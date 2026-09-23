from sqlalchemy import ForeignKey, JSON, Text
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import Timestamps


class Summary(Timestamps, Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id"), unique=True)
    overview: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    exam_focus: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    week: Mapped["Week"] = relationship(back_populates="summary")
