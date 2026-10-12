from app.agents.config import AgentConfig
from app.agents.llm import OpenRouterLLM
from app.agents.planner import make_planner_node
from app.agents.state import initial_state

QUESTIONS = {
    "simple": "What was the closing headcount at the end of Q2 FY26?",
    "q19 (wording)": (
        "What was the company's profit after tax in the October-to-December "
        "quarter of the year before FY26?"
    ),
    "q16 (two facts)": (
        "How did the value of new deals from the biggest market change over the "
        "year, and roughly what portion of revenue does that market make up?"
    ),
}

llm = OpenRouterLLM.from_env(retries=1)
node = make_planner_node(llm, AgentConfig())

for name, question in QUESTIONS.items():
    update = node(initial_state(question))
    step = update["trace"][0]
    print(f"--- {name}")
    print("trace:", step.content)
    print("fallback:", step.metadata.get("fallback", False))
    for text in update["search_queries"]:
        print("  search:", text)