import logging

import httpx2 as httpx
import pytest

from app.core.config import Settings
from app.schemas.canvas import CanvasCourse
from app.services.canvas_errors import (
    CanvasError, CanvasAuthenticationError, CanvasConfigurationError,
    CanvasConnectionError, CanvasNotFoundError, CanvasPermissionError, CanvasRateLimitError,
)
from app.services.canvas_mapping import canvas_course_to_course
from app.services.canvas_service import CanvasService

BASE = "https://canvas.example.test"
TOKEN = "test-token-not-a-real-secret"
COURSE = {"id": 1, "name": "Networks", "course_code": "COMP1000", "workflow_state": "available", "start_at": "2026-01-01T00:00:00Z", "end_at": None}
MODULE = {"id": 2, "name": "Week Three", "position": 1, "workflow_state": "active"}
FILE = {"id": 3, "filename": "lecture.pdf", "display_name": "Lecture", "content-type": "application/pdf", "size": 6, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-02-01T00:00:00Z", "url": BASE + "/files/3/download"}


def settings(**overrides):
    return Settings(_env_file=None, canvas_base_url=BASE, canvas_access_token=TOKEN, **overrides)


def test_courses_auth_and_mapping(caplog):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/courses"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.url.params["per_page"] == "100"
        assert request.extensions["timeout"]["read"] == 20
        return httpx.Response(200, json=[{**COURSE, "extra_upstream": "discard"}, {"id": 4}])

    with caplog.at_level(logging.INFO), CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        courses = service.get_courses()
    assert len(courses) == 2 and courses[0].canvas_course_id == 1
    assert "extra_upstream" not in courses[0].model_dump()
    assert courses[1].name is None
    mapped = canvas_course_to_course(courses[0], semester_id=2)
    assert mapped.semester_id == 2 and mapped.code == "COMP1000"
    with pytest.raises(ValueError):
        canvas_course_to_course(courses[1], semester_id=2)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("method,args,payload", [
    ("get_modules", (1,), [MODULE]),
    ("get_files", (1,), [FILE]),
    ("get_file", (3,), FILE),
])
def test_metadata(method, args, payload):
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as service:
        result = getattr(service, method)(*args)
    item = result[0] if isinstance(result, list) else result
    if method == "get_modules":
        assert item.name == "Week Three" and item.module_id == 2
    else:
        assert item.canvas_file_id == 3 and item.content_type == "application/pdf"
        assert item.updated_at.year == 2026 and item.download_url.endswith("/download")


def test_all_item_types_and_missing_file_content_id():
    types = ["File", "Page", "Assignment", "Discussion", "ExternalUrl", "ExternalTool", "Quiz", "SubHeader", "FutureType"]
    payload = [{"id": i + 1, "module_id": 2, "title": kind, "type": kind, "content_id": 3} for i, kind in enumerate(types)]
    payload.append({"id": 10, "module_id": 2, "title": "Restricted", "type": "File"})
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as service:
        items = service.get_module_items(1, 2)
    assert items[0].canvas_file_id == 3
    assert all(item.canvas_file_id is None for item in items[1:])
    assert [item.type for item in items[:9]] == types


@pytest.mark.parametrize("method,args,payload", [
    ("get_courses", (), COURSE), ("get_modules", (1,), MODULE),
    ("get_module_items", (1, 2), {"id": 1, "module_id": 2, "title": "Page", "type": "Page"}),
    ("get_files", (1,), FILE),
])
def test_shared_pagination(method, args, payload):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=[payload], headers={"Link": f'<{BASE}{request.url.path}?opaque=next>; rel="next"'})
        assert request.url.params["opaque"] == "next"
        assert "per_page" not in request.url.params
        return httpx.Response(200, json=[payload])
    with CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        assert len(getattr(service, method)(*args)) == 2
    assert len(calls) == 2


@pytest.mark.parametrize("next_url", [BASE + "/api/v1/courses?per_page=100&include[]=term", "https://other.test/api/v1/courses", BASE + "/login"])
def test_pagination_loop_and_origin_protection(next_url):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{next_url}>; rel="next"'})
    with CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(CanvasError):
            service.get_courses()
    assert len(calls) == 1


def test_page_limit():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{BASE}/api/v1/courses?page={len(calls)}>; rel="next"'})
    with CanvasService(settings(canvas_max_pages=2), transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(CanvasError, match="page limit"):
            service.get_courses()
    assert len(calls) == 2


@pytest.mark.parametrize("status,error", [(401, CanvasAuthenticationError), (403, CanvasPermissionError), (404, CanvasNotFoundError), (429, CanvasRateLimitError), (500, CanvasError), (503, CanvasError), (302, CanvasError)])
def test_status_errors_do_not_retry_or_leak(status, error, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=TOKEN, headers={"Retry-After": "60"})
    with CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(error) as caught:
            service.get_courses()
    if status == 429:
        assert caught.value.retry_after == 60
    assert len(calls) == 1 and TOKEN not in str(caught.value) and TOKEN not in caplog.text


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError])
def test_network_errors(error):
    def handler(request):
        raise error(TOKEN, request=request)
    with CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(CanvasConnectionError) as caught:
            service.get_courses()
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>login</html>"), httpx.Response(200, json={}), httpx.Response(200, json=[{"id": "bad"}])])
def test_invalid_payload(response):
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: response)) as service:
        with pytest.raises(CanvasError):
            service.get_courses()


@pytest.mark.parametrize("base,token", [("", ""), (BASE, ""), ("http://canvas.test", TOKEN), (BASE + "/api/v1", TOKEN), ("https://user:password@canvas.test", TOKEN)])
def test_configuration_is_validated_when_service_is_used(base, token):
    with pytest.raises(CanvasConfigurationError):
        CanvasService(Settings(_env_file=None, canvas_base_url=base, canvas_access_token=token))


def test_secret_settings_repr():
    assert TOKEN not in repr(settings())


def test_identity_check_and_file_id_mismatch():
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": 9}))) as service:
        service.check_connection()
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={**FILE, "id": 4}))) as service:
        with pytest.raises(CanvasError, match="ID"):
            service.get_file(3)
