"""Synchronous single-worker orchestration; all external IO stays in existing services."""
from copy import deepcopy
import logging
from pathlib import Path
from threading import Event, Lock

from sqlalchemy import delete, select
from app.models import Resource, SyncRecord, Concept, Question, Course, Week
from app.models.common import ResourceStatus, SyncStatus, utc_now
from app.repositories import sync as repository
from app.schemas.sync_record import SyncRecordRead
from app.services.document_processing import process_resource
from app.services.material_service import download_resource
from app.services.material_paths import resolve_database_path
from app.services.semester_scope import exclusion_reason

logger = logging.getLogger(__name__)
_sync_lock = Lock()  # MVP requires one backend worker; background work stays in-process.
_cancel_event = Event()
_active_sync_id = None
PIPELINE = ('discovery', 'download', 'parse', 'generation', 'review', 'persistence')


class SyncCancelled(Exception):
    pass


def request_cancellation(sync_id):
    if _sync_lock.locked() and _active_sync_id == sync_id:
        _cancel_event.set()
        return True
    return False


def cancellation_requested(sync_id):
    return _active_sync_id == sync_id and _cancel_event.is_set()


def recover_interrupted(db):
    """Only called on single-worker startup, never resume abandoned paid work."""
    for record in db.scalars(select(SyncRecord).where(SyncRecord.status == SyncStatus.running)):
        record.status, record.completed_at = SyncStatus.cancelled, utc_now()
        record.details = {**record.details, 'progress': {**record.details.get('progress', {}), 'stage': 'cancelled',
                          'processing': False, 'updated_at': utc_now().isoformat()},
                          'cancellation': {'reason': 'Backend stopped before this sync finished.'}}
    db.commit()


class SyncBusyError(Exception):
    pass


class SyncService:
    def __init__(self, settings, canvas_factory, documents, knowledge, ai_factory):
        self.settings, self.canvas_factory = settings, canvas_factory
        self.documents, self.knowledge, self.ai_factory = documents, knowledge, ai_factory

    def reserve(self, db, request, *, dry_run=False):
        global _active_sync_id
        if not _sync_lock.acquire(blocking=False):
            raise SyncBusyError('A sync is already running.')
        try:
            semester, selected_course = repository.select_semester(db, request, self.settings.sync_semester_id)
            record = SyncRecord(details={'dry_run': dry_run, 'scope': request.model_dump(),
                'files_parsed': 0, 'files_analyzed': 0, 'files_checked': 0, 'events': [], 'errors': [], 'usage': {},
                'progress': {'stage': 'discovery', 'processing': False, 'updated_at': utc_now().isoformat()},
                'discovery_complete': False, 'cancel_requested': False})
            db.add(record)
            db.commit()
            _active_sync_id = record.id
            _cancel_event.clear()
            return record
        except Exception:
            _sync_lock.release()
            raise

    def run(self, db, request, *, dry_run=False, reserved_id=None):
        global _active_sync_id
        record = self.reserve(db, request, dry_run=dry_run) if reserved_id is None else db.get(SyncRecord, reserved_id)
        try:
            record_id = record.id
            semester, selected_course = repository.select_semester(db, request, self.settings.sync_semester_id)
            logger.info('Starting Canvas sync %d', record_id)
            seen = set()
            pending = []  # Discover the selected scope before processing; no external queue.
            try:
                self._checkpoint()
                with self.canvas_factory() as canvas:
                    courses = canvas.get_courses()
                    included, excluded = [], []
                    for remote in courses:
                        reason = exclusion_reason(remote, semester)
                        identity = {'canvas_course_id': remote.canvas_course_id, 'code': remote.course_code,
                                    'name': remote.name}
                        if reason:
                            excluded.append({**identity, 'reason': reason})
                        else:
                            included.append(remote)
                    record.details = {**record.details, 'courses_visible': len(courses),
                        'courses_included': len(included), 'courses_excluded': len(excluded),
                        'included_courses': [{'canvas_course_id': c.canvas_course_id, 'code': c.course_code, 'name': c.name} for c in included],
                        'excluded_courses': excluded}
                    self._save(db, record)
                    courses = included
                    if selected_course:
                        courses = [c for c in courses if c.canvas_course_id == selected_course.canvas_course_id]
                        if not courses:
                            raise ValueError('Scoped course not in the active Canvas term.')
                    for remote in courses:
                        try:
                            self._checkpoint()
                            self._progress(db, record, 'checking', course_code=remote.course_code,
                                course_name=remote.name, course_id=remote.canvas_course_id,
                                module=None, module_id=None, filename=None, resource_id=None)
                            if not remote.name or not remote.course_code:
                                continue  # Restricted Canvas courses expose only an ID.
                            course = (db.scalar(select(Course).where(Course.canvas_course_id == remote.canvas_course_id))
                                      if dry_run else repository.upsert_course(db, remote, semester))
                            if course and course.semester_id != semester.id:
                                continue
                            if not dry_run and course is None:
                                continue
                            if not dry_run:
                                db.commit()
                            record.courses_processed += 1
                            self._save(db, record)
                            self._course(db, record, canvas, course, remote, request, seen, dry_run, pending)
                        except SyncCancelled:
                            raise
                        except Exception:
                            db.rollback()
                            record = db.get(SyncRecord, record_id)
                            self._error(db, record, 'discovery', course_id=remote.canvas_course_id)
                    self._checkpoint()
                    record.details = {**record.details, 'discovery_complete': True,
                                      'discovery_incomplete': bool(record.details['errors'])}
                    self._save(db, record)
                    for week_id, file_id, context in pending:
                        self._progress(db, record, 'checking', **context, processing=True,
                                       steps={step: 'pending' for step in PIPELINE}, batch=None, batches=None,
                                       parsing_review_pages=None)
                        self._file(db, record, canvas, db.get(Week, week_id) if week_id else None, file_id, dry_run)
                    self._checkpoint()
                    record.status = SyncStatus.completed_with_errors if record.details['errors'] else SyncStatus.completed
            except SyncCancelled:
                db.rollback()
                record = db.get(SyncRecord, record_id)
                record.status = SyncStatus.cancelled
                record.details = {**record.details, 'cancel_requested': True,
                                  'cancellation': {'reason': 'Cancelled by user at a safe processing boundary.'}}
            except Exception:
                db.rollback()
                record = db.get(SyncRecord, record_id)
                self._error(db, record, 'discovery')
                record.status = SyncStatus.failed
            record.completed_at = utc_now()
            record.details = {**record.details, 'progress': {**record.details.get('progress', {}),
                              'stage': record.status.value, 'processing': False}}
            self._save(db, record)
            logger.info('Sync %d finished: %s, downloaded %d, updated %d, skipped %d, failed %d',
                        record.id, record.status, record.files_downloaded, record.files_updated,
                        record.files_skipped, record.files_failed)
            return SyncRecordRead.model_validate(record)
        finally:
            _active_sync_id = None
            _sync_lock.release()

    @staticmethod
    def _checkpoint():
        if _cancel_event.is_set():
            raise SyncCancelled()

    def _progress(self, db, record, stage, **context):
        self._checkpoint()
        progress = {**record.details.get('progress', {}), **context, 'stage': stage}
        if stage in PIPELINE:
            progress['steps'] = {**progress.get('steps', {}), stage: 'current'}
        record.details = {**record.details, 'progress': progress}
        self._save(db, record)

    def _step(self, db, record, step, state):
        progress = record.details.get('progress', {})
        record.details = {**record.details, 'progress': {**progress,
                          'steps': {**progress.get('steps', {}), step: state}}}
        self._save(db, record)

    def _ai_progress(self, db, record, step, ai):
        self._checkpoint()
        if step.endswith('_complete'):
            self._step(db, record, step.removesuffix('_complete'), 'completed')
        else:
            self._progress(db, record, step, batch=getattr(ai, 'batch_index', None) if step == 'generation' else None,
                           batches=getattr(ai, 'batch_total', None) if step == 'generation' else None)

    def _course(self, db, record, canvas, course, remote, request, seen, dry_run, pending):
        modules = canvas.get_modules(remote.canvas_course_id)
        if request.module_id:
            modules = [m for m in modules if m.module_id == request.module_id]
            if not modules:
                raise ValueError('Scoped module not found.')
        found_target = False
        for module in modules:
            try:
                self._progress(db, record, 'checking', module=module.name, module_id=module.module_id,
                               filename=None, resource_id=None)
                week = None if dry_run else repository.upsert_week(db, course, module)
                if not dry_run:
                    db.commit()
                items = canvas.get_module_items(remote.canvas_course_id, module.module_id)
            except SyncCancelled:
                raise
            except Exception:
                db.rollback()
                self._error(db, record, 'discovery', course_id=remote.canvas_course_id, module_id=module.module_id)
                continue
            for item in items:
                self._checkpoint()
                file_id = item.canvas_file_id
                if not file_id or (request.file_id and file_id != request.file_id):
                    continue
                found_target = True
                if file_id in seen:
                    continue  # One canonical resource even when linked from multiple modules.
                seen.add(file_id)
                record.files_discovered += 1
                self._save(db, record)
                pending.append((week.id if week else None, file_id, dict(course_id=remote.canvas_course_id,
                    course_code=remote.course_code, course_name=remote.name, module_id=module.module_id,
                    module=module.name, filename=item.title, resource_id=None, canvas_file_id=file_id)))
        if request.file_id and not found_target:
            self._error(db, record, 'discovery', file_id=request.file_id, course_id=remote.canvas_course_id)

    def _file(self, db, record, canvas, week, file_id, dry_run):
        resource_id, stage = None, 'discovery'
        failed_usage = None
        try:
            self._progress(db, record, 'checking', resource_id=None)
            self._step(db, record, 'discovery', 'current')
            metadata = canvas.get_file(file_id)
            resource = repository.find_resource(db, file_id)
            resource_id = resource.id if resource else None
            classification = repository.classify(resource, metadata)
            self._progress(db, record, 'checking', filename=metadata.filename, resource_id=resource_id)
            self._event(db, record, file_id, resource_id, 'discovery', classification)
            if dry_run:
                self._detail_count(record, 'files_checked')
                if classification == 'UNCHANGED':
                    record.files_skipped += 1
                record.details = {**record.details, 'progress': {**record.details['progress'], 'processing': False}}
                self._save(db, record)
                return
            if classification == 'UNCHANGED' and resource.sync_status == ResourceStatus.completed:
                record.files_skipped += 1
                self._event(db, record, file_id, resource_id, 'skip', 'UNCHANGED')
                return
            if classification == 'UNCHANGED' and resource.sync_stage == 'unsupported':
                record.files_skipped += 1
                self._event(db, record, file_id, resource_id, 'skip', 'unsupported')
                return
            if resource is None:
                resource = Resource(week_id=week.id, canvas_file_id=file_id,
                    filename=metadata.filename, file_type=Path(metadata.filename).suffix.lower().lstrip('.') or 'unknown',
                    sync_stage='download')
                db.add(resource)
                db.commit()
                resource_id = resource.id
            self._progress(db, record, 'checking', resource_id=resource_id)
            if classification == 'UPDATED':
                resource.sync_stage, resource.sync_status = 'download', ResourceStatus.pending
                # Historical canonical payload stays for audit; projections must not claim it is current.
                for model in (Concept, Question):
                    db.execute(delete(model).where(model.resource_id == resource.id))
                self.knowledge.refresh_summary(db, resource.week_id)
                db.commit()
            stage = resource.sync_stage or ('knowledge' if resource.sync_status == ResourceStatus.parsed else 'download')
            if stage == 'done':
                stage = 'knowledge'
            # Resume only already-committed work. New/updated files start pending.
            if stage in {'parse', 'knowledge', 'unsupported'}:
                self._step(db, record, 'download', 'completed')
            if stage == 'knowledge':
                self._step(db, record, 'parse', 'completed')
            if stage == 'download':
                self._progress(db, record, 'download')
                resource.sync_stage = stage
                resource.sync_status = ResourceStatus.pending
                db.commit()
                if resource.local_path and not resolve_database_path(resource.local_path).is_file():
                    raise ValueError('Missing existing material requires explicit recovery.')
                download_resource(db, canvas, resource)
                resource.filename = metadata.filename
                resource.file_type = Path(metadata.filename).suffix.lower().lstrip('.') or 'unknown'
                resource.canvas_updated_at = metadata.updated_at
                resource.sync_stage = 'parse' if resource.file_type == 'pdf' else 'unsupported'
                db.commit()
                record.files_downloaded += 1
                if classification == 'UPDATED':
                    record.files_updated += 1
                self._event(db, record, file_id, resource_id, 'download', 'downloaded')
                stage = resource.sync_stage
            if stage == 'unsupported':
                record.files_skipped += 1
                self._event(db, record, file_id, resource_id, 'skip', 'unsupported')
                return
            if stage == 'parse':
                self._progress(db, record, 'parse')
                resource.sync_stage = stage
                db.commit()
                parsed = process_resource(db, resource_id, self.documents)
                record.details = {**record.details, 'progress': {**record.details['progress'],
                    'parsing_review_pages': resource.parsing_report['health']['pages_need_review']}}
                self._save(db, record)
                if parsed.status != 'parsed' or not parsed.chunks_created:
                    raise ValueError('PDF has no usable text.')
                resource.sync_stage = 'knowledge'
                db.commit()
                self._detail_count(record, 'files_parsed')
                self._event(db, record, file_id, resource_id, 'parse', 'parsed')
                stage = 'knowledge'
            if stage != 'knowledge':
                raise ValueError('Unknown resource resume stage.')
            # Existing KnowledgeService verifies fresh PDF warnings/chunks internally;
            # resume does not repeat process_resource or replace valid stored chunks.
            resource.sync_stage, resource.sync_status = 'knowledge', ResourceStatus.parsed
            db.commit()
            ai = None
            try:
                ai = self.ai_factory()  # Lazy: unchanged files never initialize a provider.
                ai.on_stage = lambda step: self._ai_progress(db, record, step, ai)
                self._progress(db, record, 'generation')
                self.knowledge.generate(db, resource_id, ai)
            finally:
                if ai is not None:
                    self._usage(record, ai)
                    failed_usage = deepcopy(record.details['usage'])
            resource = db.get(Resource, resource_id)
            resource.sync_stage = 'done'
            db.commit()
            self._detail_count(record, 'files_analyzed')
            self._event(db, record, file_id, resource_id, 'knowledge', 'completed')
        except SyncCancelled:
            db.rollback()
            if failed_usage is not None:
                record.details = {**record.details, 'usage': failed_usage}
                self._save(db, record)
            raise
        except Exception:
            # Never log exception text, provider bodies, prompts or signed URLs.
            db.rollback()
            if resource_id and stage in {'download', 'parse', 'knowledge'}:
                resource = db.get(Resource, resource_id)
                resource.sync_status = ResourceStatus.failed
                resource.sync_stage = stage
                db.commit()
            if failed_usage is not None:
                details = deepcopy(record.details)
                details['usage'] = failed_usage
                record.details = details
            record.files_failed += 1
            failed_step = record.details.get('progress', {}).get('stage', stage)
            self._error(db, record, failed_step if failed_step in PIPELINE else stage,
                        file_id=file_id, resource_id=resource_id)

    @staticmethod
    def _detail_count(record, key):
        details = deepcopy(record.details)
        details[key] += 1
        record.details = details

    @staticmethod
    def _usage(record, ai):
        details = deepcopy(record.details)
        usage = details['usage']
        usage['requests'] = usage.get('requests', 0) + sum(ai.request_counts.values())
        for entry in ai.usage:
            if any(isinstance(entry.get(key), int) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
                usage['requests_with_token_usage'] = usage.get('requests_with_token_usage', 0) + 1
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens',
                        'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'):
                if isinstance(entry.get(key), int):
                    usage[key] = usage.get(key, 0) + entry[key]
        record.details = details

    def _event(self, db, record, file_id, resource_id, stage, outcome):
        details = deepcopy(record.details)
        details['events'].append(dict(file_id=file_id, resource_id=resource_id, stage=stage, outcome=outcome))
        progress = details.get('progress', {})
        steps = progress.get('steps', {})
        completed_step = {'discovery': 'discovery', 'download': 'download', 'parse': 'parse', 'knowledge': 'persistence'}.get(stage)
        if completed_step:
            steps[completed_step] = 'completed'
        if stage == 'skip':
            steps = {key: ('skipped' if value == 'pending' else value) for key, value in steps.items()}
        details['progress'] = {**progress, 'steps': steps,
                               'processing': False if stage in {'skip', 'knowledge'} else progress.get('processing', False)}
        record.details = details
        logger.info('Sync %d file %d resource %s: %s -> %s', record.id, file_id, resource_id, stage, outcome)
        self._save(db, record)

    def _error(self, db, record, stage, **identity):
        details = deepcopy(record.details)
        current = details.get('progress', {})
        if identity.get('file_id'):
            failed_step = stage if stage in PIPELINE else 'discovery'
            details['progress'] = {**current, 'processing': False,
                                   'steps': {**current.get('steps', {}), failed_step: 'failed'}}
        details['errors'].append(dict(stage=stage, message=f'{stage.capitalize()} failed; retry or inspect local configuration/source.',
                                     course_code=current.get('course_code'), filename=current.get('filename'), **identity))
        record.details = details
        record.error_message = f"{len(details['errors'])} failure(s); see details.errors."
        logger.warning('Sync %d failed at %s for file %s', record.id, stage, identity.get('file_id'))
        self._save(db, record)

    @staticmethod
    def _save(db, record):
        # Service-owned commits keep running progress readable in a second session.
        record.details = {**record.details, 'progress': {**record.details.get('progress', {}),
                          'updated_at': utc_now().isoformat()}}
        if _cancel_event.is_set():
            record.details = {**record.details, 'cancel_requested': True}
        db.add(record)
        db.commit()
