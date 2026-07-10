from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from infra.operations.zelerdata_read_model_reconcile import (
    build_arg_parser as build_reconciliation_arg_parser,
)
from infra.operations.zelerdata_read_model_reconcile import (
    build_reconciliation_request,
)
from infra.rabbitmq.sheets_devoluciones_topology import _build_parser

ROOT = Path(__file__).resolve().parents[1]
SHEETS_PYPROJECT = ROOT / "modules" / "sheets" / "pyproject.toml"
SHEETS_WORKER_DOCKERFILE = ROOT / "modules" / "sheets" / "Dockerfile.worker"
STARTUP = ROOT / "infra" / "gce" / "platform-vm-startup.sh"
RECONCILE_WRAPPER = ROOT / "infra" / "gce" / "zelerdata-devoluciones-reconcile.sh"
TOPOLOGY_WRAPPER = ROOT / "infra" / "gce" / "zelerdata-devoluciones-topology.sh"
COMPOSE_FILE = ROOT / "infra" / "gce" / "docker-compose.yml"
SYSTEMD_DIR = ROOT / "infra" / "gce" / "systemd"
RECONCILE_SERVICE = SYSTEMD_DIR / "zelerdata-devoluciones-reconcile.service"
RECONCILE_TIMER = SYSTEMD_DIR / "zelerdata-devoluciones-reconcile.timer"
RECONCILE_ALERT_SERVICE = SYSTEMD_DIR / "zelerdata-devoluciones-reconcile-alert.service"
DEPLOY_DOC = ROOT / "docs" / "deploy.md"
RECONCILIATION_DOC = ROOT / "docs" / "sheets" / "zelerdata-read-model-reconciliation.md"
FORMULA_DOC = ROOT / "docs" / "sheets" / "zelerdata-formulas.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_blocks(markdown: str) -> tuple[str, ...]:
    return tuple(
        fenced.split("```", 1)[0] for fenced in markdown.split("```bash")[1:] if "```" in fenced
    )


def test_sheets_runtime_keeps_motor_and_proves_frozen_reconcile_interpreter() -> None:
    pyproject = tomllib.loads(_read(SHEETS_PYPROJECT))
    dependencies = pyproject["project"]["dependencies"]
    dockerfile = _read(SHEETS_WORKER_DOCKERFILE)

    assert any(str(dependency).startswith("motor>=") for dependency in dependencies)
    assert "RUN test -x .venv/bin/python" in dockerfile
    assert (
        'RUN .venv/bin/python -c "import motor.motor_asyncio; '
        'import infra.operations.zelerdata_read_model_reconcile"'
    ) in dockerfile
    runtime_stanza = dockerfile.split("USER appuser", 1)[1]
    assert "pip install" not in runtime_stanza
    assert "uv sync" not in runtime_stanza


def test_topology_wrapper_uses_packaged_worker_one_shot_without_host_python() -> None:
    dockerfile = _read(SHEETS_WORKER_DOCKERFILE)
    wrapper = _read(TOPOLOGY_WRAPPER)

    assert "COPY infra/rabbitmq ./infra/rabbitmq" in dockerfile
    assert "import infra.rabbitmq.sheets_devoluciones_topology" in dockerfile
    assert "/opt/zeler-platform/.venv/bin/python" not in wrapper
    assert 'source "$ENV_FILE"' not in wrapper
    assert '/usr/bin/docker compose --file "$COMPOSE_FILE" run --rm --no-deps -T' in wrapper
    assert "--volume /var/run/docker.sock:/var/run/docker.sock" in wrapper
    assert "--entrypoint /app/.venv/bin/python" in wrapper
    assert "sheets-worker -m infra.rabbitmq.sheets_devoluciones_topology" in wrapper
    assert "MONGO_URI" not in wrapper
    assert "MONGO_DB" not in wrapper


@pytest.mark.parametrize(
    "argv",
    [
        ("plan",),
        ("prestart", "--execute"),
        ("bind-claims", "--execute"),
        ("rollback", "--execute"),
    ],
)
def test_every_topology_command_uses_socket_capable_ephemeral_root_one_shot(
    argv: tuple[str, ...],
) -> None:
    parsed = _build_parser().parse_args(argv)
    wrapper = _read(TOPOLOGY_WRAPPER)
    one_shot = wrapper.split("run_topology() {", 1)[1].split("}", 1)[0]

    assert parsed.command == argv[0]
    assert "--user 0:0" in one_shot
    assert one_shot.index("--user 0:0") < one_shot.index(
        "--volume /var/run/docker.sock:/var/run/docker.sock"
    )
    assert 'infra.rabbitmq.sheets_devoluciones_topology "$@"' in one_shot
    assert "--privileged" not in one_shot
    assert "set -x" not in wrapper


def test_topology_privilege_boundary_keeps_persistent_worker_non_root() -> None:
    dockerfile = _read(SHEETS_WORKER_DOCKERFILE)
    compose = _read(COMPOSE_FILE)
    worker = compose.split("  sheets-worker:", 1)[1].split("  autoreply-worker:", 1)[0]
    deploy = _read(DEPLOY_DOC)
    section = deploy.split(
        "## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation",
        1,
    )[1].split("---", 1)[0]

    assert "USER appuser" in dockerfile
    assert "user:" not in worker
    assert "privileged:" not in worker
    assert "/var/run/docker.sock" not in worker
    assert "ephemeral topology one-shot" in section
    assert "`--user 0:0`" in section
    assert "`appuser` (UID 1001)" in section
    assert "persistent worker never mounts the Docker socket" in section


def test_reconcile_wrapper_renews_the_enclosing_closed_range_with_frozen_python() -> None:
    wrapper = _read(RECONCILE_WRAPPER)

    assert wrapper.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "ACCEPTED_RANGE_START=2026-06-01" in wrapper
    assert "ACCEPTED_BASELINE_THROUGH=2026-07-09" in wrapper
    assert "RANGE_START=${ZELERDATA_DEVOLUCIONES_RANGE_START:-2026-06-01}" in wrapper
    assert "ACCEPTED_THROUGH=${ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH:-2026-07-09}" in wrapper
    assert 'CLOSED_DATE_TO=$(/usr/bin/date -u -d "yesterday" +%F)' in wrapper
    assert '"$RANGE_START" > "$ACCEPTED_THROUGH"' in wrapper
    assert '"$RANGE_START" > "$ACCEPTED_RANGE_START"' in wrapper
    assert '"$ACCEPTED_THROUGH" < "$ACCEPTED_BASELINE_THROUGH"' in wrapper
    assert '"$ACCEPTED_THROUGH" > "$CLOSED_DATE_TO"' in wrapper
    assert (
        '/usr/bin/docker compose --file "$COMPOSE_FILE" exec -T --workdir /app sheets-worker'
        in wrapper
    )
    assert "/app/.venv/bin/python" in wrapper
    assert "-m infra.operations.zelerdata_read_model_reconcile" in wrapper
    assert '--date-from "$RANGE_START"' in wrapper
    assert '--date-to "$CLOSED_DATE_TO"' in wrapper
    assert '--date-from "$CLOSED_DATE_TO"' not in wrapper
    assert "--write" in wrapper
    assert "--confirm-approved-runtime" in wrapper
    assert "--confirm-production-write" in wrapper
    assert "runtime_config_invalid" in wrapper
    assert "MAX_ATTEMPTS=2" in wrapper
    assert "/usr/bin/timeout --signal=TERM --kill-after=30s 3m" in wrapper
    assert "reconciliation_retry_scheduled" in wrapper
    assert "/usr/bin/sleep 60" in wrapper
    assert "reconciliation_failed" in wrapper
    assert "mktemp" in wrapper
    assert 'cat "$OUTPUT_FILE"' not in wrapper
    assert "uv run" not in wrapper
    assert "pip install" not in wrapper
    assert "python3" not in wrapper
    assert "/usr/bin/python" not in wrapper
    assert "set -x" not in wrapper


def test_reconciliation_service_has_canonical_runtime_and_failure_visibility() -> None:
    service = _read(RECONCILE_SERVICE)
    alert_service = _read(RECONCILE_ALERT_SERVICE)

    required = (
        "Requires=docker.service",
        "After=docker.service network-online.target",
        "OnFailure=zelerdata-devoluciones-reconcile-alert.service",
        "Type=oneshot",
        "WorkingDirectory=/opt/zeler-platform",
        "Environment=ZELERDATA_DEVOLUCIONES_SELLER_ID=82453304",
        "Environment=ZELERDATA_DEVOLUCIONES_RANGE_START=2026-06-01",
        "Environment=ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH=2026-07-09",
        "EnvironmentFile=-/etc/zeler-platform/zelerdata-devoluciones-reconcile.env",
        "ExecStart=/opt/zeler-platform/zelerdata-devoluciones-reconcile.sh",
        "TimeoutStartSec=8m",
        "Restart=no",
        "StandardOutput=journal",
        "StandardError=journal",
        "SyslogIdentifier=zelerdata-devoluciones-reconcile",
    )
    for snippet in required:
        assert snippet in service
    assert service.index("EnvironmentFile=") < service.index(
        "Environment=ZELERDATA_DEVOLUCIONES_SELLER_ID=82453304"
    )
    assert "ConditionPathExists" not in service
    assert "python" not in service.lower()
    assert "uv " not in service.lower()
    assert "Type=oneshot" in alert_service
    assert "/usr/bin/logger" in alert_service
    assert "daemon.err" in alert_service
    assert "DEVOLUCIONES_RECONCILIATION_FAILED" in alert_service
    assert "journalctl -u zelerdata-devoluciones-reconcile.service" in alert_service
    assert "ZELERDATA_DEVOLUCIONES_SELLER_ID" not in alert_service


def test_reconciliation_timer_is_randomized_persistent_and_not_self_enabling() -> None:
    timer = _read(RECONCILE_TIMER)

    assert "OnCalendar=*-*-* *:00,10,20,30,40,50:00 UTC" in timer
    assert "RandomizedDelaySec=1m" in timer
    assert "AccuracySec=30s" in timer
    assert "Persistent=true" in timer
    assert "Unit=zelerdata-devoluciones-reconcile.service" in timer
    assert "WantedBy=timers.target" in timer
    assert "enable" not in timer.lower()
    assert "systemctl start" not in timer.lower()


def test_startup_installs_exact_wrapper_and_units_without_enabling_timer_or_topology() -> None:
    startup = _read(STARTUP)
    wrapper = _read(RECONCILE_WRAPPER).strip()
    service = _read(RECONCILE_SERVICE).strip()
    timer = _read(RECONCILE_TIMER).strip()
    alert_service = _read(RECONCILE_ALERT_SERVICE).strip()
    topology_wrapper = _read(TOPOLOGY_WRAPPER).strip()

    assert topology_wrapper in startup
    assert wrapper in startup
    assert service in startup
    assert timer in startup
    assert alert_service in startup
    assert "chmod 0755 /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh" in startup
    assert "systemctl daemon-reload" in startup
    assert "systemctl enable --now zelerdata-devoluciones-reconcile.timer" not in startup
    assert "zelerdata-devoluciones-topology.sh prestart --execute" not in startup
    assert "zelerdata-devoluciones-topology.sh bind-claims --execute" not in startup


def test_reconcile_wrapper_rejects_environment_seller_override() -> None:
    wrapper = _read(RECONCILE_WRAPPER)

    assert "APPROVED_SELLER_ID=82453304" in wrapper
    assert '[[ "$CONFIGURED_SELLER_ID" != "$APPROVED_SELLER_ID" ]]' in wrapper
    assert "runtime_seller_invalid" in wrapper
    assert "SELLER_ID=$APPROVED_SELLER_ID" in wrapper


def test_deploy_runbook_orders_topology_acceptance_and_timer_activation() -> None:
    deploy = _read(DEPLOY_DOC)
    section = deploy.split(
        "## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation",
        1,
    )[1].split("---", 1)[0]

    required = (
        "/app/.venv/bin/python",
        "motor",
        "GET /post-purchase/v1/claims/search",
        "GET /post-purchase/v1/claims/*",
        "GET /post-purchase/v2/claims/*/returns",
        "GET /orders/*",
        "30-minute marker lease",
        "2026-06-01 through the previous closed UTC day",
        "every 10 minutes",
        "bounded retry",
        "OnFailure",
        "expected/persisted/complete/missing = 9/9/9/0",
        "OPERATOR_EVIDENCE_PENDING",
        "journalctl -u zelerdata-devoluciones-reconcile.service",
        "failure-conditional rollback",
        "systemctl enable --now zelerdata-devoluciones-reconcile.timer",
    )
    for snippet in required:
        assert snippet in section
    assert section.index("plan") < section.index("prestart --execute")
    assert section.index("prestart --execute") < section.index("bind-claims --execute")
    assert section.index("Acceptance gate") < section.index(
        "systemctl enable --now zelerdata-devoluciones-reconcile.timer"
    )
    assert "pip install" not in section
    assert "uv run" not in section
    assert "MONGO_URI=" not in section


def test_exact_merged_wu8_dry_run_reproduces_runtime_confirmation_rejection() -> None:
    args = build_reconciliation_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-07-09",
        ]
    )

    with pytest.raises(SystemExit, match="--confirm-approved-runtime is required"):
        build_reconciliation_request(args)


def test_deploy_runbook_dry_run_and_write_commands_confirm_runtime_exactly_once() -> None:
    deploy_section = (
        _read(DEPLOY_DOC)
        .split(
            "## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation",
            1,
        )[1]
        .split("---", 1)[0]
    )
    reconciliation_commands = tuple(
        block
        for block in _bash_blocks(deploy_section)
        if "infra.operations.zelerdata_read_model_reconcile" in block
    )

    assert len(reconciliation_commands) == 2
    dry_run, authorized_write = reconciliation_commands
    assert "--dry-run" in dry_run
    assert "--write" not in dry_run
    assert dry_run.count("--confirm-approved-runtime") == 1
    assert "--write" in authorized_write
    assert "--confirm-production-write" in authorized_write
    assert authorized_write.count("--confirm-approved-runtime") == 1


def test_deploy_runbook_records_the_wu8_gate_corrections() -> None:
    deploy_section = (
        _read(DEPLOY_DOC)
        .split(
            "## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation",
            1,
        )[1]
        .split("---", 1)[0]
    )
    normalized_section = " ".join(deploy_section.replace("> ", "").split())

    assert "WU8 rollout-gate correction" in normalized_section
    assert "rejected before reconciliation" in normalized_section
    assert "exactly one `--confirm-approved-runtime`" in normalized_section
    assert (
        "derives the database name from the default database in `MONGO_URI`" in normalized_section
    )
    assert "does not require a new secret or a manual host edit" in normalized_section
    assert "never prints the URI or derived database name" in normalized_section


def test_every_reviewed_operator_command_confirms_runtime_exactly_once() -> None:
    reconciliation_runbook = _read(RECONCILIATION_DOC)
    documented_commands = tuple(
        block
        for path in (DEPLOY_DOC, RECONCILIATION_DOC)
        for block in _bash_blocks(_read(path))
        if "infra.operations.zelerdata_read_model_reconcile" in block
    )
    wrapper_invocation = (
        _read(RECONCILE_WRAPPER)
        .split(
            "/app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile",
            1,
        )[1]
        .split('>"$OUTPUT_FILE"', 1)[0]
    )

    assert len(documented_commands) == 4
    assert all(command.count("--confirm-approved-runtime") == 1 for command in documented_commands)
    assert wrapper_invocation.count("--confirm-approved-runtime") == 1
    assert wrapper_invocation.count("--confirm-production-write") == 1
    assert "`--write --confirm-production-write`" not in reconciliation_runbook
    assert (
        "`--repair-observed-pause-basis --dry-run --confirm-approved-runtime`"
        in reconciliation_runbook
    )


def test_deploy_runbook_has_exact_non_activating_artifact_install_path() -> None:
    deploy = _read(DEPLOY_DOC)
    section = deploy.split(
        "## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation",
        1,
    )[1].split("---", 1)[0]

    assert "infra/gce/zelerdata-devoluciones-reconcile.sh" in section
    assert "infra/gce/systemd/zelerdata-devoluciones-reconcile.service" in section
    assert "infra/gce/systemd/zelerdata-devoluciones-reconcile.timer" in section
    assert "infra/gce/systemd/zelerdata-devoluciones-reconcile-alert.service" in section
    assert "sudo install -m 0755" in section
    assert "sudo install -m 0644" in section
    install_boundary = section.split("### Acceptance gate", 1)[0]
    assert "systemctl enable --now zelerdata-devoluciones-reconcile.timer" not in install_boundary


def test_zelerdata_docs_explain_joint_marker_operator_evidence_and_safe_rollback() -> None:
    reconciliation = _read(RECONCILIATION_DOC)
    formulas = _read(FORMULA_DOC)

    reconciliation_required = (
        "/app/.venv/bin/python",
        "30-minute marker lease",
        "one exact non-unioned `devoluciones` marker",
        "2026-06-01 through the previous closed UTC day",
        "must not shrink accepted coverage",
        "every 10 minutes",
        "OnFailure",
        "plan → prestart → worker health → bind-claims",
        "OPERATOR_EVIDENCE_PENDING",
        "failure-conditional rollback",
        "systemctl enable --now zelerdata-devoluciones-reconcile.timer",
    )
    formula_required = (
        "joint `devoluciones` marker",
        "30-minute lease",
        "requested half-open UTC range",
        "operator evidence",
        "request/correlation ID",
        "DATA_UNAVAILABLE",
        "expected/persisted/complete/missing = 9/9/9/0",
    )
    for snippet in reconciliation_required:
        assert snippet in reconciliation
    for snippet in formula_required:
        assert snippet in formulas
