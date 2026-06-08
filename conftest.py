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
WORKSPACE_IMPORT_PATHS = (
    ROOT,
    ROOT / "gateway/src",
    ROOT / "core/src",
    ROOT / "modules/repricer/src",
    ROOT / "modules/sheets/src",
    ROOT / "modules/publicador/src",
    ROOT / "modules/autoreply/src",
    ROOT / "bootstrap/src",
)

# Keep workspace packages available to tests and subprocess import smoke tests
# the same way as pyproject's pytest `pythonpath` setting.
for import_path in reversed(WORKSPACE_IMPORT_PATHS):
    path_text = str(import_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

_existing_pythonpath = [part for part in os.environ.get("PYTHONPATH", "").split(os.pathsep) if part]
_workspace_pythonpath = [str(path) for path in WORKSPACE_IMPORT_PATHS]
os.environ["PYTHONPATH"] = os.pathsep.join(
    [
        *_workspace_pythonpath,
        *[part for part in _existing_pythonpath if part not in _workspace_pythonpath],
    ]
)

# Fallback Mongo URI used ONLY when MONGO_URI is unset during local
# integration test runs. Production code (`apply_validators.py`,
# `apply_seeds.py`) intentionally has no such fallback — it fails loud.
# This default exists strictly for developer ergonomics: integration
# tests that touch the local dev container can still run without
# requiring every dev to export MONGO_URI by hand.
_DEV_FALLBACK_MONGO_URI = (
    "mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/"
    "zeler_platform_dev?replicaSet=rs0-dev&directConnection=true&authSource=admin"
)


@pytest.fixture
def default_mongo_uri() -> str:
    """Resolve `MONGO_URI` from env, falling back to the local dev URI."""
    return os.environ.get("MONGO_URI") or _DEV_FALLBACK_MONGO_URI
