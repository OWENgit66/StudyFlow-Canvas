"""Stable Canvas identities and minimal legacy Week adoption."""
import re
from sqlalchemy import select, update
from app.models import Course, Semester, Week, Resource
from app.services.canvas_mapping import canvas_course_to_course
from app.services.semester_scope import active_semester


def select_semester(db, request, configured_id):
    course = db.get(Course, request.course_id) if request.course_id else None
    if request.course_id and (course is None or course.canvas_course_id is None):
        raise ValueError('Requested course has no Canvas mapping.')
    semester = active_semester(db)
    if semester is None or not semester.canvas_term_id:
        raise ValueError('Configure one active semester and its Canvas term mapping before syncing.')
    if (request.semester_id and request.semester_id != semester.id) or (course and course.semester_id != semester.id):
        raise ValueError('Only the active semester can be synced.')
    # Legacy config must not become a second source of truth.
    if configured_id and configured_id != semester.id:
        raise ValueError('Legacy SYNC_SEMESTER_ID conflicts with the active database semester.')
    return semester, course


def upsert_course(db, remote, semester):
    course = db.scalar(select(Course).where(Course.canvas_course_id == remote.canvas_course_id))
    if course and course.semester_id != semester.id:
        return None  # Do not move historical courses between semesters.
    data = canvas_course_to_course(remote, semester.id)
    if course is None:
        course = Course(**data.model_dump())
        db.add(course)
    else:
        course.code, course.name = data.code, data.name
    db.flush()
    return course


def upsert_week(db, course, module):
    weeks = db.scalars(select(Week).where(Week.course_id == course.id)).all()
    week = next((w for w in weeks if w.canvas_module_id == module.module_id), None)
    match = re.match(r'^\s*(?:week|module|topic)\s*0*(\d+)\b', module.name, re.I)
    number = int(match[1]) if match and int(match[1]) > 0 else None
    if week is None:
        legacy = [w for w in weeks if w.canvas_module_id is None and w.title == module.name]
        if not legacy and number:
            legacy = [w for w in weeks if w.canvas_module_id is None and w.week_number == number]
        if len(legacy) == 1:
            week = legacy[0]
        else:
            used = {w.week_number for w in weeks}
            number = number if number and number not in used else max(used, default=0) + 1
            week = Week(course_id=course.id, week_number=number, title=module.name)
            db.add(week)
    week.canvas_module_id, week.title = module.module_id, module.name
    db.flush()
    return week


def find_resource(db, file_id, *, external_source_key=None):
    identity = (Resource.external_source_key == external_source_key if external_source_key
                else Resource.canvas_file_id == file_id)
    if file_id is None and not external_source_key:
        raise ValueError('A material identity is required.')
    rows = db.scalars(select(Resource).where(identity)).all()
    if len(rows) > 1:
        raise ValueError('Ambiguous legacy Canvas file identity; resolve duplicate resources.')
    return rows[0] if rows else None


def classify(resource, remote):
    if hasattr(remote, 'source_key'):
        return 'NEW' if resource is None else ('UNCHANGED' if resource.external_revision == remote.revision else 'UPDATED')
    if remote.updated_at is None or remote.updated_at.tzinfo is None:
        raise ValueError('Canvas file lacks a reliable update timestamp.')
    if resource is None:
        return 'NEW'
    if resource.canvas_updated_at is None or remote.updated_at > resource.canvas_updated_at:
        return 'UPDATED'
    return 'UNCHANGED'


def update_resource_type(db, resource, resource_type):
    """Role metadata must not touch file timestamps or invalidate current knowledge."""
    if resource.resource_type != resource_type:
        db.execute(update(Resource).where(Resource.id == resource.id).values(
            resource_type=resource_type, updated_at=Resource.updated_at))
