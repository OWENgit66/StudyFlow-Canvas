from sqlalchemy import Boolean, CheckConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import CreatedAt


class Semester(CreatedAt, Base):
    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("year", "term"), CheckConstraint("year > 0"),
        Index('uq_active_semester', 'is_active', unique=True, sqlite_where=text('is_active = 1')),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    year: Mapped[int]
    term: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0')
    canvas_term_id: Mapped[int | None] = mapped_column(unique=True)
    courses: Mapped[list["Course"]] = relationship(back_populates="semester")
