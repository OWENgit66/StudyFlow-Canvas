from pydantic import Field, PositiveInt

from app.schemas.common import Schema, TimestampRead


class SummaryCreate(Schema):
    week_id: PositiveInt
    overview: str
    key_points: list[str] = Field(default_factory=list)
    exam_focus: list[str] = Field(default_factory=list)


class SummaryRead(SummaryCreate, TimestampRead):
    pass
