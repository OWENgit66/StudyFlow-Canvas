"""Read-only Canvas REST client. No database, parsing or AI dependencies."""

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
from urllib.parse import quote, urljoin, urlsplit

import httpx2 as httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.canvas import CanvasCourse, CanvasFile, CanvasModule, CanvasModuleItem, CanvasPage
from app.services.canvas_errors import (
    CanvasError, CanvasAuthenticationError, CanvasConfigurationError,
    CanvasConnectionError, CanvasDownloadError, CanvasNotFoundError,
    CanvasPermissionError, CanvasRateLimitError,
)
from app.services.canvas_storage import save_stream
from app.services.material_paths import MaterialContext, build_material_path, material_root
from pathlib import Path

logger = logging.getLogger(__name__)


def positive_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Canvas IDs must be positive integers.")
    return value


def https_url(value: str):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.fragment)
        port = parsed.port  # Validate malformed ports before sending any request.
    except ValueError:
        raise CanvasError("Canvas returned an invalid URL.") from None
    if not valid or any(char.isspace() for char in value) or "\\" in value:
        raise CanvasError("Canvas URLs must use HTTPS without embedded credentials.")
    return parsed, (parsed.scheme, parsed.hostname.lower(), port or 443)


class CanvasService:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        token = settings.canvas_access_token.get_secret_value().strip()
        base = settings.canvas_base_url.strip().rstrip("/")
        if not base or not token:
            raise CanvasConfigurationError("Canvas credentials are not configured.")
        try:
            parsed, self._origin = https_url(base)
        except CanvasError:
            raise CanvasConfigurationError("CANVAS_BASE_URL must be a valid HTTPS instance URL.") from None
        if parsed.path or parsed.query or "\r" in token or "\n" in token:
            raise CanvasConfigurationError("Use the Canvas instance origin without an API path or query.")
        self._base = base + "/api/v1/"
        self._token = token
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.canvas_timeout_seconds, follow_redirects=False,
            transport=transport, headers={"Accept": "application/json"},
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._client.close()

    def _headers(self, url: str) -> dict[str, str]:
        _, origin = https_url(url)
        # Signed CDN downloads must never receive the Canvas bearer token.
        return {"Authorization": f"Bearer {self._token}"} if origin == self._origin else {}

    def _check_api_url(self, url: str) -> None:
        parsed, origin = https_url(url)
        if origin != self._origin or not parsed.path.startswith("/api/v1/"):
            raise CanvasError("Canvas pagination left the configured API origin.")

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        logger.warning("Canvas request failed: %s", status)
        errors = {
            401: (CanvasAuthenticationError, "Canvas token is invalid or expired."),
            403: (CanvasPermissionError, "Canvas access is forbidden for this resource."),
            404: (CanvasNotFoundError, "Canvas resource was not found."),
        }
        if status in errors:
            kind, message = errors[status]
            raise kind(message)
        if status == 429:
            retry_after = None
            value = response.headers.get("Retry-After", "")
            try:
                seconds = int(value) if value.isdigit() else int(
                    (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                )
                retry_after = max(1, min(seconds, 3600))
            except (TypeError, ValueError, OverflowError):
                pass
            raise CanvasRateLimitError(retry_after)
        raise CanvasError("Canvas server error." if status >= 500 else "Unexpected Canvas response status.")

    @contextmanager
    def _stream(self, url: str):
        try:
            with self._client.stream("GET", url, headers=self._headers(url)) as response:
                yield response
        except (httpx.HTTPError, httpx.InvalidURL):
            logger.warning("Canvas connection failed.")
            raise CanvasConnectionError("Unable to connect to Canvas or download host; request failed or timed out.") from None

    def _json(self, url: str):
        self._check_api_url(url)
        with self._stream(url) as response:
            self._check_status(response)
            try:
                response.read()
                return response.json(), response.links
            except (ValueError, UnicodeError):
                raise CanvasError("Canvas returned invalid JSON.") from None

    @staticmethod
    def _parse(schema, payload):
        try:
            return schema.model_validate(payload)
        except ValidationError:
            raise CanvasError("Canvas returned unexpected metadata fields.") from None

    def _get_paginated(self, path: str, schema, *, include_term=False):
        url = self._base + path + "?per_page=100" + ("&include[]=term" if include_term else "")
        seen = set()
        results = []
        for _ in range(self._settings.canvas_max_pages):
            if url in seen:
                raise CanvasError("Canvas pagination repeated a page URL.")
            seen.add(url)
            payload, links = self._json(url)
            if not isinstance(payload, list):
                raise CanvasError("Canvas list endpoint did not return a list.")
            results.extend(self._parse(schema, item) for item in payload)
            next_url = links.get("next", {}).get("url")
            if not next_url:
                return results
            url = urljoin(url, next_url)
        raise CanvasError("Canvas pagination exceeded the configured page limit.")

    def check_connection(self) -> None:
        # Minimal identity check; do not return or log personal profile data.
        payload, _ = self._json(self._base + "users/self/profile")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise CanvasError("Canvas returned an unexpected profile response.")

    def get_courses(self) -> list[CanvasCourse]:
        logger.info("Fetching Canvas courses")
        courses = self._get_paginated("courses", CanvasCourse, include_term=True)
        logger.info("Found %d Canvas courses", len(courses))
        return courses

    def get_modules(self, course_id: int) -> list[CanvasModule]:
        course_id = positive_id(course_id)
        logger.info("Fetching modules for course %d", course_id)
        return self._get_paginated(f"courses/{course_id}/modules", CanvasModule)

    def get_module_items(self, course_id: int, module_id: int) -> list[CanvasModuleItem]:
        path = f"courses/{positive_id(course_id)}/modules/{positive_id(module_id)}/items"
        return self._get_paginated(path, CanvasModuleItem)

    def get_files(self, course_id: int) -> list[CanvasFile]:
        return self._get_paginated(f"courses/{positive_id(course_id)}/files", CanvasFile)

    def get_page(self, course_id: int, page_url_or_id: str | int) -> CanvasPage:
        if isinstance(page_url_or_id, int):
            locator = f'page_id:{positive_id(page_url_or_id)}'
        elif (isinstance(page_url_or_id, str) and page_url_or_id.strip()
              and len(page_url_or_id) <= 1000
              and not any(c in page_url_or_id for c in '/\\?#%')
              and page_url_or_id not in {'.', '..'}):
            locator = page_url_or_id
        else:
            raise CanvasError('Invalid Canvas page identifier.')
        payload, _ = self._json(self._base + f'courses/{positive_id(course_id)}/pages/' + quote(locator, safe=':'))
        page = self._parse(CanvasPage, payload)
        if page.locked_for_user:
            raise CanvasPermissionError('Canvas page is locked for the current user.')
        if page.body is None:
            raise CanvasError('Canvas page has no accessible HTML body.')
        return page

    def get_external_file(self, url):
        from app.services.external_pdf import ExternalPDFClient
        return ExternalPDFClient(self._settings).metadata(url)

    def download_external_file(self, metadata, *, context, existing_path=None):
        from app.services.external_pdf import ExternalPDFClient
        return ExternalPDFClient(self._settings).download(metadata, context, existing_path=existing_path)

    def get_file(self, file_id: int) -> CanvasFile:
        payload, _ = self._json(self._base + f"files/{positive_id(file_id)}")
        result = self._parse(CanvasFile, payload)
        if result.canvas_file_id != file_id:
            raise CanvasError("Canvas file metadata ID does not match the requested file.")
        return result

    def download_file(self, file_id: int, *, context: MaterialContext,
                      existing_path: Path | None = None) -> Path:
        file = self.get_file(file_id)
        if file.locked_for_user:
            raise CanvasPermissionError("Canvas file is locked for the current user.")
        if not file.download_url:
            raise CanvasDownloadError("Canvas did not supply a download URL.")
        if file.size > self._settings.canvas_max_download_bytes:
            raise CanvasDownloadError("File exceeds the configured download size limit.")
        root = material_root(self._settings)
        target = build_material_path(root, context, file.filename)
        logger.info("Downloading Canvas file %d", file_id)
        url, seen = file.download_url, set()
        for _ in range(6):
            if url in seen:
                raise CanvasDownloadError("Canvas download redirect loop detected.")
            seen.add(url)
            with self._stream(url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise CanvasDownloadError("Download redirect has no destination.")
                    url = urljoin(url, location)
                    continue
                self._check_status(response)
                if response.status_code != 200:
                    raise CanvasDownloadError("Canvas did not return a complete file response.")
                result = save_stream(
                    root, target, response.iter_bytes(chunk_size=65536),
                    file.size, self._settings.canvas_max_download_bytes,
                    existing_path=existing_path,
                )
                logger.info("Downloaded Canvas file %d", file_id)
                return result
        raise CanvasDownloadError("Canvas download exceeded the redirect limit.")
