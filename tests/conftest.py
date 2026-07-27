"""Shared test configuration.

The entire suite runs offline: no Docker, no network, no live database, no API keys. That is a
hard requirement, not a convenience — CI runs exactly these tests on a shared runner with nothing
provisioned, and a test that quietly needs infrastructure would turn a green pipeline into a lie.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, REPO_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Set before any t2sql import reads it.
os.environ.setdefault("OFFLINE_MODE", "1")


@pytest.fixture(autouse=True)
def _isolate_traces():
    """Each test starts with an empty trace buffer so trace assertions cannot leak between tests."""
    from t2sql.observability import tracing

    tracing.clear_trace()
    yield
    tracing.clear_trace()


@pytest.fixture
def settings():
    from t2sql.config import reload_settings

    return reload_settings()
