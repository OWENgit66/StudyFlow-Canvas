"""Small student-facing read models; never include local storage paths."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.common import ResourceStatus, ResourceType, SyncStatus
from app.schemas.course import CourseRead
from app.schemas.semester import SemesterRead
from app.schemas.parsing_health import ParsingHealth


class CourseCard(CourseRead):
    module_count: int
    parsed_resource_count: int
    latest_module: str | None
    current_knowledge_count: int = 0


class SyncProgress(BaseModel):
    stage: str = 'discovery'
    course_code: str | None = None
    course_name: str | None = None
    module: str | None = None
    filename: str | None = None
    course_id: int | None = None
    module_id: int | None = None
    resource_id: int | None = None
    updated_at: datetime | None = None
    processing: bool = False
    steps: dict[str, str] = Field(default_factory=dict)
    batch: int | None = None
    batches: int | None = None
    parsing_review_pages: int | None = None


class SyncFileIssue(BaseModel):
    stage: str
    course_code: str | None = None
    filename: str | None = None


class SyncDisplayDetails(BaseModel):
    dry_run: bool = False
    progress: SyncProgress = Field(default_factory=SyncProgress)
    files_parsed: int = 0
    files_analyzed: int = 0
    files_checked: int = 0
    cancel_requested: bool = False
    discovery_complete: bool = False
    discovery_incomplete: bool = False
    errors: list[SyncFileIssue] = Field(default_factory=list)


class SyncSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: SyncStatus
    started_at: datetime
    completed_at: datetime | None
    courses_processed: int
    files_discovered: int
    files_downloaded: int
    files_updated: int
    files_skipped: int
    files_failed: int
    details: SyncDisplayDetails = Field(default_factory=SyncDisplayDetails)


class DashboardRead(BaseModel):
    semesters: list[SemesterRead]
    courses: list[CourseCard]
    latest_sync: SyncSummary | None
    active_semester: SemesterRead | None = None


class StudyResource(BaseModel):
    id: int
    week_id: int
    canvas_file_id: int | None
    filename: str
    file_type: str
    resource_type: ResourceType = ResourceType.other
    sync_status: ResourceStatus
    file_available: bool
    size_bytes: int | None
    parsing_health: ParsingHealth | None = None
