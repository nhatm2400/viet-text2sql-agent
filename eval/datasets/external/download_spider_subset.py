"""Download a Spider 1.0 dev subset into the git-ignored `data/external/` directory.

STUB — not implemented and NOT executed by the scaffold.

Spider 1.0 is used here as an **English sanity check only**. It is effectively saturated for
modern LLMs (~86-91% EX for GPT-4-class methods), so a good score on it is a floor check, not
evidence of quality, and it is reported as such.

    python eval/datasets/external/download_spider_subset.py --accept-license
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIR = REPO_ROOT / "data" / "external" / "spider"

SOURCE = "https://yale-lily.github.io/spider"
VERSION_TAG = "spider-1.0-dev@TODO-pin-a-release"  # TODO(phase2): pin before any reported run
SUBSET_SIZE = 100

LICENSE_NOTICE = f"""
================================================================================
Spider 1.0 — LICENCE NOTICE
================================================================================
Source  : {SOURCE}
Paper   : Yu T. et al. (2018), "Spider: A Large-Scale Human-Labeled Dataset for
          Complex and Cross-Domain Semantic Parsing and Text-to-SQL", EMNLP 2018.
Licence : CC BY-SA 4.0 — attribution required, share-alike.

Downloaded files stay inside data/ (git-ignored) and are not committed.

Reporting note: Spider 1.0 is saturated. Report it as a floor check with the
subset size and version stated, never as a headline result.
================================================================================
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a Spider dev subset (stub).")
    parser.add_argument(
        "--accept-license", action="store_true", help="acknowledge the notice above"
    )
    parser.add_argument("--n", type=int, default=SUBSET_SIZE, help="subset size to sample")
    args = parser.parse_args(argv)

    print(LICENSE_NOTICE)
    if not args.accept_license:
        print("Re-run with --accept-license to proceed. Nothing was downloaded.")
        return 0

    print(f"Would download Spider dev @ {VERSION_TAG} from {SOURCE}")
    print(f"Would sample {args.n} items into {TARGET_DIR}")
    print("Would then require a manual audit of a sample before any number is reported.\n")

    raise NotImplementedError(  # TODO(phase2)
        "download_spider_subset is a stub. Implement it in phase 2 (proposal week 5-6) and pin "
        "VERSION_TAG to an exact release first."
    )


if __name__ == "__main__":
    sys.exit(main())
