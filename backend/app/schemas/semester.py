from pydantic import Field, PositiveInt

from app.schemas.common import CreatedRead, Schema


class SemesterCreate(Schema):
    name: str = Field(min_length=1, max_length=200)
    year: PositiveInt
    term: str = Field(min_length=1, max_length=30)
    is_active: bool = False
    canvas_term_id: PositiveInt | None = None


class SemesterRead(SemesterCreate, CreatedRead):
    pass
