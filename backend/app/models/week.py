from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import Timestamps


class Week(Timestamps, Base):
    __tablename__ = "weeks"
    __table_args__ = (
        UniqueConstraint("course_id", "week_number"),
        CheckConstraint("week_number > 0"),
        Index("uq_week_canvas_module", "course_id", "canvas_module_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    week_number: Mapped[int]
    title: Mapped[str] = mapped_column(String(250))
    canvas_module_id: Mapped[int | None]
    course: Mapped["Course"] = relationship(back_populates="weeks")
    resources: Mapped[list["Resource"]] = relationship(back_populates="week")
    summary: Mapped["Summary | None"] = relationship(back_populates="week")
    concepts: Mapped[list["Concept"]] = relationship(back_populates="week")
    questions: Mapped[list["Question"]] = relationship(back_populates="week")
