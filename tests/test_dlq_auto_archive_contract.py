from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dlq_auto_archive_is_documented_and_gated() -> None:
    """Q4-b/Q11-c: the queue keeps getting archived, behind its own flag."""
    refresh_doc = _read(ROOT / "docs" / "sheets" / "zelerdata-refresh.md")
    consumer = _read(ROOT / "modules" / "sheets" / "src" / "zeler_sheets" / "consumer.py")
    refresh = _read(
        ROOT / "modules" / "sheets" / "src" / "zeler_sheets" / "formulas" / "refresh.py"
    )
    template = _read(ROOT / "infra" / "gce" / "env-templates" / "sheets-worker.env.template")

    assert "ZELERDATA_DLQ_ARCHIVE_ENABLED" in refresh_doc
    assert "ZELERDATA_DLQ_ARCHIVE_ENABLED" in consumer
    assert "ZELERDATA_DLQ_ARCHIVE_ENABLED=" in template
    # The shipped default keeps the archive off until the operator flips it on.
    default_line = next(
        line for line in template.splitlines() if line.startswith("ZELERDATA_DLQ_ARCHIVE_ENABLED=")
    )
    assert default_line.endswith("false")
    # The archive runs from the refresh cycle, not as a per-seller side effect.
    assert "_dlq_archiver" in refresh
    # A message is never removed without the archive decision that justified it.
    assert "reconciled" in refresh_doc and "retention" in refresh_doc
