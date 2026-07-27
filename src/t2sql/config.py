"""Runtime configuration. Single source of truth; nothing else reads os.environ directly.

Every value has a default that keeps the project runnable with no .env at all — that is what
makes `make test` / `make demo-offline` work on a fresh clone with zero keys and no database.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/t2sql/config.py -> repo root
PACKAGE_ROOT = Path(__file__).resolve().parent

ModelRole = Literal["fast", "strong"]
ModelProvider = Literal["anthropic", "openai_compatible", "bedrock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),  # we genuinely want fields named model_*
    )

    # --- mode ---------------------------------------------------------------
    offline_mode: bool = True
    """When true every LLM call is replayed from tests/fixtures — no keys, no network."""

    # --- model provider -----------------------------------------------------
    model_provider: ModelProvider = "anthropic"
    model_fast: str = "claude-haiku-4-5-20251001"
    model_strong: str = "claude-opus-5"
    model_temperature: float = 0.0
    model_max_tokens: int = 2048
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    aws_region: str = ""

    # --- database -----------------------------------------------------------
    database_url: str = ""
    """Admin connection. Used by db/seed.py and the trace writer only."""
    database_url_ro: str = ""
    """Read-only connection (role t2sql_ro). The ONLY connection execute_sql may use."""

    # --- agent bounds -------------------------------------------------------
    max_iterations: int = 6
    max_rows: int = 1000
    statement_timeout_ms: int = 5000

    # --- observability ------------------------------------------------------
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- paths --------------------------------------------------------------
    @property
    def schema_sql_path(self) -> Path:
        return REPO_ROOT / "db" / "schema.sql"

    @property
    def glossary_path(self) -> Path:
        return REPO_ROOT / "db" / "glossary.yaml"

    @property
    def policy_path(self) -> Path:
        return PACKAGE_ROOT / "guardrails" / "policy.yaml"

    @property
    def fixtures_path(self) -> Path:
        return REPO_ROOT / "tests" / "fixtures"

    @property
    def results_path(self) -> Path:
        return REPO_ROOT / "eval" / "results"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    def model_name(self, role: ModelRole) -> str:
        return self.model_fast if role == "fast" else self.model_strong


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Drop the cache — used by tests that mutate the environment."""
    get_settings.cache_clear()
    return get_settings()
