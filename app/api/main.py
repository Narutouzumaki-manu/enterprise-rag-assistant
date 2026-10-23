
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.bootstrap import build_real_components
from app.api.errors import register_error_handlers
from app.api.routes import auth, chat, health, sessions
from app.api.runtime import AgentRuntime
from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.api.exchange import ChatStore


def make_runtime(agent, settings: Settings) -> AgentRuntime:
    return AgentRuntime(agent, settings.agent_max_concurrent, settings.agent_wait_seconds)


def create_app(
    agent=None,
    retriever=None,
    settings: Settings | None = None,
    session_factory=None,
    chat_store=None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        try:
            if app.state.db_session_factory is None:
                engine = create_engine(settings.database_url)  # connects lazily, on first use
                app.state.db_session_factory = create_session_factory(engine)
                if app.state.chat_store is None:
                    app.state.chat_store = ChatStore(app.state.db_session_factory)
            if app.state.runtime is None and settings.agent_enabled:
                real_retriever, real_agent = await run_in_threadpool(build_real_components, settings)
                app.state.retriever = real_retriever
                app.state.runtime = make_runtime(real_agent, settings)
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="Enterprise RAG Assistant API", lifespan=lifespan)
    app.state.settings = settings
    app.state.retriever = retriever
    app.state.runtime = make_runtime(agent, settings) if agent is not None else None
    app.state.db_session_factory = session_factory
    app.state.background_tasks = set()  # keeps background tasks (answer saving) alive
    if chat_store is None and session_factory is not None:
        chat_store = ChatStore(session_factory)
    app.state.chat_store = chat_store
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    return app


app = create_app()
