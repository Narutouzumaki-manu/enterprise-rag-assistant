from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.metrics import AGENT_SLOTS_IN_USE

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    runtime = request.app.state.runtime
    AGENT_SLOTS_IN_USE.set(runtime.in_use if runtime is not None else 0)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)