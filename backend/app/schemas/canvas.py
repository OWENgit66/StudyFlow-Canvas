"""Normalize Canvas payloads; extra upstream fields are deliberately ignored."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt, computed_field


class CanvasSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class CanvasTerm(CanvasSchema):
    id: PositiveInt
    name: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class CanvasCourse(CanvasSchema):
    canvas_course_id: PositiveInt = Field(validation_alias="id")
    # Canvas may return only id/access_restricted_by_date for restricted courses.
    name: str | None = None
    course_code: str | None = None
    workflow_state: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    enrollment_term_id: PositiveInt | None = None
    term: CanvasTerm | None = None


class CanvasModule(CanvasSchema):
    module_id: PositiveInt = Field(validation_alias="id")
    name: str
    position: NonNegativeInt
    workflow_state: str | None = None


class CanvasModuleItem(CanvasSchema):
    item_id: PositiveInt = Field(validation_alias="id")
    module_id: PositiveInt
    title: str
    type: str  # Retain unknown/new item types without breaking discovery.
    position: NonNegativeInt | None = None
    content_id: PositiveInt | None = None

    @computed_field
    @property
    def canvas_file_id(self) -> int | None:
        return self.content_id if self.type == "File" else None


class CanvasFile(CanvasSchema):
    canvas_file_id: PositiveInt = Field(validation_alias="id")
    filename: str = Field(min_length=1)
    display_name: str | None = None
    content_type: str | None = Field(default=None, validation_alias="content-type")
    size: NonNegativeInt
    created_at: datetime | None = None
    updated_at: datetime | None = None
    download_url: str | None = Field(default=None, validation_alias="url", repr=False)
    locked_for_user: bool = False


class CanvasStatus(BaseModel):
    configured: bool
    connected: bool
    message: str | None = None
