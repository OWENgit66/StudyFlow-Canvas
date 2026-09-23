from datetime import timedelta

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.database import Base, build_engine, create_session_factory, init_db
from app.models import Concept, Course, DocumentChunk, Question, Resource, Semester, Summary, SyncRecord, Week
from app.models.common import utc_now
from app.seed import seed_demo


def test_connection_tables_and_foreign_keys(engine, db):
    assert db.scalar(text("SELECT 1")) == 1
    assert db.scalar(text("PRAGMA foreign_keys")) == 1
    assert set(inspect(engine).get_table_names()) == {
        "semesters", "courses", "weeks", "resources", "document_chunks",
        "summaries", "concepts", "questions", "sync_records", "resource_knowledge",
    }


def test_file_creation_and_persistence(tmp_path):
    path = tmp_path / "nested" / "test.db"
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    init_db(engine)  # initialization is repeatable
    with create_session_factory(engine).begin() as db:
        db.add(Semester(name="Test", year=2026, term="S2"))
    engine.dispose()
    assert path.is_file()
    reopened = build_engine(f"sqlite:///{path.as_posix()}")
    try:
        with create_session_factory(reopened)() as db:
            assert db.scalar(select(Semester.name)) == "Test"
    finally:
        reopened.dispose()


def test_create_hierarchy_and_bidirectional_relationships(db, graph):
    ids = [item.id for item in graph]
    db.expunge_all()
    semester = db.get(Semester, ids[0])
    course = semester.courses[0]
    week = course.weeks[0]
    resource = week.resources[0]
    assert [semester.id, course.id, week.id, resource.id] == ids
    assert course.semester is semester
    assert week.course is course
    assert resource.week is week
    assert resource.sync_status == "pending"
    assert resource.local_path is None
    for entity in [semester, course, week, resource]:
        assert entity.created_at.utcoffset() == timedelta(0)


def test_create_knowledge_and_relationships(db, graph):
    _, _, week, resource = graph
    chunk = DocumentChunk(resource=resource, page_number=2, chunk_index=0, content="Frames carry data.")
    summary = Summary(week=week, overview="Link layer", key_points=["Frames"], exam_focus=[])
    concept = Concept(week=week, resource=resource, name="Frame", definition="A unit of data", explanation="Test fixture", importance="high", source_page=2)
    question = Question(week=week, resource=resource, question="What carries data?", answer="Frames", source_page=2)
    db.add_all([chunk, summary, concept, question])
    db.commit()
    resource_id, week_id = resource.id, week.id
    db.expunge_all()
    resource = db.get(Resource, resource_id)
    week = db.get(Week, week_id)
    assert resource.chunks[0].page_number == 2
    assert resource.chunks[0].resource is resource
    assert week.summary.key_points == ["Frames"]
    assert week.summary.week is week
    assert resource.concepts[0] is week.concepts[0]
    assert resource.questions[0] is week.questions[0]
    assert week.concepts[0].resource is resource
    assert week.questions[0].week is week
    week.summary.key_points.append("Error detection")
    db.commit()
    db.expire_all()
    assert week.summary.key_points == ["Frames", "Error detection"]


def test_sync_record_and_updated_at(db, graph):
    record = SyncRecord()
    db.add(record)
    db.commit()
    db.refresh(record)
    assert record.status == "running"
    assert record.files_failed == 0
    assert record.completed_at is None
    record.status = "completed_with_errors"
    record.files_failed = 1
    record.completed_at = utc_now()
    record.error_message = "Development test only"
    db.commit()
    db.refresh(record)
    assert record.completed_at >= record.started_at
    course = graph[1]
    before = course.updated_at
    course.name = "Updated title"
    db.commit()
    db.refresh(course)
    assert course.updated_at > before


@pytest.mark.parametrize("kind", ["semester", "course", "week", "resource", "chunk", "summary"])
def test_duplicate_constraints(db, graph, kind):
    semester, course, week, resource = graph
    if kind == "semester":
        duplicate = Semester(name="Duplicate", year=2026, term="S2")
    elif kind == "course":
        duplicate = Course(semester_id=semester.id, canvas_course_id=course.canvas_course_id, code="DUP", name="Duplicate")
    elif kind == "week":
        duplicate = Week(course_id=course.id, week_number=2, title="Duplicate")
    elif kind == "resource":
        duplicate = Resource(week_id=week.id, canvas_file_id=resource.canvas_file_id, filename="duplicate.pdf", file_type="pdf")
    elif kind == "chunk":
        db.add(DocumentChunk(resource_id=resource.id, page_number=1, chunk_index=0, content="First"))
        db.commit()
        duplicate = DocumentChunk(resource_id=resource.id, page_number=2, chunk_index=0, content="Duplicate")
    else:
        db.add(Summary(week_id=week.id, overview="First"))
        db.commit()
        duplicate = Summary(week_id=week.id, overview="Duplicate")
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.scalar(text("SELECT 1")) == 1


def test_same_file_can_be_referenced_in_another_week(db, graph):
    _, course, _, resource = graph
    other = Week(course=course, week_number=3, title="Revision")
    db.add(Resource(week=other, canvas_file_id=resource.canvas_file_id, filename=resource.filename, file_type="pdf"))
    db.commit()
    assert db.scalar(select(func.count()).select_from(Resource)) == 2


@pytest.mark.parametrize("model,values", [
    (Course, {"semester_id": 999, "code": "X", "name": "Missing parent"}),
    (Week, {"course_id": 999, "week_number": 1, "title": "Missing parent"}),
    (Resource, {"week_id": 999, "filename": "x.pdf", "file_type": "pdf"}),
    (DocumentChunk, {"resource_id": 999, "page_number": 1, "chunk_index": 0, "content": "X"}),
    (Summary, {"week_id": 999, "overview": "X"}),
])
def test_orphans_are_rejected(db, model, values):
    db.add(model(**values))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("model,values", [
    (Concept, {"name": "X", "definition": "", "explanation": ""}),
    (Question, {"question": "X?", "answer": ""}),
])
def test_knowledge_cannot_point_to_another_weeks_resource(db, graph, model, values):
    _, course, _, resource = graph
    other = Week(course_id=course.id, week_number=3, title="Other")
    db.add(other)
    db.commit()
    db.add(model(week_id=other.id, resource_id=resource.id, **values))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("sql", [
    "UPDATE weeks SET week_number = 0",
    "UPDATE resources SET sync_status = 'unknown'",
    "UPDATE courses SET canvas_course_id = -1",
    "INSERT INTO sync_records (started_at, status, courses_processed, files_discovered, files_downloaded, files_updated, files_skipped, files_failed) VALUES ('2026-01-01', 'unknown', 0,0,0,0,0,0)",
    "INSERT INTO sync_records (started_at, status, courses_processed, files_discovered, files_downloaded, files_updated, files_skipped, files_failed) VALUES ('2026-01-01', 'running', 0,0,0,0,0,-1)",
])
def test_database_checks_also_protect_raw_sql(db, graph, sql):
    with pytest.raises(IntegrityError):
        db.execute(text(sql))
    db.rollback()


def test_naive_timestamp_rejected(db, graph):
    graph[3].canvas_updated_at = utc_now().replace(tzinfo=None)
    with pytest.raises(StatementError):
        db.commit()
    db.rollback()


def test_seed_is_explicit_repeatable_and_has_no_real_file(db):
    for _ in range(2):
        seed_demo(db)
        db.commit()
    for model, expected in [(Semester, 1), (Course, 1), (Week, 2), (Resource, 1)]:
        assert db.scalar(select(func.count()).select_from(model)) == expected
    resource = db.scalar(select(Resource))
    assert resource.canvas_file_id is None and resource.local_path is None


def test_uncommitted_session_is_rolled_back(engine):
    factory = create_session_factory(engine)
    with factory() as db:
        db.add(Semester(name="Discard", year=2026, term="S1"))
        db.flush()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Semester)) == 0
