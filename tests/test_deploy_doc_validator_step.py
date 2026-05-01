from __future__ import annotations

from pathlib import Path


def test_deploy_doc_mentions_apply_validators_and_drift_check() -> None:
    content = Path("docs/deploy.md").read_text(encoding="utf-8")

    assert 'python -m infra.mongo.apply_validators --mongo-uri="$MONGO_URI"' in content
    assert 'python -m infra.mongo.drift_check --mongo-uri="$MONGO_URI"' in content
