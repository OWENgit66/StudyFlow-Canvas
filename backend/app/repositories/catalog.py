from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Semester, Week


def list_semesters(db: Session, offset: int, limit: int):
    return db.scalars(select(Semester).order_by(Semester.year.desc(), Semester.id).offset(offset).limit(limit)).all()


def list_courses(db: Session, offset: int, limit: int, semester_id: int):
    return db.scalars(select(Course).where(Course.semester_id == semester_id)
                      .order_by(Course.code, Course.id).offset(offset).limit(limit)).all()


def get_course(db: Session, course_id: int):
    return db.get(Course, course_id)


def list_weeks(db: Session, course_id: int):
    return db.scalars(select(Week).where(Week.course_id == course_id).order_by(Week.week_number)).all()


def get_week(db: Session, week_id: int):
    return db.get(Week, week_id)
