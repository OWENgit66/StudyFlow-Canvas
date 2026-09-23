"""Shared timestamps and constrained enum values."""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite stores UTC without an offset; Python always receives aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class ResourceStatus(StrEnum):
    pending = "pending"
    downloaded = "downloaded"
    parsed = "parsed"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Importance(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class SyncStatus(StrEnum):
    running = "running"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"
    cancelled = "cancelled"


def enum_column(enum_class):
    return Enum(
        enum_class, native_enum=False, create_constraint=True, validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
