"""Protocol and provenance checks; no network calls and no model-accuracy claims."""

import json

import pytest
from langchain_core.messages import HumanMessage

from db.seed import SNAPSHOT_END, build_rows
from eval.harness.live_local import load_package, select_items
from eval.harness.prepare_v2 import digest, freeze, sqlite_sql
from t2sql.llm.ollama_local import OllamaLocal, request_json


def test_v2_business_invariants_and_v1_preserved():
    old = build_rows()
    rows = build_rows(version="v2")
    orders = {o["order_id"]: o for o in rows["orders"]}
    addresses = {a["address_id"]: a for a in rows["addresses"]}
    payments = {p["order_id"]: p for p in rows["payments"]}
    for shipment in rows["shipments"]:
        order = orders[shipment["order_id"]]
        assert addresses[shipment["address_id"]]["customer_id"] == order["customer_id"]
        assert (
            order["created_at"]
            <= payments[order["order_id"]]["paid_at"]
            <= shipment["shipped_at"]
            <= SNAPSHOT_END
        )
        if shipment["delivered_at"]:
            assert (
                shipment["shipped_at"]
                <= shipment["delivered_at"]
                == order["completed_at"]
                <= SNAPSHOT_END
            )
    completed = {
        (orders[i["order_id"]]["customer_id"], i["product_id"])
        for i in rows["order_items"]
        if orders[i["order_id"]]["status"] == "completed"
    }
    assert all(
        (r["customer_id"], r["product_id"]) in completed and r["created_at"] <= SNAPSHOT_END
        for r in rows["reviews"]
    )
    assert old["payments"] == rows["payments"]  # v2 preserves financial values
    assert len(old["reviews"]) == 8298


@pytest.mark.parametrize(
    "url", ["https://api.openai.com", "http://example.com", "http://user:pw@localhost"]
)
def test_adapter_rejects_nonlocal_or_credential_endpoints(url):
    with pytest.raises(ValueError):
        request_json(url, "/api/tags")


def test_actual_ollama_tool_response_and_usage_mapping(monkeypatch):
    def response(base, path, payload):
        assert payload["stream"] is False and payload["think"] is True
        assert payload["messages"][0]["role"] == "user"
        assert payload["options"]["num_predict"] == 4096
        return {
            "message": {
                "content": "",
                "thinking": "Internal reasoning must not become executable SQL.",
                "tool_calls": [
                    {"function": {"name": "execute_sql", "arguments": {"sql": "SELECT 1"}}}
                ],
            },
            "prompt_eval_count": 123,
            "eval_count": 10,
            "done_reason": "stop",
        }

    monkeypatch.setattr("t2sql.llm.ollama_local.request_json", response)
    model = OllamaLocal(num_predict=4096)
    result = model.invoke([HumanMessage(content="Question")])
    assert result.tool_calls[0]["args"] == {"sql": "SELECT 1"}
    assert result.content == ""
    assert result.usage_metadata["total_tokens"] == 133
    assert len(model.audit) == 1


def test_pilot_selection_preserves_dataset_order_and_test_cannot_be_filtered():
    items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert select_items(items, "dev", ["c", "a"], 0) == [items[0], items[2]]
    for split, ids, limit in [
        ("test", ["a"], 0),
        ("test", None, 1),
        ("dev", ["missing"], 0),
        ("dev", ["a", "a"], 0),
        ("dev", ["a"], 1),
    ]:
        with pytest.raises(ValueError):
            select_items(items, split, ids, limit)


def test_missing_human_review_prevents_freeze_and_test(tmp_path):
    (tmp_path / "snapshot.sqlite").write_bytes(b"placeholder")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"snapshot_sha256": digest(tmp_path / "snapshot.sqlite")})
    )
    items = [
        {"id": str(i), "split": "dev" if i < 20 else "test", "human_review": "pending"}
        for i in range(50)
    ]
    (tmp_path / "questions.json").write_text(json.dumps(items))
    with pytest.raises(ValueError, match="human_review"):
        freeze(tmp_path)
    with pytest.raises(ValueError, match="human review"):
        load_package(tmp_path, "test")


def test_sqlite_elapsed_time_preserves_five_day_threshold():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    sql = "SELECT CASE WHEN julianday('2026-01-07') - julianday('2026-01-01') > 5 THEN 1 ELSE 0 END"
    assert conn.execute(sqlite_sql(sql)).fetchone()[0] == 1
    conn.close()
