from pydantic import Field, PositiveInt

from app.models.common import Importance
from app.schemas.common import CreatedRead, Schema


class ConceptCreate(Schema):
    week_id: PositiveInt
    resource_id: PositiveInt
    name: str = Field(min_length=1, max_length=250)
    definition: str
    explanation: str
    importance: Importance = Importance.medium
    source_page: PositiveInt | None = None


class ConceptRead(ConceptCreate, CreatedRead):
    pass
