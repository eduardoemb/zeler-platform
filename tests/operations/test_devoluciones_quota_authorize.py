from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from infra.operations import devoluciones_quota_authorize as authorize_module

from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
from zeler_platform_core.devoluciones_runs import RunBinding


def _binding() -> RunBinding:
    return RunBinding(
        authorization_id="authorization-1",
        cohort_id="cohort-1",
        seller_id="82453304",
        scope="devoluciones",
        start=datetime(2026, 6, 1, tzinfo=UTC),
        end=datetime(2026, 7, 1, tzinfo=UTC),
        partition_version="v1",
        release_fingerprints={"sheets": "a" * 64},
    )


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
    )


def test_write_run_environment_is_atomic_root_only_and_exact(tmp_path: Path) -> None:
    environment_file = tmp_path / "quota-run.env"

    authorize_module.write_run_environment(environment_file, _binding().run_id)

    assert environment_file.read_text() == (f"ZELERDATA_DEVOLUCIONES_RUN_ID={_binding().run_id}\n")
    assert environment_file.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [environment_file]


@pytest.mark.asyncio
async def test_authorize_run_uses_fenced_repository_before_writing_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    operation = _operation()

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        events.append(("acquire", kwargs))
        return operation

    async def finish(**kwargs: Any) -> None:
        events.append(("finish", kwargs))

    class Repository:
        def __init__(self, db: Any) -> None:
            events.append(("repository", db))

        async def create(self, binding: RunBinding, **kwargs: Any) -> bool:
            events.append(("create", (binding, kwargs)))
            return True

    monkeypatch.setattr(authorize_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(authorize_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(authorize_module, "MongoRunWindowRepository", Repository)
    environment_file = tmp_path / "quota-run.env"

    run_id = await authorize_module.authorize_quota_run(
        db=object(),
        binding=_binding(),
        environment_file=environment_file,
        now=lambda: datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert run_id == _binding().run_id
    assert [event[0] for event in events] == ["acquire", "repository", "create", "finish"]
    create_binding, create_kwargs = events[2][1]
    assert create_binding == _binding()
    assert create_kwargs == {
        "operation": operation,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    assert events[3][1]["succeeded"] is True
    assert environment_file.read_text().endswith(f"{run_id}\n")


@pytest.mark.asyncio
async def test_failed_authorization_is_released_and_never_selects_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finishes: list[dict[str, Any]] = []

    async def acquire(**_: Any) -> DevolucionesOperationContext:
        return _operation()

    async def finish(**kwargs: Any) -> None:
        finishes.append(kwargs)

    class RejectedRepository:
        def __init__(self, _: Any) -> None:
            pass

        async def create(self, *_: Any, **__: Any) -> bool:
            return False

    monkeypatch.setattr(authorize_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(authorize_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(authorize_module, "MongoRunWindowRepository", RejectedRepository)
    environment_file = tmp_path / "quota-run.env"

    with pytest.raises(RuntimeError, match="not created"):
        await authorize_module.authorize_quota_run(
            db=object(), binding=_binding(), environment_file=environment_file
        )

    assert finishes[0]["succeeded"] is False
    assert finishes[0]["error_code"] == "quota_run_authorization_failed"
    assert not environment_file.exists()


def test_cli_requires_explicit_authority_and_fixed_seller() -> None:
    parser = authorize_module.build_parser()
    base = [
        "--seller-id",
        "82453304",
        "--authorization-id",
        "authorization-1",
        "--cohort-id",
        "cohort-1",
        "--date-from",
        "2026-06-01",
        "--date-to",
        "2026-07-01",
        "--release-fingerprint",
        f"sheets={'a' * 64}",
    ]

    with pytest.raises(ValueError, match="confirmation"):
        authorize_module.binding_from_args(parser.parse_args(base))
    approved = parser.parse_args(
        [*base, "--confirm-approved-runtime", "--confirm-run-authorization"]
    )
    assert authorize_module.binding_from_args(approved) == _binding()
    approved.seller_id = "1"
    with pytest.raises(ValueError, match="seller"):
        authorize_module.binding_from_args(approved)
