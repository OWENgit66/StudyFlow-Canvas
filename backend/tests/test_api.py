import pytest

from app.models import Course


def test_health_and_empty_lists(client):
    assert client.get("/health").json() == {"status": "ok"}
    for url in ["/api/semesters", "/api/courses"]:
        response = client.get(url)
        assert response.status_code == 200
        assert response.json() == []


def test_catalog_reads_database(client, graph):
    semester, course, week, _ = graph
    semesters = client.get("/api/semesters").json()
    assert semesters[0]["id"] == semester.id
    assert semesters[0]["created_at"].endswith("Z")
    assert client.get("/api/courses").json()[0]["code"] == "COMPXXXX"
    assert client.get(f"/api/courses/{course.id}").json()["semester_id"] == semester.id
    assert client.get(f"/api/courses/{course.id}/weeks").json()[0]["id"] == week.id
    assert client.get(f"/api/weeks/{week.id}").json()["week_number"] == 2
    assert client.get("/api/courses?offset=1&limit=1").json() == []


def test_existing_course_without_weeks_returns_empty_list(client, db, graph):
    course = Course(semester_id=graph[0].id, code="EMPTY", name="Empty")
    db.add(course)
    db.commit()
    response = client.get(f"/api/courses/{course.id}/weeks")
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize("url", ["/api/courses/999", "/api/courses/999/weeks", "/api/weeks/999"])
def test_missing_records_return_404(client, url):
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("url", ["/api/courses/0", "/api/weeks/-1", "/api/courses/abc", "/api/courses?limit=0", "/api/semesters?offset=-1"])
def test_bad_parameters_return_422(client, url):
    assert client.get(url).status_code == 422


def test_openapi_documents_all_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/api/semesters", "/api/courses", "/api/courses/{course_id}", "/api/courses/{course_id}/weeks", "/api/weeks/{week_id}"} <= set(paths)
