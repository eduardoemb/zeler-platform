from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_precalculated_heavy_formulas_are_documented_and_gated() -> None:
    """Q3-b/Q8-a/Q16: heavy aggregates are precalculated behind their own flag."""
    refresh_doc = _read(ROOT / "docs" / "sheets" / "zelerdata-refresh.md")
    consumer = _read(ROOT / "modules" / "sheets" / "src" / "zeler_sheets" / "consumer.py")
    template = _read(ROOT / "infra" / "gce" / "env-templates" / "sheets-worker.env.template")

    assert "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED" in refresh_doc
    assert "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED" in consumer
    assert "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED=" in template
    # The shipped default keeps warming off until the operator flips it on.
    default_line = next(
        line
        for line in template.splitlines()
        if line.startswith("ZELERDATA_PRECALCULATED_FORMULAS_ENABLED=")
    )
    assert default_line.endswith("false")
    # The sheet call degrades to the existing on-demand path, never to a stale
    # or partial table.
    assert "on-demand" in refresh_doc
    assert "never cached" in refresh_doc
