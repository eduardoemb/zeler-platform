"""Top-level pytest configuration for the zeler-platform workspace.

This `conftest.py` lives at the repo root so its fixtures are available
to every test directory in the workspace (`tests/`, `gateway/tests/`,
`core/tests/`, `modules/*/tests`, `bootstrap/tests`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# Keep root on sys.path so `import infra.mongo.apply_validators` works
# the same way under any pytest --import-mode setting.
_ROOT_STR = str(ROOT)
if _ROOT_STR not in sys.path:
    sys.path.insert(0, _ROOT_STR)

# Fallback Mongo URI used ONLY when MONGO_URI is unset during local
# integration test runs. Production code (`apply_validators.py`,
# `apply_seeds.py`) intentionally has no such fallback — it fails loud.
# This default exists strictly for developer ergonomics: integration
# tests that touch the local dev container can still run without
# requiring every dev to export MONGO_URI by hand.
_DEV_FALLBACK_MONGO_URI = (
    "mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/"
    "zeler_platform_dev?authSource=admin"
)


@pytest.fixture
def default_mongo_uri() -> str:
    """Resolve `MONGO_URI` from env, falling back to the local dev URI."""
    return os.environ.get("MONGO_URI") or _DEV_FALLBACK_MONGO_URI
