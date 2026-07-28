from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from infra.operations.zelerdata_campaign_state import (
    CampaignStateError,
    CampaignStateStore,
    require_accepted_campaign,
)
from infra.operations.zelerdata_read_model_reconcile import (
    build_arg_parser as build_reconciliation_arg_parser,
)
from infra.operations.zelerdata_read_model_reconcile import (
    build_reconciliation_request,
)
from infra.rabbitmq.sheets_devoluciones_topology import _build_parser

ROOT = Path(__file__).resolve().parents[1]
SHEETS_PYPROJECT = ROOT / "modules" / "sheets" / "pyproject.toml"
SHEETS_API_DOCKERFILE = ROOT / "modules" / "sheets" / "Dockerfile.api"
SHEETS_WORKER_DOCKERFILE = ROOT / "modules" / "sheets" / "Dockerfile.worker"
STARTUP = ROOT / "infra" / "gce" / "platform-vm-startup.sh"
RECONCILE_WRAPPER = ROOT / "infra" / "gce" / "zelerdata-devoluciones-reconcile.sh"
TIMER_ENABLE_WRAPPER = ROOT / "infra" / "gce" / "zelerdata-devoluciones-enable-timer.sh"
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


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _scheduled_transport() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "public": {
                "stage": "write_readback",
                "status_class": "success",
                "counters": {
                    "expected": 9,
                    "persisted": 9,
                    "complete": 9,
                    "missing": 0,
                    "P": 4,
                    "R": 8,
                    "O": 4,
                    "T": 16,
                },
            },
            "private_campaign": {
                "campaign_id": "campaign-generated-001",
                "outcome": "success",
                "campaign_disqualified": False,
                "duration_seconds": 100.25,
                "source_fingerprint_hash": "a" * 64,
                "read_model_fingerprint_hash": "b" * 64,
            },
        },
        sort_keys=True,
    )


def _scheduled_wrapper_test_env(
    *, tmp_path: Path, output: str, status: int
) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    logger_file = tmp_path / "journald.log"
    campaign_state_file = tmp_path / "campaign-state.json"
    mktemp_count_file = tmp_path / "mktemp-count"
    epoch_file = tmp_path / "epoch"
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    date_bin = _write_executable(
        bin_dir / "date",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"+%s"* ]]; then
  if [[ -f "{epoch_file}" ]]; then
    echo 110
  else
    : > "{epoch_file}"
    echo 100
  fi
elif [[ "$*" == *"yesterday"* ]]; then
  echo 2026-07-10
else
  for value in "$@"; do
    if [[ "$value" =~ ^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$ ]]; then
      echo "$value"
      exit 0
    fi
  done
  exit 1
fi
""",
    )
    docker_bin = _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$FAKE_DOCKER_OUTPUT"
exit "$FAKE_DOCKER_STATUS"
""",
    )
    timeout_bin = _write_executable(
        bin_dir / "timeout",
        """#!/usr/bin/env bash
set -euo pipefail
shift 3
exec "$@"
""",
    )
    logger_bin = _write_executable(
        bin_dir / "logger",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_LOGGER_FAIL:-0}" == "1" ]]; then
  exit 72
fi
printf '%s\n' "$*" >> "$FAKE_LOGGER_FILE"
""",
    )
    mktemp_bin = _write_executable(
        bin_dir / "mktemp",
        f"""#!/usr/bin/env bash
set -euo pipefail
count=0
if [[ -f "{mktemp_count_file}" ]]; then
  count=$(cat "{mktemp_count_file}")
fi
count=$((count + 1))
printf '%s' "$count" > "{mktemp_count_file}"
if [[ "${{FAKE_MKTEMP_FAIL_AT:-0}}" == "$count" ]]; then
  exit 73
fi
TMPDIR="$TMPDIR" /usr/bin/mktemp
""",
    )
    python_bin = _write_executable(
        bin_dir / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"zelerdata_scheduled_evidence"* && "${FAKE_PARSER_FAIL:-0}" == "1" ]]; then
  exit 65
fi
if [[ "$*" == *"zelerdata_campaign_state"* && "${FAKE_STATE_WRITER_FAIL:-0}" == "1" ]]; then
  exit 70
fi
exec /usr/bin/python3 "$@"
""",
    )
    return (
        {
            **os.environ,
            "TMPDIR": str(output_dir),
            "ZELER_PLATFORM_ROOT": str(ROOT),
            "ZELER_COMPOSE_FILE": str(compose_file),
            "ZELERDATA_DEVOLUCIONES_SELLER_ID": "82453304",
            "ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID": "campaign-generated-001",
            "ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE": str(campaign_state_file),
            "ZELER_DATE_BIN": str(date_bin),
            "ZELER_DOCKER_BIN": str(docker_bin),
            "ZELER_TIMEOUT_BIN": str(timeout_bin),
            "ZELER_LOGGER_BIN": str(logger_bin),
            "ZELER_MKTEMP_BIN": str(mktemp_bin),
            "ZELER_PYTHON_BIN": str(python_bin),
            "ZELER_RM_BIN": "/bin/rm",
            "FAKE_DOCKER_OUTPUT": output,
            "FAKE_DOCKER_STATUS": str(status),
            "FAKE_LOGGER_FILE": str(logger_file),
            "FAKE_LOGGER_FAIL": "0",
            "FAKE_MKTEMP_FAIL_AT": "0",
            "FAKE_PARSER_FAIL": "0",
            "FAKE_STATE_WRITER_FAIL": "0",
        },
        output_dir,
        logger_file,
    )


def _accept_scheduled_campaign(state_file: Path) -> None:
    store = CampaignStateStore(state_file)
    for _ in range(20):
        store.record(
            {
                "campaign_id": "campaign-generated-001",
                "outcome": "success",
                "duration_seconds": 100.0,
                "source_fingerprint_hash": "a" * 64,
                "read_model_fingerprint_hash": "b" * 64,
                "campaign_disqualified": False,
            }
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


def test_sheets_api_packages_topology_and_proves_frozen_import_without_execution() -> None:
    dockerfile = _read(SHEETS_API_DOCKERFILE)

    required_stanzas = (
        "COPY pyproject.toml uv.lock ./",
        "COPY core ./core",
        "COPY infra/operations ./infra/operations",
        "COPY infra/rabbitmq ./infra/rabbitmq",
        "COPY modules/sheets ./modules/sheets",
        "RUN uv sync --frozen --package zeler-sheets --no-dev",
        "RUN test -x .venv/bin/python",
        'RUN .venv/bin/python -c "import motor.motor_asyncio; '
        'import infra.rabbitmq.sheets_devoluciones_topology"',
        "USER appuser",
        'CMD ["sh", "-c", ".venv/bin/uvicorn zeler_sheets.app:make_app '
        '--factory --host 0.0.0.0 --port ${PORT:-8080}"]',
    )
    positions = tuple(dockerfile.index(stanza) for stanza in required_stanzas)

    assert positions == tuple(sorted(positions))
    assert "HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3" in dockerfile
    runtime_stanza = dockerfile.split("USER appuser", 1)[1]
    assert "pip install" not in runtime_stanza
    assert "uv sync" not in runtime_stanza
    assert "-m infra.rabbitmq.sheets_devoluciones_topology" not in dockerfile
    assert "/var/run/docker.sock" not in dockerfile
    assert "--privileged" not in dockerfile


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
    assert 'CLOSED_DATE_TO=$("$DATE_BIN" -u -d "yesterday" +%F)' in wrapper
    assert '"$RANGE_START" > "$ACCEPTED_THROUGH"' in wrapper
    assert '"$RANGE_START" > "$ACCEPTED_RANGE_START"' in wrapper
    assert '"$ACCEPTED_THROUGH" < "$ACCEPTED_BASELINE_THROUGH"' in wrapper
    assert '"$ACCEPTED_THROUGH" > "$CLOSED_DATE_TO"' in wrapper
    assert '"$DOCKER_BIN" compose --file "$COMPOSE_FILE" exec -T --workdir /app' in wrapper
    assert "/app/.venv/bin/python" in wrapper
    assert "-m infra.operations.zelerdata_read_model_reconcile" in wrapper
    assert '--date-from "$RANGE_START"' in wrapper
    assert '--date-to "$CLOSED_DATE_TO"' in wrapper
    assert '--date-from "$CLOSED_DATE_TO"' not in wrapper
    assert "--write" in wrapper
    assert "--confirm-approved-runtime" in wrapper
    assert "--confirm-production-write" in wrapper
    assert "runtime_config_invalid" in wrapper
    assert "MAX_ATTEMPTS" not in wrapper
    assert '"$TIMEOUT_BIN" --signal=TERM --kill-after=30s 175s' in wrapper
    assert wrapper.count('"$TIMEOUT_BIN"') == 1
    assert wrapper.count("infra.operations.zelerdata_read_model_reconcile") == 1
    assert "--read-model devoluciones" in wrapper
    assert "CAMPAIGN_ID=${ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID:-}" in wrapper
    assert "FINAL_STATUS_CLASS=evidence_invalid" in wrapper
    assert '--env "ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID=$CAMPAIGN_ID"' in wrapper
    assert "--private-scheduled-transport" in wrapper
    assert "--private-output" in wrapper
    assert "reconciliation_retry_scheduled" not in wrapper
    assert "/usr/bin/sleep" not in wrapper
    assert "reconciliation_failed" in wrapper
    assert "mktemp" in wrapper
    assert 'cat "$OUTPUT_FILE"' not in wrapper
    assert "uv run" not in wrapper
    assert "pip install" not in wrapper
    assert "infra.operations.zelerdata_scheduled_evidence" in wrapper
    assert "PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}" in wrapper
    assert "set -x" not in wrapper


@pytest.mark.parametrize(
    ("process_status", "raw_output", "expected_returncode", "status_class"),
    [
        (0, _scheduled_transport(), 0, "success"),
        (42, "TOP_SECRET_SENTINEL RAW_PII_SENTINEL", 42, "process_failed"),
        (124, "", 124, "timeout"),
        (7, "ARBITRARY_RAW_FAILURE", 7, "process_failed"),
        (0, "TOP_SECRET_SENTINEL malformed", 65, "evidence_invalid"),
    ],
)
def test_scheduled_wrapper_publishes_allowlisted_evidence_before_cleanup(
    tmp_path: Path,
    process_status: int,
    raw_output: str,
    expected_returncode: int,
    status_class: str,
) -> None:
    env, output_dir, logger_file = _scheduled_wrapper_test_env(
        tmp_path=tmp_path,
        output=raw_output,
        status=process_status,
    )

    completed = subprocess.run(  # noqa: S603 - executes repository-owned wrapper.
        ["/bin/bash", str(RECONCILE_WRAPPER)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == expected_returncode
    evidence_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(evidence_lines) == 1
    evidence = json.loads(evidence_lines[0])
    assert set(evidence) == {"stage", "status_class", "counters"}
    assert evidence["stage"] == "scheduled"
    assert evidence["status_class"] == status_class
    if status_class == "success":
        assert evidence["counters"] == {
            "O": 4,
            "P": 4,
            "R": 8,
            "T": 16,
            "complete": 9,
            "expected": 9,
            "missing": 0,
            "persisted": 9,
        }
    else:
        assert evidence["counters"] == {}
    for forbidden in ("campaign", "duration", "fingerprint", "hash", "reason", "outcome"):
        assert forbidden not in evidence_lines[0]
    assert "TOP_SECRET_SENTINEL" not in completed.stdout + completed.stderr
    assert "RAW_PII_SENTINEL" not in completed.stdout + completed.stderr
    journal = logger_file.read_text(encoding="utf-8")
    assert evidence_lines[0] in journal
    assert "TOP_SECRET_SENTINEL" not in journal
    assert "RAW_PII_SENTINEL" not in journal
    assert list(output_dir.iterdir()) == []
    campaign_state = json.loads(
        Path(env["ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE"]).read_text(encoding="utf-8")
    )
    if status_class != "success":
        assert "campaign-generated-001" in campaign_state["disqualified_campaign_ids"]
    else:
        assert len(campaign_state["campaigns"]["campaign-generated-001"]["durations"]) == 1


@pytest.mark.parametrize(
    ("mutation", "status_class"),
    [
        ({"ZELERDATA_DEVOLUCIONES_SELLER_ID": "wrong"}, "evidence_invalid"),
        ({"ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID": "invalid campaign"}, "evidence_invalid"),
        ({"ZELER_COMPOSE_FILE": "/missing/docker-compose.yml"}, "process_failed"),
    ],
)
def test_scheduled_wrapper_central_exit_emits_exactly_one_early_failure_record(
    tmp_path: Path,
    mutation: dict[str, str],
    status_class: str,
) -> None:
    env, output_dir, logger_file = _scheduled_wrapper_test_env(
        tmp_path=tmp_path,
        output="TOP_SECRET_SENTINEL",
        status=0,
    )
    env.update(mutation)

    completed = subprocess.run(  # noqa: S603 - executes repository-owned wrapper.
        ["/bin/bash", str(RECONCILE_WRAPPER)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert completed.returncode != 0
    assert len(records) == 1
    assert set(records[0]) == {"stage", "status_class", "counters"}
    assert records[0] == {"stage": "scheduled", "status_class": status_class, "counters": {}}
    assert "TOP_SECRET_SENTINEL" not in completed.stdout + completed.stderr
    assert logger_file.read_text(encoding="utf-8").count("event=scheduled_run evidence=") == 1
    assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "expected_exit", "status_class"),
    [
        ({"FAKE_MKTEMP_FAIL_AT": "1"}, 73, "tooling_failed"),
        ({"FAKE_PARSER_FAIL": "1"}, 65, "evidence_invalid"),
        ({"FAKE_LOGGER_FAIL": "1"}, 72, "publication_failed"),
        ({"FAKE_STATE_WRITER_FAIL": "1"}, 70, "state_failed"),
    ],
)
def test_scheduled_wrapper_tooling_failures_emit_one_minimal_disqualification(
    tmp_path: Path,
    mutation: dict[str, str],
    expected_exit: int,
    status_class: str,
) -> None:
    env, output_dir, _ = _scheduled_wrapper_test_env(
        tmp_path=tmp_path,
        output="TOP_SECRET_RAW_OUTPUT",
        status=0,
    )
    env.update(mutation)
    env["TOP_SECRET_RAW_ENV"] = "DO_NOT_PRINT_ME"  # noqa: S105 - leak sentinel, not a secret.

    completed = subprocess.run(  # noqa: S603 - repository-owned wrapper.
        ["/bin/bash", str(RECONCILE_WRAPPER)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert completed.returncode == expected_exit
    assert len(records) == 1
    assert records[0] == {"stage": "scheduled", "status_class": status_class, "counters": {}}
    assert "TOP_SECRET_RAW_OUTPUT" not in completed.stdout + completed.stderr
    assert "DO_NOT_PRINT_ME" not in completed.stdout + completed.stderr
    assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "expected_exit", "status_class"),
    [
        ({"FAKE_LOGGER_FAIL": "1"}, 72, "publication_failed"),
        ({"FAKE_MKTEMP_FAIL_AT": "1"}, 73, "tooling_failed"),
    ],
)
def test_scheduled_wrapper_failure_revokes_previously_accepted_campaign(
    tmp_path: Path,
    mutation: dict[str, str],
    expected_exit: int,
    status_class: str,
) -> None:
    env, output_dir, _ = _scheduled_wrapper_test_env(
        tmp_path=tmp_path,
        output=_scheduled_transport(),
        status=0,
    )
    env.update(mutation)
    state_file = Path(env["ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE"])
    _accept_scheduled_campaign(state_file)

    completed = subprocess.run(  # noqa: S603 - repository-owned wrapper.
        ["/bin/bash", str(RECONCILE_WRAPPER)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert completed.returncode == expected_exit
    assert records == [{"stage": "scheduled", "status_class": status_class, "counters": {}}]
    assert all(
        private_field not in completed.stdout + completed.stderr
        for private_field in ("campaign", "duration", "fingerprint", "outcome")
    )
    state = CampaignStateStore(state_file).load()
    assert state.accepted_campaign_id is None
    assert state.disqualified_campaign_ids == frozenset({"campaign-generated-001"})
    assert "campaign-generated-001" not in state.campaigns
    with pytest.raises(CampaignStateError, match="campaign is not accepted"):
        require_accepted_campaign(
            state_file,
            expected_campaign_id="campaign-generated-001",
            expected_source_fingerprint_hash="a" * 64,
            expected_read_model_fingerprint_hash="b" * 64,
        )
    assert list(output_dir.iterdir()) == []


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


def test_timer_enablement_requires_durable_accepted_campaign(tmp_path: Path) -> None:
    state_file = tmp_path / "campaign.json"
    systemctl_log = tmp_path / "systemctl.log"
    systemctl = _write_executable(
        tmp_path / "systemctl",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "show" ]]; then
  printf '%s\n' "${SERVICE_ENVIRONMENT:-}"
  exit 0
fi
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
""",
    )
    base_env = {
        **os.environ,
        "ZELER_PLATFORM_ROOT": str(ROOT),
        "ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE": str(state_file),
        "ZELER_SYSTEMCTL_BIN": str(systemctl),
        "SYSTEMCTL_LOG": str(systemctl_log),
        "SERVICE_ENVIRONMENT": "",
    }

    rejected = subprocess.run(  # noqa: S603 - repository-owned timer gate.
        ["/bin/bash", str(TIMER_ENABLE_WRAPPER)],
        cwd=ROOT,
        env=base_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert not systemctl_log.exists()

    store = CampaignStateStore(state_file)
    for _ in range(20):
        store.record(
            {
                "campaign_id": "campaign-a",
                "outcome": "success",
                "duration_seconds": 100.0,
                "source_fingerprint_hash": "a" * 64,
                "read_model_fingerprint_hash": "b" * 64,
                "campaign_disqualified": False,
            }
        )
    accepted_environment = (
        "ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID=campaign-a "
        f"ZELERDATA_DEVOLUCIONES_SOURCE_FINGERPRINT_HASH={'a' * 64} "
        f"ZELERDATA_DEVOLUCIONES_READ_MODEL_FINGERPRINT_HASH={'b' * 64}"
    )
    mismatch_env = {
        **base_env,
        "SERVICE_ENVIRONMENT": accepted_environment.replace("campaign-a", "campaign-b"),
    }
    mismatch = subprocess.run(  # noqa: S603 - repository-owned timer gate.
        ["/bin/bash", str(TIMER_ENABLE_WRAPPER)],
        cwd=ROOT,
        env=mismatch_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatch.returncode != 0
    assert not systemctl_log.exists()

    base_env["SERVICE_ENVIRONMENT"] = accepted_environment
    accepted = subprocess.run(  # noqa: S603 - repository-owned timer gate.
        ["/bin/bash", str(TIMER_ENABLE_WRAPPER)],
        cwd=ROOT,
        env=base_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0
    assert systemctl_log.read_text(encoding="utf-8").strip() == (
        "enable --now zelerdata-devoluciones-reconcile.timer"
    )

    restarted = subprocess.run(  # noqa: S603 - proves durable state survives process restart.
        ["/bin/bash", str(TIMER_ENABLE_WRAPPER)],
        cwd=ROOT,
        env=base_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert restarted.returncode == 0
    assert systemctl_log.read_text(encoding="utf-8").count("enable --now") == 2


def test_startup_installs_exact_wrapper_and_units_without_enabling_timer_or_topology() -> None:
    startup = _read(STARTUP)
    service = _read(RECONCILE_SERVICE).strip()
    timer = _read(RECONCILE_TIMER).strip()
    alert_service = _read(RECONCILE_ALERT_SERVICE).strip()
    topology_wrapper = _read(TOPOLOGY_WRAPPER).strip()

    assert topology_wrapper in startup
    assert "cat > /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh" not in startup
    assert "cat > /dev/null << 'SCRIPT'" not in startup
    assert '"event":"zelerdata_devoluciones_scheduled_run"' not in startup
    encoded_wrapper = re.search(r"RECONCILE_WRAPPER_B64='([^']+)'", startup)
    assert encoded_wrapper is not None
    assert (
        base64.b64decode(encoded_wrapper.group(1)).decode().strip()
        == _read(RECONCILE_WRAPPER).strip()
    )
    assert service in startup
    assert timer in startup
    assert alert_service in startup
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
        "single scheduled attempt",
        "OnFailure",
        "expected/persisted/complete/missing = 9/9/9/0",
        "OPERATOR_EVIDENCE_PENDING",
        "journalctl -u zelerdata-devoluciones-reconcile.service",
        "failure-conditional rollback",
        "zelerdata-devoluciones-enable-timer.sh",
    )
    for snippet in required:
        assert snippet in section
    assert section.index("plan") < section.index("prestart --execute")
    assert section.index("prestart --execute") < section.index("bind-claims --execute")
    assert section.index("Acceptance gate") < section.rindex(
        "zelerdata-devoluciones-enable-timer.sh"
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
    assert "infra/gce/zelerdata-devoluciones-enable-timer.sh" in section
    assert "infra/gce/sheets-rollback-execute.sh" in section
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
        "zelerdata-devoluciones-enable-timer.sh",
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


def test_reconciliation_runbook_documents_focused_budget_campaign_and_safe_api_rollback() -> None:
    reconciliation = _read(RECONCILIATION_DOC)

    required = (
        "--read-model devoluciones",
        "claims-first immutable snapshot",
        "broad order-date, questions, items, shipments, and catalog hydration is prohibited",
        "B = P + 3H",
        "B ≤ 104",
        "C ≤ 208",
        "1.25-second minimum start-to-start interval",
        "physical RETURNS attempts only",
        "one pacer spans both snapshots",
        "429 remains terminal",
        "does not retry",
        "at most 41.25 seconds per snapshot and 83.75 seconds per run",
        "110-second projected run envelope",
        "55 seconds of process-deadline margin",
        "165-second process deadline",
        "175-second shell stop",
        "20 consecutive",
        "nearest-rank p95",
        "every run must remain below 180 seconds",
        "p95 must remain below 150 seconds",
        "exact 11 scopes and 5 routing keys",
        "retain the corrected candidate API",
        "rollback-compatible API image",
        "old 8/4 writer is prohibited",
        "keep the Sheets API unavailable",
        "SHEETS_ROLLBACK_PREFLIGHT=1",
        "sanitized evidence",
        "Enable scheduling last",
        "single scheduled attempt",
        "cannot reset either snapshot or run accounting",
        "explicit campaign ID",
        "Cloud Build SLSA provenance",
        "Repository JSON alone is not authority",
        "unknown digest fails closed",
        "registry fingerprint before healthy",
        "startup-installed preflight is parity-bound",
        "private campaign sample",
        "success-only source/read-model fingerprint hashes",
        "stage`, `status_class`, and `counters",
        "arbitrary nonzero values remain authoritative",
        "evidence_invalid",
        "all temporary files are removed after state handling and publication",
        "zelerdata-devoluciones-campaign.json",
        "A→B→A",
        "gcloud artifacts docker images describe",
        "--show-provenance",
        "gcloud builds describe",
        "zeler_sheets.app:make_app --factory",
        "sheets-rollback-execute.sh",
        "RepoDigest",
    )
    for snippet in required:
        assert snippet in reconciliation
