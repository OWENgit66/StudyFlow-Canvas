from typing import Self

from pydantic import AwareDatetime, Field, NonNegativeInt, model_validator

from app.models.common import SyncStatus, utc_now
from app.schemas.common import Schema


class SyncRecordCreate(Schema):
    started_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None
    status: SyncStatus = SyncStatus.running
    courses_processed: NonNegativeInt = 0
    files_discovered: NonNegativeInt = 0
    files_downloaded: NonNegativeInt = 0
    files_updated: NonNegativeInt = 0
    files_skipped: NonNegativeInt = 0
    files_failed: NonNegativeInt = 0
    error_message: str | None = None

    @model_validator(mode="after")
    def completion_follows_start(self) -> Self:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class SyncRecordRead(SyncRecordCreate):
    id: int
    details: dict = Field(default_factory=dict)
