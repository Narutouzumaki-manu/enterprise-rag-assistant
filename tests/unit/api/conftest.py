import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.api.limits import limiter
    print("RESET RAN")
    limiter.reset()   # clears the counters before every test, no try/except
    yield