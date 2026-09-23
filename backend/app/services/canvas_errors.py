"""Safe errors: never include upstream response bodies, tokens or signed URLs."""


class CanvasError(Exception):
    code = "canvas_error"
    http_status = 502


class CanvasConfigurationError(CanvasError):
    code = "canvas_not_configured"
    http_status = 503


class CanvasAuthenticationError(CanvasError):
    code = "canvas_authentication_error"
    http_status = 401


class CanvasPermissionError(CanvasError):
    code = "canvas_permission_error"
    http_status = 403


class CanvasNotFoundError(CanvasError):
    code = "canvas_not_found"
    http_status = 404


class CanvasRateLimitError(CanvasError):
    code = "canvas_rate_limited"
    http_status = 429

    def __init__(self, retry_after: int | None = None):
        super().__init__("Canvas rate limit reached. Try again later.")
        self.retry_after = retry_after


class CanvasConnectionError(CanvasError):
    code = "canvas_connection_error"
    http_status = 504


class CanvasDownloadError(CanvasError):
    code = "canvas_download_error"
