"""Download the ViText2SQL evaluation subset into the git-ignored `data/external/` directory.

Downloads pinned annotations and original Spider resources; never fetches paid APIs.

LICENCE: ViText2SQL is released for research and educational purposes only, with no
redistribution in any form. That is why this repository ships a script instead of data, why
`data/` is git-ignored, and why the notice below is printed before anything is fetched rather
than buried in a README.

    python eval/datasets/external/download_vitext2sql.py --accept-license
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIR = REPO_ROOT / "data" / "external" / "vitext2sql"

# Version pin. Every reported number states the version it was measured on.
SOURCE_REPO = "https://github.com/VinAIResearch/ViText2SQL"
VERSION_TAG = "e759141d891feb794bb9a9fb912d544b25583b3c"
SPIDER_COMMIT = "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c"
SPIDER_ARCHIVE_SHA256 = "00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b"
SPIDER_ARCHIVE_URL = "https://drive.usercontent.google.com/download?id=1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J&export=download&confirm=t"

LICENSE_NOTICE = f"""
================================================================================
ViText2SQL — LICENCE NOTICE
================================================================================
Source : {SOURCE_REPO}
Paper  : Nguyen A.T., Dao M.H., Nguyen D.Q. (2020),
         "A Pilot Study of Text-to-SQL Semantic Parsing for Vietnamese",
         Findings of EMNLP 2020.

The dataset is released for RESEARCH AND EDUCATIONAL PURPOSES ONLY.
REDISTRIBUTION IN ANY FORM IS NOT PERMITTED.

By continuing you confirm that your use is research/educational, and that the
downloaded files stay inside data/ (git-ignored) and are never committed,
mirrored, or attached to a release.

Setting note: ViText2SQL translated BOTH the questions AND the schemas into
Vietnamese. This project evaluates Vietnamese questions over an ENGLISH schema,
so results on this subset are related but not directly comparable to core_vi and
must be reported separately.
================================================================================
"""


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url: str, target: Path, *, archive: bool = False) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".partial")
        request = urllib.request.Request(url, headers={"User-Agent": "viet-text2sql-research"})
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        if archive:
            from zipfile import ZipFile

            with ZipFile(temporary) as zipped:
                if "spider_data/database/architecture/architecture.sqlite" not in zipped.namelist():
                    raise ValueError("Unexpected Spider archive layout")
        elif target.suffix == ".json":
            json.loads(temporary.read_text(encoding="utf-8"))
        temporary.replace(target)
    actual_hash = sha256(target)
    if archive and actual_hash != SPIDER_ARCHIVE_SHA256:
        raise ValueError("Spider archive differs from the pinned SHA-256; review a new version")
    return {"url": url, "path": str(target.relative_to(REPO_ROOT)), "sha256": actual_hash}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download pinned ViText2SQL and Spider resources.")
    parser.add_argument(
        "--accept-license", action="store_true", help="acknowledge the notice above"
    )
    parser.add_argument("--splits", nargs="+", choices=["train", "dev", "test"], default=["dev"])
    args = parser.parse_args(argv)

    print(LICENSE_NOTICE)
    if not args.accept_license:
        print("Re-run with --accept-license to proceed. Nothing was downloaded.")
        return 0

    sources = []
    vi_base = f"https://raw.githubusercontent.com/VinAIResearch/ViText2SQL/{VERSION_TAG}"
    for name in ["tables.json", *[f"{split}.json" for split in sorted(set(args.splits))]]:
        sources.append(
            fetch(f"{vi_base}/data/syllable-level/{name}", TARGET_DIR / "raw/syllable-level" / name)
        )
    sources.append(fetch(f"{vi_base}/README.md", TARGET_DIR / "raw/README.md"))
    spider = REPO_ROOT / "data/external/spider/raw"
    en_base = f"https://raw.githubusercontent.com/taoyds/spider/{SPIDER_COMMIT}/evaluation_examples/examples"
    for name in ("tables.json", "train_spider.json", "dev.json"):
        sources.append(fetch(f"{en_base}/{name}", spider / name))
    sources.append(fetch(SPIDER_ARCHIVE_URL, spider / "spider_data.zip", archive=True))
    manifest = {
        "vitext2sql_commit": VERSION_TAG,
        "spider_commit": SPIDER_COMMIT,
        "license_acknowledged": True,
        "sources": sources,
    }
    (TARGET_DIR / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved {len(sources)} source hashes to {TARGET_DIR / 'sources.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
