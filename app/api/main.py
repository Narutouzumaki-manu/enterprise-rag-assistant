from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.bootstrap import build_real_components
from app.api.errors import register_error_handlers
from app.api.routes import chat, health
from app.api.runtime import AgentRuntime
from app.core.config import Settings, get_settings


def make_runtime(agent, settings: Settings) -> AgentRuntime:
    return AgentRuntime(agent, settings.agent_max_concurrent, settings.agent_wait_seconds)


def create_app(agent=None, retriever=None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.runtime is None and settings.agent_enabled:
            real_retriever, real_agent = await run_in_threadpool(build_real_components, settings)
            app.state.retriever = real_retriever
            app.state.runtime = make_runtime(real_agent, settings)
        yield

    app = FastAPI(title="Enterprise RAG Assistant API", lifespan=lifespan)
    app.state.retriever = retriever
    app.state.settings = settings
    app.state.runtime = make_runtime(agent, settings) if agent is not None else None
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()