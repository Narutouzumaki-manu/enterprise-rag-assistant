from app.core.config import Settings


def build_real_components(settings: Settings):
    """Builds the real retriever and agent. Slow (loads the embedding model); run it in a thread."""
    # Imported here so that importing the API (and running tests) never loads the model stack.
    from app.agents.agent import build_agent
    from app.agents.config import AgentConfig
    from app.agents.llm import OpenRouterLLM
    from app.retrieval.factory import build_default_retriever

    config = AgentConfig()
    retriever = build_default_retriever(persist_path=settings.chroma_path)  # may raise ValueError: model mismatch
    llm = OpenRouterLLM.from_env(retries=config.llm_retries)  # needs OPENROUTER_API_KEY; never CachingLLM here
    agent = build_agent(retriever, llm, config)
    return retriever, agent
def real_ingest(path: str):
    """Member 1's pipeline, without its in-memory duplicate list.

    Our database is the authority on duplicates. Left alone, that list would call a re-upload
    after a delete a 'duplicate' with no chunks (the list only forgets on a restart)."""
    from app.ingestion.dedupe import clear_registry
    from app.ingestion.pipeline import ingest_document

    clear_registry()
    return ingest_document(path)