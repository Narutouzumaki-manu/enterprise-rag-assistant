
import os

# Must run before app.api.limits is imported: the limiter reads this setting at import time.
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://rag:rag@localhost:5432/rag_test"
)


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (OSError, SQLAlchemyError) as exc:
        await engine.dispose()
        pytest.skip(f"Test database not available: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session


@pytest.fixture
def database_url() -> str:
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)

@pytest.fixture(autouse=True)
def _limiter_off():
    from app.api.limits import limiter
    print("FIXTURE RAN, id:", id(limiter), "enabled before:", limiter.enabled)
    limiter.enabled = False
    