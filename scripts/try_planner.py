from app.agents.config import AgentConfig
from app.agents.llm import LLMError
from app.agents.planner import Plan, make_planner_node
from app.agents.state import initial_state
from tests.unit.agents.mocks import MockLLM

Q19 = (
    "What was the company's profit after tax in the October-to-December "
    "quarter of the year before FY26?"
)
Q16 = (
    "How did the value of new deals from the biggest market change over the "
    "year, and roughly what portion of revenue does that market make up?"
)


def show(title, scripted, query):
    llm = MockLLM(structured={Plan: [scripted]})
    update = make_planner_node(llm, AgentConfig())(initial_state(query))
    print(f"--- {title}")
    print("type:", update["query_type"])
    print("subqueries:", len(update["subqueries"]))
    for text in update["search_queries"]:
        print("  search:", text)
    print("trace:", update["trace"][0].content)
    print("step_count:", update["step_count"])


show(
    "q19 style: rewrite added next to the original",
    Plan(query_type="simple", subqueries=[Q19], rewrites={Q19: "Net income Q3 FY25"}),
    Q19,
)
show(
    "q16 style: one search per fact",
    Plan(
        query_type="multi-hop",
        subqueries=[
            "North America total contract value FY26 and FY25",
            "North America share of revenue",
        ],
    ),
    Q16,
)
show("failure: falls back to the original", LLMError("down"), "What was revenue?")