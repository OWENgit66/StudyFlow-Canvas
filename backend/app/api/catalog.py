from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories import catalog
from app.schemas.course import CourseRead
from app.schemas.semester import SemesterRead
from app.schemas.week import WeekRead
from app.services.semester_scope import active_semester
from pathlib import Path as FilePath
from app.api.study import get_material_root
from app.services.parsing_health import read_health

router = APIRouter(prefix="/api", tags=["catalog"])
DB = Annotated[Session, Depends(get_db)]
EntityID = Annotated[int, Path(gt=0)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/semesters", response_model=list[SemesterRead])
def list_semesters(db: DB, offset: Offset = 0, limit: Limit = 100):
    return catalog.list_semesters(db, offset, limit)


@router.get("/courses", response_model=list[CourseRead])
def list_courses(db: DB, offset: Offset = 0, limit: Limit = 100, semester_id: Annotated[int | None, Query(gt=0)] = None):
    active = active_semester(db)
    selected = semester_id or (active.id if active else None)
    return catalog.list_courses(db, offset, limit, selected) if selected else []


@router.get("/courses/{course_id}", response_model=CourseRead)
def get_course(course_id: EntityID, db: DB):
    course = catalog.get_course(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/courses/{course_id}/weeks", response_model=list[WeekRead])
def list_weeks(course_id: EntityID, db: DB, root: Annotated[FilePath, Depends(get_material_root)]):
    if catalog.get_course(db, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    result = []
    for week in catalog.list_weeks(db, course_id):
        result.append(week_read(week, root))
    return result


def week_read(week, root):
    reports = [read_health(resource, root) for resource in week.resources]
    return WeekRead.model_validate(week).model_copy(update={
        'resource_count': len(reports),
        'resources_need_review': sum(r.status in {'review', 'unable_to_parse'} for r in reports),
        'parsing_reports_unavailable': sum(r.status in {'unknown', 'stale', 'unavailable'} for r in reports),
    })


@router.get("/weeks/{week_id}", response_model=WeekRead)
def get_week(week_id: EntityID, db: DB, root: Annotated[FilePath, Depends(get_material_root)]):
    week = catalog.get_week(db, week_id)
    if week is None:
        raise HTTPException(status_code=404, detail="Week not found")
    return week_read(week, root)
