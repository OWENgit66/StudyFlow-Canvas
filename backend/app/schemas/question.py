from pydantic import Field, PositiveInt

from app.schemas.common import CreatedRead, Schema


class QuestionCreate(Schema):
    week_id: PositiveInt
    resource_id: PositiveInt
    question: str = Field(min_length=1)
    answer: str
    source_page: PositiveInt | None = None


class QuestionRead(QuestionCreate, CreatedRead):
    pass
