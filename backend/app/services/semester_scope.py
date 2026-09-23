"""One active semester, with explicit Canvas enrollment-term identity. Fail closed."""
from sqlalchemy import select
from app.models import Semester


def active_semester(db):
    return db.scalar(select(Semester).where(Semester.is_active.is_(True)))


def exclusion_reason(course, semester):
    if not semester.canvas_term_id:
        return 'active_term_not_mapped'
    term_id = course.enrollment_term_id or (course.term.id if course.term else None)
    if course.enrollment_term_id and course.term and course.term.id != course.enrollment_term_id:
        return 'conflicting_term_metadata'
    if term_id != semester.canvas_term_id:
        return 'different_term' if term_id else 'unknown_term'
    if course.workflow_state in {'completed', 'deleted', 'unpublished'}:
        return 'inactive_course'
    if not course.name or not course.course_code:
        return 'restricted_course'
    return None
