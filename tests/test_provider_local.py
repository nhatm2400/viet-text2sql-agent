"""The public app factory must use the native adapter and preserve its bounded options."""

from langchain_core.messages import HumanMessage

from t2sql.config import reload_settings
from t2sql.llm.ollama_local import OllamaLocal
from t2sql.llm.provider import OfflineProvider, get_model


def test_app_factory_uses_native_ollama(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "0")
    monkeypatch.setenv("MODEL_PROVIDER", "ollama_local")
    monkeypatch.setenv("MODEL_FAST", "qwen3:4b")
    monkeypatch.setenv("MODEL_STRONG", "qwen3:4b")
    monkeypatch.setenv("MODEL_MAX_TOKENS", "4096")
    reload_settings()
    captured = []

    def fake_request(base_url, path, payload=None, **kwargs):
        captured.append((base_url, path, payload))
        return {
            "message": {"role": "assistant", "content": "OK"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 2,
        }

    monkeypatch.setattr("t2sql.llm.ollama_local.request_json", fake_request)
    try:
        model = get_model("strong")
        assert isinstance(model, OllamaLocal)
        assert model.invoke([HumanMessage(content="hello")]).content == "OK"
        assert captured[0][2]["model"] == "qwen3:4b"
        assert captured[0][2]["options"]["num_predict"] == 4096
        assert captured[0][2]["options"]["num_ctx"] == 8192
        assert get_model(max_tokens=512).num_predict == 512
    finally:
        monkeypatch.setenv("OFFLINE_MODE", "1")
        reload_settings()


def test_offline_mode_takes_precedence_over_local_provider(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "ollama_local")
    reload_settings()
    try:
        assert isinstance(get_model(), OfflineProvider)
    finally:
        reload_settings()
