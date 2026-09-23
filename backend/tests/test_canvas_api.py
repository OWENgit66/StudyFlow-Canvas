import httpx2 as httpx
import pytest

from app.api.canvas import get_canvas_service, get_canvas_settings
from app.core.config import Settings
from app.services.canvas_service import CanvasService
from test_canvas_service import COURSE, FILE, MODULE, TOKEN, settings


def test_no_credentials_does_not_break_existing_app(client):
    client.app.dependency_overrides[get_canvas_settings] = lambda: Settings(
        _env_file=None, canvas_base_url="", canvas_access_token=""
    )
    response = client.get("/api/canvas/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["connected"] is False
    assert client.get("/api/canvas/courses").status_code == 503
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/courses").status_code == 200


def test_canvas_routes_use_service(client):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        payload = [COURSE]
        if request.url.path.endswith("/modules"):
            payload = [MODULE]
        elif request.url.path.endswith("/items"):
            payload = [{"id": 9, "module_id": 2, "type": "File", "title": "Lecture", "content_id": 3}]
        elif request.url.path.endswith("/files/3"):
            payload = FILE
        elif request.url.path.endswith("/files"):
            payload = [FILE]
        return httpx.Response(200, json=payload)
    with CanvasService(settings(), transport=httpx.MockTransport(handler)) as service:
        client.app.dependency_overrides[get_canvas_service] = lambda: service
        assert client.get("/api/canvas/courses").json()[0]["canvas_course_id"] == 1
        assert client.get("/api/canvas/courses/1/modules").json()[0]["name"] == "Week Three"
        assert client.get("/api/canvas/courses/1/modules/2/items").json()[0]["canvas_file_id"] == 3
        assert client.get("/api/canvas/files/3").json()["content_type"] == "application/pdf"
        assert client.get("/api/canvas/courses/1/files").json()[0]["canvas_file_id"] == 3
        assert client.get("/api/canvas/courses/0/modules").status_code == 422
    assert len(paths) == 5


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_safe_api_errors(client, status):
    with CanvasService(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(status, text=TOKEN, headers={"Retry-After": "30"}))) as service:
        client.app.dependency_overrides[get_canvas_service] = lambda: service
        response = client.get("/api/canvas/courses")
    assert response.status_code == (502 if status == 503 else status)
    assert TOKEN not in response.text
    assert response.json()["detail"]["code"].startswith("canvas_")
    if status == 429:
        assert response.headers["Retry-After"] == "30"


@pytest.mark.parametrize("status,expected", [(200, 200), (401, 401), (403, 403)])
def test_status_checks_actual_service_with_mock_transport(client, monkeypatch, status, expected):
    # Patch only the external transport, not the status business logic.
    from app.api import canvas
    factory = CanvasService
    monkeypatch.setattr(canvas, "CanvasService", lambda config: factory(
        config, transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"id": 1}))
    ))
    client.app.dependency_overrides[get_canvas_settings] = lambda: settings()
    response = client.get("/api/canvas/status")
    assert response.status_code == expected
    if status == 200:
        assert response.json() == {"configured": True, "connected": True, "message": None}
    assert TOKEN not in response.text


def test_canvas_openapi_is_read_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    canvas_paths = {path: methods for path, methods in paths.items() if path.startswith("/api/canvas/")}
    assert len(canvas_paths) == 6
    assert all(set(methods) == {"get"} for methods in canvas_paths.values())
