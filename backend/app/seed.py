"""Explicit, repeatable development data. Never executed during app startup."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import build_engine, create_session_factory, init_db
from app.models import Course, Resource, Semester, Week


def seed_demo(db: Session) -> None:
    semester = db.scalar(select(Semester).where(Semester.year == 2026, Semester.term == "S2"))
    if semester is None:
        semester = Semester(name="2026 Semester 2", year=2026, term="S2")
        db.add(semester)
        db.flush()
    course = db.scalar(select(Course).where(Course.semester_id == semester.id, Course.code == "COMPXXXX"))
    if course is None:
        course = Course(semester=semester, code="COMPXXXX", name="Computer Networks")
        db.add(course)
        db.flush()
    for number, title in [(1, "Introduction"), (2, "Link Layer")]:
        week = db.scalar(select(Week).where(Week.course_id == course.id, Week.week_number == number))
        if week is None:
            week = Week(course=course, week_number=number, title=title)
            db.add(week)
            db.flush()
        if number == 2:
            resource = db.scalar(select(Resource).where(Resource.week_id == week.id, Resource.filename == "week2-lecture.pdf"))
            if resource is None:
                db.add(Resource(week=week, filename="week2-lecture.pdf", file_type="pdf"))


def main() -> None:
    engine = build_engine(Settings().database_url)
    try:
        init_db(engine)
        with create_session_factory(engine).begin() as db:
            seed_demo(db)
        print("Development seed ready. No real files or Canvas IDs were added.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
