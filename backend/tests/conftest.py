import pytest
from fastapi.testclient import TestClient

from app.core.database import build_engine, create_session_factory, init_db
from app.main import create_app
from app.models import Course, Resource, Semester, Week


@pytest.fixture
def engine():
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def graph(db):
    semester = Semester(name="2026 Semester 2", year=2026, term="S2", is_active=True, canvas_term_id=101)
    course = Course(semester=semester, canvas_course_id=1001, code="COMPXXXX", name="Computer Networks")
    week = Week(course=course, week_number=2, title="Link Layer")
    resource = Resource(week=week, canvas_file_id=2001, filename="week2-lecture.pdf", file_type="pdf")
    db.add(resource)
    db.commit()
    return semester, course, week, resource


@pytest.fixture
def client(engine):
    # App lifespan initializes only this fixture's isolated engine.
    with TestClient(create_app(engine)) as client:
        yield client
