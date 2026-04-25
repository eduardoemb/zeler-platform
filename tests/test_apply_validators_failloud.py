from __future__ import annotations

from pathlib import Path

import pytest
from infra.mongo import apply_validators


def test_main_exits_2_when_mongo_uri_unset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_validators(mongo_uri: str, schemas_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, schemas_dir))
        return {}

    monkeypatch.setattr(apply_validators, "apply_validators", fake_apply_validators)
    monkeypatch.delenv("MONGO_URI", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        apply_validators.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "error: MONGO_URI must be set explicitly (no default)\n"
    assert calls == []


def test_main_exits_2_when_mongo_uri_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_validators(mongo_uri: str, schemas_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, schemas_dir))
        return {}

    monkeypatch.setattr(apply_validators, "apply_validators", fake_apply_validators)
    monkeypatch.setenv("MONGO_URI", "")

    with pytest.raises(SystemExit) as exc_info:
        apply_validators.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "error: MONGO_URI must be set explicitly (no default)\n"
    assert calls == []
