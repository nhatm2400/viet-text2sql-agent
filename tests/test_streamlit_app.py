"""Exercise user-visible reply and connection-error states through Streamlit's runtime."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from t2sql.config import reload_settings

APP = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"


def configure(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "1")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL_RO", "")
    reload_settings()


def test_text_only_answer_is_shown_as_information(monkeypatch):
    configure(monkeypatch)
    response = {
        "status": "answered",
        "answer": "Không chạy câu SQL này.",
        "sql": None,
        "rows": [],
        "chart_spec": None,
        "tool_calls": [],
        "trace_id": "reply-test",
    }
    monkeypatch.setattr("t2sql.agent.build.run_agent", lambda question: response)
    app = AppTest.from_file(str(APP)).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("không thực thi SQL" in message.value for message in app.info)


def test_model_connection_failure_has_recovery_message(monkeypatch):
    configure(monkeypatch)

    def unavailable(question):
        raise ConnectionError("PRIVATE_SERVER_DETAILS")

    monkeypatch.setattr("t2sql.agent.build.run_agent", unavailable)
    app = AppTest.from_file(str(APP)).run()
    app.button[0].click().run()
    assert not app.exception
    assert "ConnectionError" in app.error[0].value
    assert "PRIVATE_SERVER_DETAILS" not in app.error[0].value
    assert any("thử lại" in caption.value for caption in app.caption)
