from datetime import datetime

from sqlalchemy import CheckConstraint, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import SyncStatus, UTCDateTime, enum_column, utc_now


class SyncRecord(Base):
    __tablename__ = "sync_records"
    __table_args__ = (
        CheckConstraint("courses_processed >= 0 AND files_discovered >= 0 AND files_downloaded >= 0 "
                        "AND files_updated >= 0 AND files_skipped >= 0 AND files_failed >= 0"),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[SyncStatus] = mapped_column(enum_column(SyncStatus), default=SyncStatus.running)
    courses_processed: Mapped[int] = mapped_column(default=0)
    files_discovered: Mapped[int] = mapped_column(default=0)
    files_downloaded: Mapped[int] = mapped_column(default=0)
    files_updated: Mapped[int] = mapped_column(default=0)
    files_skipped: Mapped[int] = mapped_column(default=0)
    files_failed: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
