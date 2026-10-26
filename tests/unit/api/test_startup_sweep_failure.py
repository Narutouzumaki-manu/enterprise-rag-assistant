import pytest

from app.api.startup import sweep_interrupted_documents


class BrokenFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        raise ConnectionError("unexpected connection_lost() call")

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_sweep_never_raises_when_the_database_is_down():
    assert await sweep_interrupted_documents(BrokenFactory(), None) == 0