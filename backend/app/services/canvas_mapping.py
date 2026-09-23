"""Pure mapping only: persistence belongs to future orchestration/repositories."""

from app.schemas.canvas import CanvasCourse
from app.schemas.course import CourseCreate


def canvas_course_to_course(course: CanvasCourse, semester_id: int) -> CourseCreate:
    if not course.name or not course.course_code:
        raise ValueError("Canvas course lacks name or course code; cannot map restricted metadata.")
    return CourseCreate(
        semester_id=semester_id, canvas_course_id=course.canvas_course_id,
        code=course.course_code, name=course.name,
    )
