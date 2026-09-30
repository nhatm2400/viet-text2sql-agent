from pathlib import Path

import pytest

from eval.datasets.review_v2 import candidates
from eval.harness.ai_review import edge_checks, review, write_revision
from eval.harness.prepare_v2 import freeze


def test_gold_semantic_edges_reject_executable_mutations():
    checks = edge_checks(candidates())
    assert len(checks) == 12
    assert all(item["pass"] and item["mutant_rejected"] for item in checks)


@pytest.mark.skipif(
    not Path("data/benchmark_v2_ready/snapshot.sqlite").exists(),
    reason="Local review package is not installed",
)
def test_ai_revision_never_becomes_human_approval(tmp_path):
    import json

    package = Path("data/benchmark_v2_ready")
    report = review(package)
    assert report["summary"]["python_matches"] == 50
    revised = tmp_path / "revision"
    write_revision(package, revised, report)
    before = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    after = json.loads((revised / "questions.json").read_text(encoding="utf-8"))
    assert [i["gold_sql"] for i in after] == [i["gold_sql"] for i in before]
    assert [i["human_review"] for i in after] == [i["human_review"] for i in before]
    assert all(i["ai_review"]["human_review"] is False for i in after)
    assert (
        sum(a["question_vi"] != b["question_vi"] for a, b in zip(after, before, strict=True)) == 1
    )
    with pytest.raises(ValueError, match="human_review"):
        freeze(revised)
