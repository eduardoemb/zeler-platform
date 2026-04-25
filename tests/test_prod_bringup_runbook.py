from __future__ import annotations

from pathlib import Path

RUNBOOK = Path("infra/docker/PROD_BRINGUP.md")


def test_prod_bringup_runbook_contains_operator_contract() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    required_strings = [
        "source .env.prod",
        "uv run python infra/mongo/smoke_prod.py",
        "infra/docker/PROD_BRINGUP_EVIDENCE.template.md",
        "rs.status()",
        "docker compose down -v",
        "mongosh",
        "dropDatabase()",
        "0 OK",
        "10 connectivity",
        "11 auth",
        "20 rs.status",
        "21 not-primary",
        "30 roundtrip",
        "40 transaction",
        "50 change-stream",
        "60 cleanup",
        "99 unexpected",
    ]

    missing = [text for text in required_strings if text not in content]
    assert missing == []
