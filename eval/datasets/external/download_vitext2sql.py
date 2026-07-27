"""Download the ViText2SQL evaluation subset into the git-ignored `data/external/` directory.

STUB — not implemented and NOT executed by the scaffold. It prints the licence, states what it
would fetch, and exits.

LICENCE: ViText2SQL is released for research and educational purposes only, with no
redistribution in any form. That is why this repository ships a script instead of data, why
`data/` is git-ignored, and why the notice below is printed before anything is fetched rather
than buried in a README.

    python eval/datasets/external/download_vitext2sql.py --accept-license
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIR = REPO_ROOT / "data" / "external" / "vitext2sql"

# Version pin. Every reported number states the version it was measured on.
SOURCE_REPO = "https://github.com/VinAIResearch/ViText2SQL"
VERSION_TAG = "main@TODO-pin-a-commit-sha"  # TODO(phase2): pin an exact commit before any run
SUBSET_SIZE = 100

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the ViText2SQL subset (stub).")
    parser.add_argument(
        "--accept-license", action="store_true", help="acknowledge the notice above"
    )
    parser.add_argument("--n", type=int, default=SUBSET_SIZE, help="subset size to sample")
    args = parser.parse_args(argv)

    print(LICENSE_NOTICE)
    if not args.accept_license:
        print("Re-run with --accept-license to proceed. Nothing was downloaded.")
        return 0

    print(f"Would download {SOURCE_REPO} @ {VERSION_TAG}")
    print(f"Would sample {args.n} items into {TARGET_DIR}")
    print("Would then require a manual audit of a sample before any number is reported.\n")

    raise NotImplementedError(  # TODO(phase2)
        "download_vitext2sql is a stub. Implement it in phase 2 (proposal week 5-6), and pin "
        "VERSION_TAG to an exact commit SHA first — an unpinned benchmark subset makes every "
        "number derived from it unreproducible."
    )


if __name__ == "__main__":
    sys.exit(main())
