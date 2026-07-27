"""Provider-agnostic model access. `OFFLINE_MODE=1` replaces every call with a fixture."""

from t2sql.llm.provider import OfflineProvider, get_model

__all__ = ["OfflineProvider", "get_model"]
