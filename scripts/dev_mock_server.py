
import uvicorn

from app.api.main import create_app
from tests.unit.api.mocks import MockAgent, MockRetriever

if __name__ == "__main__":
    app = create_app(
        agent=MockAgent(delay=8.0),
        retriever=MockRetriever(),
    )
    uvicorn.run(app, host="127.0.0.1", port=8000)
