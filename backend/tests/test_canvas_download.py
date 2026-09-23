import httpx2 as httpx
import pytest

from app.services.canvas_errors import CanvasError, CanvasConnectionError, CanvasDownloadError, CanvasPermissionError
from app.services.canvas_service import CanvasService
from app.services.material_paths import MaterialContext

CONTEXT = MaterialContext(2026, 'S2', 'COMP1000', 'Networks', 'Week 02')

from test_canvas_service import BASE, FILE, TOKEN, settings


class Chunks(httpx.SyncByteStream):
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False

    def __iter__(self):
        yield b"abc"
        if self.fail:
            raise httpx.ReadError("Interrupted")
        yield b"def"

    def close(self):
        self.closed = True


@pytest.mark.parametrize("filename", ["../../secret.txt", "..\\..\\secret.txt", "CON", "a:b?.pdf", ".", "报告.pdf"])
def test_streaming_safe_path_no_overwrite_and_redirect_auth(tmp_path, filename):
    streams = []
    def handler(request):
        assert request.method == "GET"
        if request.url.path == "/api/v1/files/3":
            return httpx.Response(200, json={**FILE, "filename": filename})
        if request.url.host == "canvas.example.test":
            assert request.headers["Authorization"] == f"Bearer {TOKEN}"
            return httpx.Response(302, headers={"Location": "https://cdn.example.test/signed?verifier=test"})
        assert "Authorization" not in request.headers
        stream = Chunks()
        streams.append(stream)
        return httpx.Response(200, stream=stream)
    sentinel = tmp_path / "secret.txt"
    sentinel.write_bytes(b"untouched")
    with CanvasService(settings(materials_root=tmp_path), transport=httpx.MockTransport(handler)) as service:
        first = service.download_file(3, context=CONTEXT)
        second = service.download_file(3, context=CONTEXT)
    assert first != second and first.read_bytes() == second.read_bytes() == b"abcdef"
    assert first.resolve().is_relative_to(tmp_path.resolve())
    assert not first.name.startswith("file-") and sentinel.read_bytes() == b"untouched"
    assert all(stream.closed for stream in streams)
    assert not list(tmp_path.rglob(".partial"))


@pytest.mark.parametrize("mode", ["interrupt", "size", "limit", "404", "locked", "missing_url", "loop", "http", "redirect_limit"])
def test_download_failures_leave_no_partial_file(tmp_path, mode):
    count = 0
    def handler(request):
        nonlocal count
        if request.url.path == "/api/v1/files/3":
            meta = dict(FILE)
            if mode == "size":
                meta["size"] = 7
            if mode == "locked":
                meta["locked_for_user"] = True
            if mode == "missing_url":
                meta["url"] = None
            if mode == "limit":
                meta["size"] = 1  # actual stream still exceeds the configured limit
            return httpx.Response(200, json=meta)
        count += 1
        if mode == "404":
            return httpx.Response(404)
        if mode in {"loop", "http", "redirect_limit"}:
            location = str(request.url) if mode == "loop" else "http://cdn.test/file"
            if mode == "redirect_limit":
                location = BASE + f"/download/{count}"
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200, stream=Chunks(fail=mode == "interrupt"))
    config = settings(materials_root=tmp_path, canvas_max_download_bytes=2 if mode == "limit" else 100)
    with CanvasService(config, transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(CanvasError):
            service.download_file(3, context=CONTEXT)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
    assert count <= 6


def test_oversize_metadata_stops_before_download(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=FILE)
    with CanvasService(settings(materials_root=tmp_path, canvas_max_download_bytes=2), transport=httpx.MockTransport(handler)) as service:
        with pytest.raises(CanvasDownloadError, match="size limit"):
            service.download_file(3, context=CONTEXT)
    assert len(calls) == 1
