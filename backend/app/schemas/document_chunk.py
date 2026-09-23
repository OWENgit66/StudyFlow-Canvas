from pydantic import ConfigDict, Field, NonNegativeInt, PositiveInt

from app.schemas.common import CreatedRead, Schema


class DocumentChunkCreate(Schema):
    model_config = ConfigDict(str_strip_whitespace=False)
    resource_id: PositiveInt
    page_number: PositiveInt
    chunk_index: NonNegativeInt
    content: str = Field(min_length=1)


class DocumentChunkRead(DocumentChunkCreate, CreatedRead):
    model_config = ConfigDict(str_strip_whitespace=False)
    pass
