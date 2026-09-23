"""Human-readable paths. External names are always single sanitized components."""

from dataclasses import dataclass
from pathlib import Path
import re
import hashlib

from app.core.config import PROJECT_ROOT, Settings
from app.services.canvas_errors import CanvasDownloadError


@dataclass(frozen=True)
class MaterialContext:
    year: int
    term: str
    course_code: str | None
    course_name: str
    module_name: str


def sanitize_component(value: str, fallback: str = "Untitled") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")
    value = value or fallback
    # Windows device names are reserved even when followed by an extension.
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", value.split(".")[0]):
        value = "_" + value
    return value.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")


def material_root(settings: Settings) -> Path:
    root = settings.materials_root
    return (root if root.is_absolute() else PROJECT_ROOT / root).resolve()


def contained_path(root: Path, path: Path) -> Path:
    root, path = root.resolve(), path.resolve()
    if path == root or not path.is_relative_to(root):
        raise CanvasDownloadError("Material path is outside MATERIALS_ROOT.")
    return path


def build_material_path(root: Path, context: MaterialContext, filename: str) -> Path:
    if context.year <= 0 or not context.term.strip():
        raise CanvasDownloadError("A valid semester is required for material storage.")
    course = (f"{context.course_code} - {context.course_name}"
              if context.course_code else context.course_name)
    parts = [f"{context.year}-{context.term}", course, context.module_name, filename]
    parts = [sanitize_component(part) for part in parts]
    # Keep Explorer-compatible paths even on Windows hosts without long-path support.
    budget = 235 - len(str(root.resolve())) - len(parts)
    limits = [len(part) for part in parts]
    while sum(limits) > budget:
        index = max(range(len(limits)), key=limits.__getitem__)
        if limits[index] <= 20:
            raise CanvasDownloadError("MATERIALS_ROOT is too long; choose a shorter storage root.")
        limits[index] -= 1
    for index, (part, limit) in enumerate(zip(parts, limits)):
        if len(part) > limit:
            suffix = Path(part).suffix if index == 3 else ""
            if len(suffix) > 12:
                suffix = ""
            digest = hashlib.sha256(part.encode()).hexdigest()[:8]
            parts[index] = part[:limit - len(suffix) - 9].rstrip(" .") + "-" + digest + suffix
    target = root.resolve().joinpath(*parts)
    contained_path(root, target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise CanvasDownloadError("Unable to create material directories.") from None
    return contained_path(root, target)


def database_path(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(PROJECT_ROOT).as_posix() if path.is_relative_to(PROJECT_ROOT) else path.as_posix()


def resolve_database_path(value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
