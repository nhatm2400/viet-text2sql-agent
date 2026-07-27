"""`search_examples` — verified few-shot retrieval over pgvector.

STUB (phase 2). The wiring is here; the retrieval is not.

This is deliberately unimplemented rather than approximated. The one piece of direct Vietnamese
evidence available (the desk-rejected OpenReview submission `cWFLrctwuE`, cited with caveats in
the proposal) reports that schema filtering *underperformed* plain few-shot on execution matching
(~70.9% vs ~88.2%). Retrieval is therefore a hypothesis this project tests in ablation A3, not a
feature to be assumed correct — shipping a half-working version now would poison the baseline it
is supposed to be compared against.
"""

from __future__ import annotations

from langchain_core.tools import tool

from t2sql.tools import ToolResult


@tool
def search_examples(question: str, k: int = 3) -> dict:
    """Find verified question/SQL example pairs similar to the user's question.

    Not available in this build — write the SQL from the schema and glossary instead.

    Args:
        question: the user's question, Vietnamese or English.
        k: how many examples to return.
    """
    return ToolResult(
        status="not_implemented",
        message=(
            "search_examples is not available in this build (phase 2, pgvector). "
            "Use list_schema, get_table_schema and lookup_glossary instead."
        ),
        data={"question": question, "k": k, "examples": []},
        error_kind="internal",
    ).to_dict()
