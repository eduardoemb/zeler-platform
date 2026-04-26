from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "infra" / "mongo" / "backup" / "mongodump_cron.sh"


def test_mongodump_cron_contract() -> None:
    assert SCRIPT_PATH.exists()
    assert os.access(SCRIPT_PATH, os.X_OK)

    content = SCRIPT_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    assert lines[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in content
    assert "MONGO_URI" in content
    assert "GCS_BUCKET" in content
    assert "BACKUP_RETENTION_DAYS:-30" in content
    assert "$(date" in content
    assert "gs://${GCS_BUCKET}/mongo/" in content
    assert "mongodump" in content
    assert "--archive" in content
    assert "--gzip" in content
    assert "gsutil cp" in content or "gcloud storage cp" in content
    assert (
        "gsutil rm" in content
        or "gcloud storage rm" in content
        or "Deleting aged object" in content
    )
    assert re.search(r"OBJECT_PATH=.*gs://\$\{GCS_BUCKET\}/mongo/", content)


def test_mongodump_cron_rejects_uri_without_replica_set() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert re.search(
        r"if\s+\[\[\s+\"?\$\{?MONGO_URI\}?\"?\s+!=\s+\*\"replicaSet=\"\*\s+\]\]",
        content,
    )
    assert "replicaSet=" in content
    assert re.search(r"exit\s+1", content)
