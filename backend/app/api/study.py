"""Read-only presentation endpoints; generation stays in existing services."""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.database import get_db
from app.models import Course, Resource, Semester, SyncRecord, Week
from app.models.common import ResourceStatus
from app.schemas.course import CourseRead
from app.schemas.study import CourseCard, DashboardRead, StudyResource, SyncSummary
from app.services.material_paths import material_root, resolve_database_path, sanitize_component
from app.services.semester_scope import active_semester
from app.services.knowledge_service import KnowledgeService
from app.services.document_service import DocumentService
from app.services.parsing_health import read_health

router = APIRouter(prefix="/api", tags=["study"])
DB = Annotated[Session, Depends(get_db)]
ID = Annotated[int, PathParam(gt=0)]


def get_material_root() -> Path:
    return material_root(Settings())


def registered_file(resource: Resource, root: Path) -> Path | None:
    if not resource.local_path:
        return None
    try:
        path = resolve_database_path(resource.local_path)
        # resolve() follows symlinks before checking containment.
        if path.is_relative_to(root.resolve()) and path.is_file():
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


@router.get("/study/dashboard", response_model=DashboardRead)
def dashboard(db: DB):
    active = active_semester(db)
    semesters = [active] if active else []
    courses = db.scalars(select(Course).options(selectinload(Course.weeks).selectinload(Week.resources))
                         .where(Course.semester_id == active.id).order_by(Course.code, Course.id)).all() if active else []
    cards = []
    knowledge = KnowledgeService(DocumentService(Settings()))
    for course in courses:
        weeks = sorted(course.weeks, key=lambda week: week.week_number)
        cards.append(CourseCard(**CourseRead.model_validate(course).model_dump(),
            module_count=len(weeks), latest_module=weeks[-1].title if weeks else None,
            current_knowledge_count=sum(len(knowledge.current_ids(db, week.id)) for week in weeks),
            parsed_resource_count=sum(resource.sync_status in {ResourceStatus.parsed, ResourceStatus.completed}
                                      for week in weeks for resource in week.resources)))
    latest = db.scalar(select(SyncRecord).order_by(SyncRecord.id.desc()).limit(1))
    return DashboardRead(semesters=semesters, active_semester=active, courses=cards,
                         latest_sync=SyncSummary.model_validate(latest) if latest else None)


@router.get("/weeks/{week_id}/resources", response_model=list[StudyResource])
def resources(week_id: ID, db: DB, root: Annotated[Path, Depends(get_material_root)]):
    if db.get(Week, week_id) is None:
        raise HTTPException(404, "Module not found")
    rows = db.scalars(select(Resource).where(Resource.week_id == week_id).order_by(Resource.filename, Resource.id))
    result = []
    for resource in rows:
        path = registered_file(resource, root)
        try:
            size = path.stat().st_size if path else None
        except OSError:
            path, size = None, None
        result.append(StudyResource(id=resource.id, week_id=resource.week_id,
            canvas_file_id=resource.canvas_file_id, filename=resource.filename, file_type=resource.file_type,
            resource_type=resource.resource_type,
            sync_status=resource.sync_status, file_available=path is not None, size_bytes=size,
            parsing_health=read_health(resource, root)))
    return result


@router.get("/resources/{resource_id}/file")
def file(resource_id: ID, db: DB, root: Annotated[Path, Depends(get_material_root)],
         download: Annotated[bool, Query()] = False):
    resource = db.get(Resource, resource_id)
    path = registered_file(resource, root) if resource else None
    if path is None:
        raise HTTPException(404, "Original material is not available")
    # Only PDFs open inline. Other types download rather than execute active content.
    is_pdf = path.suffix.lower() == ".pdf" and resource.file_type.lower() in {"pdf", "application/pdf"}
    return FileResponse(path, media_type="application/pdf" if is_pdf else "application/octet-stream",
        filename=sanitize_component(resource.filename),
        content_disposition_type="inline" if is_pdf and not download else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
