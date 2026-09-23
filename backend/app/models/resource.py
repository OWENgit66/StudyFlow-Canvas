from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import ResourceStatus, Timestamps, UTCDateTime, enum_column


class Resource(Timestamps, Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("week_id", "canvas_file_id"),
        UniqueConstraint("id", "week_id"),  # composite knowledge source FK
        CheckConstraint("canvas_file_id > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id"), index=True)
    canvas_file_id: Mapped[int | None] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    local_path: Mapped[str | None] = mapped_column(String(1000))
    canvas_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sync_stage: Mapped[str | None] = mapped_column(String(20))
    parsing_report: Mapped[dict | None] = mapped_column(JSON)
    sync_status: Mapped[ResourceStatus] = mapped_column(
        enum_column(ResourceStatus), default=ResourceStatus.pending
    )
    week: Mapped["Week"] = relationship(back_populates="resources")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="resource")
    concepts: Mapped[list["Concept"]] = relationship(
        back_populates="resource", foreign_keys="Concept.resource_id"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="resource", foreign_keys="Question.resource_id"
    )
