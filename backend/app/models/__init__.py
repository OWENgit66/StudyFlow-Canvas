"""Import all models so SQLAlchemy can resolve relationships and metadata."""

from app.models.semester import Semester
from app.models.course import Course
from app.models.week import Week
from app.models.resource import Resource
from app.models.document_chunk import DocumentChunk
from app.models.summary import Summary
from app.models.concept import Concept
from app.models.question import Question
from app.models.sync_record import SyncRecord
from app.models.resource_knowledge import ResourceKnowledge

__all__ = ["Semester", "Course", "Week", "Resource", "DocumentChunk", "Summary", "Concept", "Question", "SyncRecord", "ResourceKnowledge"]
