"""Development read-only endpoints; all Canvas IO stays in CanvasService."""

from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.schemas.canvas import CanvasCourse, CanvasFile, CanvasModule, CanvasModuleItem, CanvasStatus
from app.services.canvas_errors import CanvasError, CanvasRateLimitError
from app.services.canvas_service import CanvasService

router = APIRouter(prefix="/api/canvas", tags=["canvas (read only)"])


def get_canvas_settings() -> Settings:
    return Settings()


def get_canvas_service(
    settings: Annotated[Settings, Depends(get_canvas_settings)],
) -> Generator[CanvasService, None, None]:
    with CanvasService(settings) as service:
        yield service


Service = Annotated[CanvasService, Depends(get_canvas_service)]
ID = Annotated[int, Path(gt=0)]


async def canvas_error_handler(_request: Request, error: CanvasError) -> JSONResponse:
    headers = {}
    if isinstance(error, CanvasRateLimitError) and error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return JSONResponse(
        status_code=error.http_status,
        content={"detail": {"code": error.code, "message": str(error)}},
        headers=headers,
    )


@router.get("/status", response_model=CanvasStatus)
def status(settings: Annotated[Settings, Depends(get_canvas_settings)]):
    if not settings.canvas_base_url.strip() or not settings.canvas_access_token.get_secret_value().strip():
        return CanvasStatus(configured=False, connected=False, message="Canvas credentials are not configured.")
    with CanvasService(settings) as service:
        service.check_connection()
    return CanvasStatus(configured=True, connected=True)


@router.get("/courses", response_model=list[CanvasCourse])
def courses(service: Service):
    return service.get_courses()


@router.get("/courses/{course_id}/modules", response_model=list[CanvasModule])
def modules(course_id: ID, service: Service):
    return service.get_modules(course_id)


@router.get("/courses/{course_id}/modules/{module_id}/items", response_model=list[CanvasModuleItem])
def items(course_id: ID, module_id: ID, service: Service):
    return service.get_module_items(course_id, module_id)


@router.get("/courses/{course_id}/files", response_model=list[CanvasFile])
def files(course_id: ID, service: Service):
    return service.get_files(course_id)


@router.get("/files/{file_id}", response_model=CanvasFile)
def file_metadata(file_id: ID, service: Service):
    return service.get_file(file_id)
