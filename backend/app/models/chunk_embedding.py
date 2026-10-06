"""Disposable local index; original text remains in DocumentChunk only."""
from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import UTCDateTime, utc_now


class ChunkEmbedding(Base):
    __tablename__ = 'chunk_embeddings'

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey('document_chunks.id', ondelete='CASCADE'), primary_key=True)
    model: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
