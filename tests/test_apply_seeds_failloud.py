from __future__ import annotations

from pathlib import Path

import pytest
from infra.mongo import apply_seeds


def test_main_exits_2_when_mongo_uri_unset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_seeds(mongo_uri: str, seeds_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, seeds_dir))
        return {}

    monkeypatch.setattr(apply_seeds, "apply_seeds", fake_apply_seeds)
    monkeypatch.delenv("MONGO_URI", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        apply_seeds.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "error: MONGO_URI must be set explicitly (no default)\n"
    assert calls == []


def test_main_exits_2_when_mongo_uri_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_seeds(mongo_uri: str, seeds_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, seeds_dir))
        return {}

    monkeypatch.setattr(apply_seeds, "apply_seeds", fake_apply_seeds)
    monkeypatch.setenv("MONGO_URI", "")

    with pytest.raises(SystemExit) as exc_info:
        apply_seeds.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "error: MONGO_URI must be set explicitly (no default)\n"
    assert calls == []
