from pydantic import BaseModel

from app.agents.llm import OpenRouterLLM


class Capital(BaseModel):
    country: str
    capital: str


llm = OpenRouterLLM.from_env(retries=1)
print("models:", llm.models)

answer = llm.complete(
    "You answer in one short sentence.", "What is the capital of France?"
)
print("check 1 - plain answer:", answer)

result = llm.complete_structured(
    "You answer factual questions.", "What is the capital of Japan?", Capital
)
print("check 2 - structured:", result)