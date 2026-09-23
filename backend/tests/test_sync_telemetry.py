from copy import deepcopy
from unittest.mock import Mock

from app.schemas.canvas import CanvasFile
from app.services.ai_errors import AITransientError
from app.services.sync_service import request_cancellation
from test_sync import sync_setup, run, pdf_bytes, NOW


def capture(setup):
    snapshots = []
    service = setup[0]
    original = service._save
    def save(db, record):
        original(db, record)
        snapshots.append(dict(total=record.files_discovered, completed=record.details['files_analyzed'],
                              skipped=record.files_skipped, failed=record.files_failed,
                              **deepcopy(record.details)))
    service._save = save
    return snapshots


def test_discovery_finishes_before_processing_and_steps_only_complete_after_work(db, sync_setup):
    snapshots = capture(sync_setup)
    canvas = sync_setup[1]
    canvas.metadata[202] = CanvasFile(id=202, filename='second.pdf', size=10, updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    original_download = canvas.download_file
    def download(*args, **kwargs):
        current = snapshots[-1]
        assert current['discovery_complete'] and current['total'] == 2
        assert current['progress']['steps']['download'] == 'current'
        assert current['progress']['steps']['parse'] == 'pending'
        return original_download(*args, **kwargs)
    canvas.download_file = download
    result = run(db, sync_setup)
    first = [s for s in snapshots if s['progress'].get('canvas_file_id') == 201]
    generation = next(s for s in first if s['progress'].get('batch') == 1)
    assert generation['completed'] == 0
    assert generation['progress']['batches'] == 1
    assert generation['progress']['steps'] == dict(discovery='completed', download='completed', parse='completed',
                                                  generation='current', review='pending', persistence='pending')
    review = next(s for s in first if s['progress']['stage'] == 'review')
    assert review['progress']['steps']['generation'] == 'completed'
    assert review['progress']['steps']['review'] == 'current'
    saving = next(s for s in first if s['progress']['stage'] == 'persistence')
    assert saving['progress']['steps']['review'] == 'completed'
    assert saving['progress']['steps']['persistence'] == 'current'
    assert saving['completed'] == 0
    assert result.details['files_analyzed'] == 2
    assert set(result.details['progress']['steps'].values()) == {'completed'}
    assert not result.details['progress']['processing']
    assert all(s['progress']['updated_at'] for s in snapshots)


def test_failure_telemetry_remains_visible_and_next_file_resets_steps(db, sync_setup):
    snapshots = capture(sync_setup)
    canvas = sync_setup[1]
    canvas.metadata[202] = CanvasFile(id=202, filename='next.pdf', size=10, updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    canvas.fail_download.add(201)
    result = run(db, sync_setup)
    failure = next(s for s in snapshots if s['progress'].get('steps', {}).get('download') == 'failed')
    assert failure['progress']['filename'] == 'lecture.pdf' and not failure['progress']['processing']
    assert failure['progress']['steps']['parse'] == 'pending'
    following = next(s for s in snapshots if s['progress'].get('canvas_file_id') == 202)
    assert following['progress']['steps']['download'] == 'pending'
    assert result.files_failed == 1 and result.details['files_analyzed'] == 1
    assert result.details['errors'][0]['filename'] == 'lecture.pdf'


def test_cancel_preserves_known_total_and_unprocessed_resources(db, sync_setup):
    from sqlalchemy import select
    from app.models import SyncRecord
    canvas = sync_setup[1]
    canvas.metadata[202] = CanvasFile(id=202, filename='later.pdf', size=10, updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    provider = sync_setup[4]
    original = provider.generate
    def generate(*args):
        value = original(*args)
        assert request_cancellation(db.scalar(select(SyncRecord.id)))
        return value
    provider.generate = generate
    result = run(db, sync_setup)
    assert result.status == 'cancelled' and result.details['discovery_complete']
    assert result.files_discovered == 2 and result.details['files_analyzed'] == 0
    assert not result.details['progress']['processing']
    assert canvas.downloads == [201]


def test_review_failure_is_not_reported_as_completed_or_as_generation(db, sync_setup):
    service = sync_setup[0]
    original_factory = service.ai_factory
    def factory():
        ai = original_factory()
        base = ai._generate
        def response(stage, *args):
            if stage == 'semantic_validation':
                raise AITransientError('PRIVATE')
            return base(stage, *args)
        ai._generate = response
        return ai
    service.ai_factory = factory
    result = run(db, sync_setup)
    assert result.files_failed == 1
    assert result.details['errors'][0]['stage'] == 'review'
    assert result.details['progress']['steps']['review'] == 'failed'
    assert result.details['progress']['steps']['persistence'] == 'pending'
    assert result.details['progress']['steps']['generation'] == 'completed'


def test_partial_discovery_does_not_claim_complete_scope(db, sync_setup):
    sync_setup[1].get_module_items = Mock(side_effect=RuntimeError('PRIVATE'))
    result = run(db, sync_setup)
    assert result.details['discovery_incomplete']
    assert result.files_discovered == 0 and result.status == 'completed_with_errors'
