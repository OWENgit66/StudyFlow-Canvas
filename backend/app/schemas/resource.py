from pydantic import AwareDatetime, Field, PositiveInt
from typing import Literal

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
    classification_source: Literal['automatic', 'manual'] = 'automatic'
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_method: Literal['metadata', 'document_content', 'llm', 'manual'] | None = None


class ResourceClassificationUpdate(Schema):
    resource_type: ResourceType


class ResourceClassificationRead(ResourceClassificationUpdate):
    id: int
    classification_source: Literal['automatic', 'manual']
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_method: Literal['metadata', 'document_content', 'llm', 'manual'] | None = None
