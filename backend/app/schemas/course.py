from pydantic import Field, PositiveInt

from app.schemas.common import Schema, TimestampRead


class CourseCreate(Schema):
    semester_id: PositiveInt
    canvas_course_id: PositiveInt | None = None
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=250)


class CourseRead(CourseCreate, TimestampRead):
    pass
