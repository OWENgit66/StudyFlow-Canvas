from pydantic import Field, PositiveInt

from app.schemas.common import Schema, TimestampRead


class WeekCreate(Schema):
    course_id: PositiveInt
    week_number: PositiveInt
    title: str = Field(min_length=1, max_length=250)


class WeekRead(WeekCreate, TimestampRead):
    canvas_module_id: PositiveInt | None = None
    resource_count: int = 0
    resources_need_review: int = 0
    parsing_reports_unavailable: int = 0
