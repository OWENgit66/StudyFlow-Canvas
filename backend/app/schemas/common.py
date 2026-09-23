from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class CreatedRead(Schema):
    id: int
    created_at: datetime


class TimestampRead(CreatedRead):
    updated_at: datetime
