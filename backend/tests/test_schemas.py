import pytest
from pydantic import ValidationError

from app import models
from app.schemas import concept, course, document_chunk, question, resource, semester, summary, sync_record, week


@pytest.mark.parametrize("model,create,read,payload", [
    (models.Semester, semester.SemesterCreate, semester.SemesterRead, {"name": "2027 Semester 1", "year": 2027, "term": "S1"}),
    (models.Course, course.CourseCreate, course.CourseRead, {"semester_id": 1, "code": "TEST", "name": "Test"}),
    (models.Week, week.WeekCreate, week.WeekRead, {"course_id": 1, "week_number": 3, "title": "Test"}),
    (models.Resource, resource.ResourceCreate, resource.ResourceRead, {"week_id": 1, "filename": "test.pdf", "file_type": "pdf"}),
    (models.DocumentChunk, document_chunk.DocumentChunkCreate, document_chunk.DocumentChunkRead, {"resource_id": 1, "page_number": 1, "chunk_index": 0, "content": "Test"}),
    (models.Summary, summary.SummaryCreate, summary.SummaryRead, {"week_id": 1, "overview": "", "key_points": ["Test"]}),
    (models.Concept, concept.ConceptCreate, concept.ConceptRead, {"week_id": 1, "resource_id": 1, "name": "Test", "definition": "", "explanation": ""}),
    (models.Question, question.QuestionCreate, question.QuestionRead, {"week_id": 1, "resource_id": 1, "question": "Test?", "answer": ""}),
    (models.SyncRecord, sync_record.SyncRecordCreate, sync_record.SyncRecordRead, {}),
])
def test_all_create_and_read_schemas_roundtrip(db, graph, model, create, read, payload):
    entity = model(**create.model_validate(payload).model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    response = read.model_validate(entity)
    assert response.id > 0
    assert read.model_validate_json(response.model_dump_json()) == response


@pytest.mark.parametrize("schema,payload", [
    (week.WeekCreate, {"course_id": 1, "week_number": 0, "title": "Bad"}),
    (semester.SemesterCreate, {"name": "   ", "year": 2026, "term": "S2"}),
    (resource.ResourceCreate, {"week_id": 1, "filename": "x", "file_type": "pdf", "sync_status": "unknown"}),
    (document_chunk.DocumentChunkCreate, {"resource_id": 1, "page_number": 0, "chunk_index": 0, "content": "X"}),
    (summary.SummaryCreate, {"week_id": 1, "overview": "", "key_points": "not a list"}),
    (concept.ConceptCreate, {"week_id": 1, "resource_id": 1, "name": "X", "definition": "", "explanation": "", "importance": "critical"}),
    (question.QuestionCreate, {"week_id": 1, "resource_id": 1, "question": "X?", "answer": "", "source_page": -1}),
    (sync_record.SyncRecordCreate, {"files_failed": -1}),
    (sync_record.SyncRecordCreate, {"started_at": "2026-09-22T00:00:00Z", "completed_at": "2026-09-21T00:00:00Z"}),
])
def test_invalid_schema_inputs(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
