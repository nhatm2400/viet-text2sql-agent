"""Run the API, Streamlit UI or real PostgreSQL role tests using the private local demo profile."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["api", "ui", "test-db", "test-all"])
    args = parser.parse_args()
    profile = ROOT / "data" / "postgres_local" / "demo.env"
    if not profile.exists():
        parser.error("Run python -m scripts.setup_postgres_local first")
    load_dotenv(profile, override=True)
    os.chdir(ROOT)
    if args.service == "api":
        import uvicorn

        uvicorn.run("t2sql.api.main:app", host="127.0.0.1", port=8000)
    elif args.service == "ui":
        from streamlit.web.cli import main as streamlit_main

        sys.argv = [
            "streamlit",
            "run",
            str(ROOT / "ui" / "streamlit_app.py"),
            "--server.address=127.0.0.1",
            "--server.port=8501",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ]
        return streamlit_main()
    else:
        import pytest

        # Tests replay the model; the role tests still exercise real PostgreSQL.
        os.environ["OFFLINE_MODE"] = "1"
        target = ["tests/test_readonly_role.py"] if args.service == "test-db" else ["tests"]
        return pytest.main([*target, "-q", "-rs", "--junitxml=data/postgres_local/tests.xml"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
