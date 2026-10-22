from fastapi import HTTPException, Request

from app.api.runtime import AgentRuntime
from app.core.config import Settings


def get_runtime(request: Request) -> AgentRuntime:
    runtime = request.app.state.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="The assistant is not available right now.")
    return runtime


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings