"""Chunk queries and replacement. Caller controls commit/rollback."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DocumentChunk
from app.schemas.document_chunk import DocumentChunkCreate


def replace_chunks(db: Session, resource_id: int, chunks: list[DocumentChunkCreate]) -> None:
    if any(chunk.resource_id != resource_id for chunk in chunks):
        raise ValueError("Chunk resource identity mismatch")
    db.execute(delete(DocumentChunk).where(DocumentChunk.resource_id == resource_id))
    db.add_all(DocumentChunk(**chunk.model_dump()) for chunk in chunks)
    db.flush()


def list_chunks(db: Session, resource_id: int, offset: int, limit: int):
    return db.scalars(
        select(DocumentChunk).where(DocumentChunk.resource_id == resource_id)
        .order_by(DocumentChunk.chunk_index).offset(offset).limit(limit)
    ).all()
