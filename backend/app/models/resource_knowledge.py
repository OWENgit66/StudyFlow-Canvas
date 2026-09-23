"""Canonical resource-level structured knowledge, additive to Phase 2 tables."""
from sqlalchemy import ForeignKey,JSON,String
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from app.models.common import Timestamps

class ResourceKnowledge(Timestamps,Base):
    __tablename__='resource_knowledge'
    resource_id: Mapped[int]=mapped_column(ForeignKey('resources.id'),primary_key=True)
    payload: Mapped[dict]=mapped_column(JSON)
    source_fingerprint: Mapped[str]=mapped_column(String(64))
    provider: Mapped[str]=mapped_column(String(50))
    model: Mapped[str]=mapped_column(String(200))
