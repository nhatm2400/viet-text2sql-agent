"""Prepare ViText2SQL questions over original Spider English schemas and values.

Only exact Spider SQL-AST matches including literals are eligible. This explicit
adaptation is not the unmodified official ViText2SQL benchmark or leaderboard metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from eval.datasets.external.download_vitext2sql import REPO_ROOT, TARGET_DIR, sha256
from eval.harness.scoring import strict_ex
from eval.harness.sqlite_readonly import connect_readonly, database_context, execute_select


def ast_key(item: dict) -> tuple[str, str]:
    return item["db_id"], json.dumps(item["sql"], sort_keys=True, ensure_ascii=False)


def schema_layout(schema: dict) -> tuple:
    return (
        len(schema["table_names_original"]),
        tuple(column[0] for column in schema["column_names_original"]),
        tuple(schema["column_types"]),
        tuple(sorted(schema["primary_keys"])),
        tuple(sorted(tuple(pair) for pair in schema["foreign_keys"])),
    )


def align_items(vietnamese: list[dict], english: list[dict], split: str):
    lookup = defaultdict(list)
    for item in english:
        lookup[ast_key(item)].append(item)
    accepted, excluded = [], []
    for index, item in enumerate(vietnamese):
        ident = f"vi-{split}-{index:04d}"
        queries = sorted({match["query"] for match in lookup[ast_key(item)]})
        if not queries:
            excluded.append(
                {"id": ident, "db_id": item["db_id"], "reason": "no_exact_AST_and_literal_match"}
            )
            continue
        accepted.append(
            {
                "id": ident,
                "source_index": index,
                "db_id": item["db_id"],
                "question_vi": item["question"],
                "gold_sql": queries[0],
                "reference_variants": queries,
                "source_sql_ast_sha256": hashlib.sha256(ast_key(item)[1].encode()).hexdigest(),
            }
        )
    return accepted, excluded


def prepare(split: str, output: Path, *, source: Path = TARGET_DIR) -> dict:
    if output.exists():
        raise FileExistsError("Use a new package path; existing benchmark packages are immutable")
    if not output.resolve().is_relative_to((REPO_ROOT / "data").resolve()):
        raise ValueError("Derived external annotations must stay under git-ignored data/")
    provenance = json.loads((source / "sources.json").read_text(encoding="utf-8"))
    for record in provenance["sources"]:
        if sha256(REPO_ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"Source hash mismatch: {record['path']}")
    raw = source / "raw/syllable-level"
    vietnamese = json.loads((raw / f"{split}.json").read_text(encoding="utf-8"))
    spider = REPO_ROOT / "data/external/spider/raw"
    english = []
    # Use all published annotations from the same archive as the physical databases.
    # train_others is necessary: ViText2SQL re-splits the original Spider corpus.
    with ZipFile(spider / "spider_data.zip") as archive:
        for name in ("train_spider.json", "train_others.json", "dev.json"):
            english.extend(json.loads(archive.read(f"spider_data/{name}")))
        en_schemas = {
            item["db_id"]: item for item in json.loads(archive.read("spider_data/tables.json"))
        }
    accepted, excluded = align_items(vietnamese, english, split)
    vi_schemas = {
        item["db_id"]: item
        for item in json.loads((raw / "tables.json").read_text(encoding="utf-8"))
    }
    incompatible = {
        db_id
        for db_id in {item["db_id"] for item in accepted}
        if db_id not in en_schemas
        or schema_layout(vi_schemas[db_id]) != schema_layout(en_schemas[db_id])
    }
    excluded.extend(
        {"id": item["id"], "db_id": item["db_id"], "reason": "source_schema_index_layout_mismatch"}
        for item in accepted
        if item["db_id"] in incompatible
    )
    accepted = [item for item in accepted if item["db_id"] not in incompatible]
    output.mkdir(parents=True)
    databases = {}
    failures = []
    with ZipFile(spider / "spider_data.zip") as archive:
        for db_id in sorted({item["db_id"] for item in accepted}):
            if not db_id.replace("_", "").isalnum():
                raise ValueError("Unsafe database ID")
            target = output / "databases" / f"{db_id}.sqlite"
            target.parent.mkdir(exist_ok=True)
            with (
                archive.open(f"spider_data/database/{db_id}/{db_id}.sqlite") as src,
                target.open("xb") as dst,
            ):
                shutil.copyfileobj(src, dst)
            databases[db_id] = {
                "path": str(target.relative_to(output)),
                "sha256": sha256(target),
                "context": database_context(target),
            }
    for item in accepted:
        conn = connect_readonly(output / databases[item["db_id"]]["path"])
        try:
            results = [execute_select(conn, sql) for sql in item["reference_variants"]]
            if any(not strict_ex(result, results[0], item["gold_sql"]) for result in results[1:]):
                raise ValueError("Original SQL variants disagree on this database")
            gold = results[0]
            item["gold_validation"] = {
                "row_count": len(gold.rows),
                "columns": gold.columns,
                "empty": not gold.rows,
            }
        except Exception as error:
            failures.append(
                {
                    "id": item["id"],
                    "db_id": item["db_id"],
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
        finally:
            conn.close()
    failed_ids = {item["id"] for item in failures}
    items = [item for item in accepted if item["id"] not in failed_ids]
    (output / "questions.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "exclusions.json").write_text(
        json.dumps(excluded + failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "version": "vitext2sql-spider-en-exact-ast-v1",
        "split": split,
        "setting": "Adapted ViText2SQL Vietnamese questions with original Spider English schemas and values",
        "not_official_vitext2sql_or_spider_score": True,
        "human_sample_audit": "pending; programmatic alignment and execution are not human review",
        "source_count": len(vietnamese),
        "ast_aligned_count": len(accepted),
        "eligible_count": len(items),
        "exclusion_counts": dict(Counter(item["reason"] for item in excluded + failures)),
        "empty_gold_count": sum(item["gold_validation"]["empty"] for item in items),
        "database_count": len(databases),
        "databases": databases,
        "source_provenance": provenance,
        "questions_sha256": sha256(output / "questions.json"),
        "exclusions_sha256": sha256(output / "exclusions.json"),
        "source_sha256": {
            name: sha256(REPO_ROOT / name)
            for name in (
                "eval/harness/prepare_vitext2sql.py",
                "eval/harness/sqlite_readonly.py",
                "eval/datasets/external/download_vitext2sql.py",
            )
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["train", "dev", "test"], default="dev")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.split, args.output)
    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in {"databases", "source_provenance", "source_sha256"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
