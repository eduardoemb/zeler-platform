from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_greenfield_live_readiness_followups_document_remaining_warnings() -> None:
    followups = ROOT / "sdd" / "greenfield-live-readiness" / "follow-ups.md"

    text = followups.read_text()

    required_phrases = [
        "wave numbering",
        "0-4",
        "H2 order",
        "bootstrap.retry",
        "missing_fields",
        "alerts catalog",
        "follow-up SDD",
    ]
    for phrase in required_phrases:
        assert phrase in text
