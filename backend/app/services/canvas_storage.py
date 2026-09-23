"""Stream raw materials via staging outside materials; never overwrite by name."""

from collections.abc import Iterable
import os
from pathlib import Path
import tempfile

from app.services.canvas_errors import CanvasDownloadError
from app.services.material_paths import contained_path


def _publish_new(part: Path, target: Path, root: Path) -> Path:
    for number in range(1, 10001):
        candidate = target if number == 1 else target.with_name(
            f"{target.stem} ({number}){target.suffix}"
        )
        contained_path(root, candidate)
        # Match Windows case-insensitive naming on all supported hosts.
        if any(p.name.casefold() == candidate.name.casefold() for p in target.parent.iterdir()):
            continue
        try:
            os.link(part, candidate)  # Exclusive publication, including concurrent writers.
            return candidate
        except FileExistsError:
            continue
    raise CanvasDownloadError("Too many conflicting material filenames.")


def save_stream(root: Path, target: Path, chunks: Iterable[bytes],
                expected_size: int, max_bytes: int, *, existing_path: Path | None = None) -> Path:
    part = None
    try:
        root = root.resolve()
        target = contained_path(root, target)
        if existing_path is not None:
            existing_path = contained_path(root, existing_path)
            if not existing_path.is_file():
                raise CanvasDownloadError("Existing material is missing; explicit recovery is required.")
        # A sibling staging directory keeps partial files out of materials and on the same volume.
        staging = root.parent / ".studyflow-staging"
        if staging.is_symlink():
            raise CanvasDownloadError("Staging directory must not be a symbolic link.")
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=staging, suffix=".partial", delete=False) as output:
            part = Path(output.name)
            total = 0
            for chunk in chunks:
                total += len(chunk)
                if total > max_bytes:
                    raise CanvasDownloadError("File exceeds the configured download size limit.")
                output.write(chunk)
        if total != expected_size:
            raise CanvasDownloadError("Downloaded size differs from Canvas metadata; fetch metadata and retry.")
        if existing_path is not None:
            # The caller must supply the path owned by this Canvas resource, never by filename.
            os.replace(part, contained_path(root, existing_path))
            return existing_path
        return _publish_new(part, target, root)
    except OSError:
        raise CanvasDownloadError("Unable to write file to StudyFlow materials storage.") from None
    finally:
        if part is not None:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
