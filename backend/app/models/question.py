from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import CreatedAt


class Question(CreatedAt, Base):
    __tablename__ = "questions"
    __table_args__ = (
        ForeignKeyConstraint(["resource_id", "week_id"], ["resources.id", "resources.week_id"]),
        CheckConstraint("source_page > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id"), index=True)
    resource_id: Mapped[int] = mapped_column(index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_page: Mapped[int | None]
    week: Mapped["Week"] = relationship(back_populates="questions", foreign_keys=[week_id])
    resource: Mapped["Resource"] = relationship(back_populates="questions", foreign_keys=[resource_id])
