from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.runtime import AgentBusyError
from app.core.config import get_settings
from app.schemas.api import ErrorResponse

HTTP_STATUS_CODES = {
    401: "UNAUTHENTICATED",
    404: "NOT_FOUND",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "DEPENDENCY_UNAVAILABLE",
    403: "FORBIDDEN",
    409: "CONFLICT",
}


def error_response(
    status_code: int, code: str, message: str, headers: dict | None = None
) -> JSONResponse:
    body = ErrorResponse(error=message, code=code)
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


def _describe_validation_error(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        field = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
        parts.append(f"{field}: {err['msg']}" if field else err["msg"])
    return "Invalid request. " + "; ".join(parts)  # never includes the submitted value


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentBusyError)
    async def busy_handler(request: Request, exc: AgentBusyError) -> JSONResponse:
        retry_after = str(get_settings().retry_after_seconds)
        return error_response(503, "AGENT_BUSY", str(exc), {"Retry-After": retry_after})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", _describe_validation_error(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        default = "INTERNAL_ERROR" if exc.status_code >= 500 else "BAD_REQUEST"
        code = HTTP_STATUS_CODES.get(exc.status_code, default)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, code, message, getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            500, "INTERNAL_ERROR", "Something went wrong on our side. Please try again."
        )