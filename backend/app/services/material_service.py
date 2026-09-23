"""Explicit single-resource save, not a sync pipeline. Caller owns the DB transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Resource
from app.models.common import ResourceStatus
from app.services.canvas_errors import CanvasDownloadError
from app.services.canvas_service import CanvasService
from app.services.material_paths import MaterialContext, database_path, resolve_database_path


def download_resource(db: Session, canvas: CanvasService, resource: Resource):
    if not resource.canvas_file_id:
        raise CanvasDownloadError("Resource has no Canvas file ID.")
    db.flush()
    existing = None
    if resource.local_path:
        existing = resolve_database_path(resource.local_path)
        for other in db.scalars(select(Resource).where(Resource.id != resource.id, Resource.local_path.is_not(None))):
            if resolve_database_path(other.local_path) == existing:
                raise CanvasDownloadError("Material path is shared by another resource; cannot replace it.")
    week = resource.week
    course = week.course
    semester = course.semester
    context = MaterialContext(semester.year, semester.term, course.code, course.name, week.title)
    path = canvas.download_file(resource.canvas_file_id, context=context, existing_path=existing)
    resource.local_path = database_path(path)
    resource.sync_status = ResourceStatus.downloaded
    db.flush()
    return path
