from pydantic import AwareDatetime, Field, PositiveInt

from app.models.common import ResourceStatus, ResourceType
from app.schemas.common import Schema, TimestampRead


class ResourceCreate(Schema):
    week_id: PositiveInt
    canvas_file_id: PositiveInt | None = None
    filename: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=50)
    resource_type: ResourceType = ResourceType.other
    local_path: str | None = Field(default=None, max_length=1000)
    canvas_updated_at: AwareDatetime | None = None
    sync_status: ResourceStatus = ResourceStatus.pending


class ResourceRead(ResourceCreate, TimestampRead):
    pass
