from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import CreatedAt, Importance, enum_column


class Concept(CreatedAt, Base):
    __tablename__ = "concepts"
    __table_args__ = (
        ForeignKeyConstraint(["resource_id", "week_id"], ["resources.id", "resources.week_id"]),
        CheckConstraint("source_page > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id"), index=True)
    resource_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(250))
    definition: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    importance: Mapped[Importance] = mapped_column(enum_column(Importance), default=Importance.medium)
    source_page: Mapped[int | None]
    week: Mapped["Week"] = relationship(back_populates="concepts", foreign_keys=[week_id])
    resource: Mapped["Resource"] = relationship(back_populates="concepts", foreign_keys=[resource_id])
