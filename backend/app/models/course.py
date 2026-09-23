from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import Timestamps


class Course(Timestamps, Base):
    __tablename__ = "courses"
    __table_args__ = (CheckConstraint("canvas_course_id > 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id"), index=True)
    canvas_course_id: Mapped[int | None] = mapped_column(unique=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(250))
    semester: Mapped["Semester"] = relationship(back_populates="courses")
    weeks: Mapped[list["Week"]] = relationship(back_populates="course")
