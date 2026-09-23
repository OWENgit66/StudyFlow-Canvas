from pathlib import Path

import httpx2 as httpx
import pytest

from app.core.config import PROJECT_ROOT, Settings
from app.models import Resource
from app.services.canvas_errors import CanvasDownloadError
from app.services.canvas_service import CanvasService
from app.services.canvas_storage import save_stream
from app.services.material_paths import (
    MaterialContext, build_material_path, database_path, material_root,
    resolve_database_path, sanitize_component,
)
from app.services.material_service import download_resource
from test_canvas_service import FILE, settings

CONTEXT = MaterialContext(2026, "S2", "INFO6007", "Project Management", "Week 02")


def test_path_generation_and_blank_setting(tmp_path):
    root = tmp_path / "materials"
    target = build_material_path(root, CONTEXT, "Lecture.pdf")
    assert target == root / "2026-S2/INFO6007 - Project Management/Week 02/Lecture.pdf"
    assert target.parent.is_dir()
    assert material_root(Settings(_env_file=None, materials_root="")) == PROJECT_ROOT / "materials"


def test_other_semester_no_code_and_non_week(tmp_path):
    context = MaterialContext(2027, "S1", None, "Networks", "Revision")
    path = build_material_path(tmp_path, context, "Tutorial.pdf")
    assert path.relative_to(tmp_path).as_posix() == "2027-S1/Networks/Revision/Tutorial.pdf"


@pytest.mark.parametrize("value", ['a<>:"/\\|?*b', "../../secret.pdf", "..\\..\\secret.pdf", "CON", "NUL.pdf", "..", "课程" * 200])
def test_sanitize_and_traversal(tmp_path, value):
    context = MaterialContext(2026, value, value, value, value)
    path = build_material_path(tmp_path, context, value)
    assert path.resolve().is_relative_to(tmp_path.resolve())
    name = sanitize_component(value)
    assert not any(c in name for c in '<>:"/\\|?*')
    assert len(name.encode("utf-8")) <= 180
    assert not name.endswith((".", " "))


def test_duplicate_name_and_case_do_not_overwrite(tmp_path):
    root = tmp_path / "materials"
    target = build_material_path(root, CONTEXT, "Lecture.pdf")
    first = save_stream(root, target, [b"one"], 3, 100)
    second = save_stream(root, target, [b"two"], 3, 100)
    third = save_stream(root, target.with_name("lecture.pdf"), [b"new"], 3, 100)
    assert first.name == "Lecture.pdf"
    assert second.name == "Lecture (2).pdf"
    assert third != first
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
    assert not list(root.rglob("*.partial"))


def test_explicit_owned_update_and_failed_update_preserve_path(tmp_path):
    root = tmp_path / "materials"
    target = build_material_path(root, CONTEXT, "Lecture.pdf")
    path = save_stream(root, target, [b"old"], 3, 100)
    with pytest.raises(CanvasDownloadError):
        save_stream(root, target, [b"bad"], 9, 100, existing_path=path)
    assert path.read_bytes() == b"old"
    assert save_stream(root, target, [b"updated"], 7, 100, existing_path=path) == path
    assert path.read_bytes() == b"updated"
    assert not list((root.parent / ".studyflow-staging").iterdir())


def test_reject_replace_outside_root(tmp_path):
    root = tmp_path / "materials"
    outside = tmp_path / "keep.pdf"
    outside.write_bytes(b"keep")
    with pytest.raises(CanvasDownloadError):
        save_stream(root, build_material_path(root, CONTEXT, "a.pdf"), [b"bad"], 3, 100, existing_path=outside)
    assert outside.read_bytes() == b"keep"


def test_project_relative_database_paths():
    path = PROJECT_ROOT / "materials/2026-S2/course/week/lecture.pdf"
    assert database_path(path) == "materials/2026-S2/course/week/lecture.pdf"
    assert resolve_database_path(database_path(path)) == path


def test_resource_identity_database_path_and_collision(db, graph, tmp_path):
    resource = graph[3]
    def handler(request):
        if "/api/v1/files/" in request.url.path:
            return httpx.Response(200, json={**FILE, "id": int(request.url.path.rsplit("/", 1)[1])})
        return httpx.Response(200, content=b"abcdef")
    other = Resource(week=graph[2], canvas_file_id=2002, filename="lecture.pdf", file_type="pdf")
    db.add(other)
    with CanvasService(settings(materials_root=tmp_path), transport=httpx.MockTransport(handler)) as canvas:
        first = download_resource(db, canvas, resource)
        second = download_resource(db, canvas, other)
        assert first.name == "lecture.pdf" and second.name == "lecture (2).pdf"
        assert download_resource(db, canvas, resource) == first
        db.commit()
        db.refresh(resource)
        assert resolve_database_path(resource.local_path) == first
        assert resource.sync_status == "downloaded"
        other.local_path = resource.local_path
        with pytest.raises(CanvasDownloadError, match="shared"):
            download_resource(db, canvas, other)


def test_symlink_escape(tmp_path):
    root = tmp_path / "materials"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "2026-S2").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlinks")
    with pytest.raises(CanvasDownloadError):
        build_material_path(root, CONTEXT, "lecture.pdf")
    assert not list(outside.iterdir())
