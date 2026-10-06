from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Course, Week
from app.services.course_qa import CourseQAService
from app.services.rag_answer_service import RagAnswer
from app.services.course_index import index_status

router = APIRouter(prefix='/api/courses', tags=['course-qa'])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    week_id: int | None = Field(default=None, gt=0)
    resource_type: Literal['lecture', 'tutorial', 'other'] | None = None


def get_course_qa():
    return CourseQAService()


class IndexStatus(BaseModel):
    state: Literal['ready', 'indexing', 'stale', 'unavailable', 'error']
    message: str
    total_chunks: int
    indexed_chunks: int
    missing_chunks: int


@router.get('/{course_id}/index-status', response_model=IndexStatus)
def course_index_status(course_id: Annotated[int, Path(gt=0)], db: Annotated[Session, Depends(get_db)]):
    if db.get(Course, course_id) is None:
        raise HTTPException(404, 'Course not found')
    return index_status(db, course_id)


@router.post('/{course_id}/ask', response_model=RagAnswer)
def ask(course_id: Annotated[int, Path(gt=0)], body: AskRequest,
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[CourseQAService, Depends(get_course_qa)]):
    if db.get(Course, course_id) is None:
        raise HTTPException(404, 'Course not found')
    if body.week_id is not None:
        week = db.get(Week, body.week_id)
        if week is None or week.course_id != course_id:
            raise HTTPException(422, 'Week does not belong to this course')
    try:
        return service.ask(db, course_id, body.question,
                           week_id=body.week_id, resource_type=body.resource_type)
    except ValueError:
        raise HTTPException(422, 'Could not prepare this question with the selected scope.') from None
