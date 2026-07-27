"""viet-text2sql-agent — bilingual Text-to-SQL analytics agent.

Package layout:
    config        pydantic-settings, single source of runtime configuration
    llm           provider adapter (anthropic | openai_compatible | bedrock | offline)
    agent         LangGraph ReAct loop, state, prompts
    tools         the tools the agent may call — each independently safe
    guardrails    sqlglot AST policy; the layer the agent cannot opt out of
    retrieval     pgvector-backed glossary + verified example stores (phase 2)
    charts        declarative Pydantic ChartSpec + Plotly renderer
    api           FastAPI surface
    observability self-built Postgres trace store
"""

__version__ = "0.1.0"
