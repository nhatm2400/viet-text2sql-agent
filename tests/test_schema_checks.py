from t2sql.tools.schema_tools import get_table_schema, load_check_constraints, schema_block


def test_check_parser_preserves_column_and_table_predicates(tmp_path):
    path = tmp_path / "schema.sql"
    path.write_text(
        "CREATE TABLE sample (status TEXT CHECK(status IN ('ready','done')), "
        "rating INT CHECK(rating BETWEEN 1 AND 5), "
        "CONSTRAINT valid_pair CHECK(status <> 'done' OR rating >= 3));",
        encoding="utf-8",
    )
    checks = load_check_constraints(str(path))["sample"]
    assert len(checks) == 3
    assert "status IN ('ready', 'done')" in checks
    assert "rating BETWEEN 1 AND 5" in checks
    assert "status <> 'done' OR rating >= 3" in checks


def test_prompt_and_schema_tool_expose_database_spelling():
    checks = load_check_constraints()
    assert "'cancelled'" in checks["orders"][0]
    assert "'canceled'" not in " ".join(checks["orders"])
    assert "'succeeded'" in " ".join(checks["payments"])
    with_checks = schema_block()
    old_context = schema_block(include_checks=False)
    assert "CHECK rating BETWEEN 1 AND 5" in with_checks
    restored = "\n".join(
        line for line in with_checks.splitlines() if not line.startswith("    CHECK ")
    )
    assert restored == old_context
    table = get_table_schema.invoke({"table_name": "orders"})
    assert table["data"]["check_constraints"] == checks["orders"]
