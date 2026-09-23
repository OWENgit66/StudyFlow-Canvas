from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import CreatedAt


class DocumentChunk(CreatedAt, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("resource_id", "chunk_index"),
        CheckConstraint("page_number > 0"), CheckConstraint("chunk_index >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    page_number: Mapped[int]
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    resource: Mapped["Resource"] = relationship(back_populates="chunks")
