"""Cross-check gold SQL against Python references and deliberate semantic errors."""

from eval.datasets.local_dev.cases import build_cases
from eval.harness.local_validation import validate_snapshot


def test_gold_and_mutants_on_real_sqlite():
    cases = build_cases()
    result = validate_snapshot(20260727, cases)
    assert len(cases) == 30
    assert len({c["family"] for c in cases}) == 10
    assert len(result["table_counts"]) == 12
    assert result["data_diagnostics"]["foreign_key_violations"] == 0
    for record in result["records"]:
        assert "error" not in record, record
        for key in (
            "strict_oracle_match",
            "relaxed_oracle_match",
            "policy_allowed",
            "rewritten_oracle_match",
            "mutant_executes",
            "mutant_policy_allowed",
            "mutant_detected",
        ):
            assert record[key], (record["id"], key, record)
