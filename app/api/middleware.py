from fastapi import HTTPException

from app.api.errors import error_response
from app.api.uploads import reject_if_declared_too_large


class UploadSizeLimitMiddleware:
    """Refuses an upload whose declared size is clearly too big BEFORE the framework starts
    receiving and spooling the body. Plain ASGI on purpose: BaseHTTPMiddleware interferes
    with streaming responses."""

    def __init__(self, app, path: str, max_bytes: int):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == self.path:
            declared = dict(scope["headers"]).get(b"content-length")
            try:
                reject_if_declared_too_large(declared.decode() if declared else None, self.max_bytes)
            except HTTPException as exc:
                response = error_response(exc.status_code, "FILE_TOO_LARGE", exc.detail)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)