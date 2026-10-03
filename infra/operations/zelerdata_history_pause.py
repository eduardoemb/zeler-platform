"""Manual, TERM-only Docker pause; root operator only. No cloud or DB access.

Docker 29.4.1 killWithSignal records manual stop and returns after signal delivery.
Never uses the uncancellable timed-stop endpoint. An application that never
finishes cannot be forcibly recovered under this contract: report pending, retain
its recovery guard, and do not claim either quiescence or restored availability.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TextIO, cast

Record = dict[str, Any]


class PauseDriver(Protocol):
    def inspect(self, container: str) -> Record: ...
    def target(self, container: str, role: str) -> Record: ...
    def term(self, container: str) -> None: ...
    def child_term(self, container: str, target: Record) -> None: ...
    def api_shutdown_complete(self, record: Record) -> bool: ...
    def start(self, container: str) -> None: ...
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


IMAGES = {
    "sheets-api": "sha256:a9d33c3fcb428bb8502feba4b7a05084a08eeb4fa097069c6de40daafae1f72b",
    "sheets-worker": "sha256:b0925d9251d1b34080435caa6f6f2224ce32e5842fbac626fc45224bb1a8bb66",
    "bootstrap-dispatcher": (
        "sha256:9806539f22deb96ab533a1684d9d4f9376bdccc924a941d6597d1d03ecb26f0b"
    ),
}
# Authenticated source-manifest/config pairs. Docker29 containerd image store and
# classic image store expose different .Image IDs for the same immutable content.
CONFIG_IDS = {
    "sheets-api": "sha256:f3dce59352c049ea3f95ad8be13d571b4cddd4e74c81e67b2bbc1c795952f164",
    "sheets-worker": "sha256:e2347b0f1d6125ea529a3fa20eef3c7268ae22dceb478cfa3ced11ae0a24f340",
    "bootstrap-dispatcher": (
        "sha256:24fe23e54ee78eaba139b28b9fc480134330678505d35f5901f4afa0774a4e8d"
    ),
}

PYTHON = "/app/.venv/bin/python"


class SafetyError(RuntimeError):
    """Safe, fixed-code failure; never expose subprocess output."""


def configuration_hash(state: Record) -> str:
    config = state["Config"]
    selected = {key: config.get(key) for key in ("Cmd", "Entrypoint", "StopSignal", "Healthcheck")}
    selected["RestartPolicy"] = state["HostConfig"]["RestartPolicy"]
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def verify(state: Record, record: Record, *, generation: bool = False) -> None:
    if state["Id"] != record["id"] or state["Image"] != record["image"]:
        raise SafetyError("identity_changed")
    if configuration_hash(state) != record["configuration_hash"]:
        raise SafetyError("config_changed")
    current = state["State"]
    if current.get("OOMKilled") or current.get("Restarting") or current.get("Paused"):
        raise SafetyError("container_state")
    if generation and (
        current["StartedAt"] != record["started_at"]
        or state["RestartCount"] != record["restart_count"]
    ):
        raise SafetyError("generation_changed")


def capture(driver: PauseDriver, container: str, role: str) -> Record:
    if role not in IMAGES:
        raise SafetyError("role_not_allowed")
    state = driver.inspect(container)
    if state["Image"] not in (IMAGES[role], CONFIG_IDS[role]) or not state["State"]["Running"]:
        raise SafetyError("preflight_image_or_running")
    if state["HostConfig"]["RestartPolicy"]["Name"] != "unless-stopped":
        raise SafetyError("preflight_restart_policy")
    if state["Config"].get("StopSignal", "") not in (None, "", "SIGTERM", "15"):
        raise SafetyError("preflight_stop_signal")
    record = dict(
        id=state["Id"],
        image=state["Image"],
        role=role,
        started_at=state["State"]["StartedAt"],
        restart_count=state["RestartCount"],
        configuration_hash=configuration_hash(state),
        target=driver.target(state["Id"], role),
        marked=False,
        stopped=False,
        resumed=False,
    )
    verify(state, record, generation=True)
    return record


def pause(
    driver: PauseDriver,
    record: Record,
    *,
    timeout: float = 90,
    settle: float = 3,
    save: Callable[[], None] = lambda: None,
) -> None:
    verify(driver.inspect(record["id"]), record, generation=True)
    record["marked"] = True
    save()  # Recovery knows this target even if delivery confirmation is lost.
    driver.term(record["id"])  # Docker manual stop bookkeeping BEFORE child TERM.
    state = driver.inspect(record["id"])
    verify(state, record, generation=True)
    if record["role"] == "sheets-api" and state["State"]["Running"]:
        driver.child_term(record["id"], record["target"])
    deadline = driver.now() + timeout
    while True:
        state = driver.inspect(record["id"])
        verify(state, record, generation=True)
        if not state["State"]["Running"]:
            exit_code = state["State"]["ExitCode"]
            if exit_code != 0:
                if not (
                    record["role"] == "sheets-api"
                    and exit_code == 143
                    and driver.api_shutdown_complete(record)
                ):
                    raise SafetyError("nonzero_graceful_exit")
                # The log sentinel belongs to the same unchanged container generation.
                verify(driver.inspect(record["id"]), record, generation=True)
            record["stopped"] = True
            save()
            break
        if driver.now() >= deadline:
            raise SafetyError("grace_exhausted")
        driver.sleep(0.25)
    end = driver.now() + settle
    while driver.now() < end:
        state = driver.inspect(record["id"])
        verify(state, record, generation=True)
        if state["State"]["Running"]:
            raise SafetyError("unexpected_start")
        driver.sleep(0.25)


def resume(
    driver: PauseDriver,
    record: Record,
    *,
    timeout: float = 120,
    save: Callable[[], None] = lambda: None,
) -> bool:
    if not record["marked"] or record["resumed"]:
        return True
    deadline = driver.now() + timeout
    while True:
        state = driver.inspect(record["id"])
        verify(state, record, generation=True)
        if not state["State"]["Running"]:
            driver.start(record["id"])
            current = driver.inspect(record["id"])
            verify(current, record)
            if not current["State"]["Running"]:
                raise SafetyError("resume_not_running")
            record["resumed"] = True
            record["resume_started_at"] = current["State"]["StartedAt"]
            save()
            return True  # Root separately validates health/consumers/leases/backlog.
        if driver.now() >= deadline:
            return False  # TERM still draining: never start/replace a running instance.
        driver.sleep(0.25)


def rfc3339_nanoseconds(value: str) -> int | None:
    """Parse Docker RFC3339Nano exactly, including on host Python3.10.

    datetime sees only whole aware seconds; all 1–9 fractional digits remain
    integer nanoseconds, never float or truncated microseconds.
    """
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})",
        value,
    )
    if match is None:
        return None
    whole, fraction, zone = match.groups()
    try:
        observed = datetime.fromisoformat(whole + ("+00:00" if zone == "Z" else zone))
        epoch = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
        delta = observed - epoch
    except ValueError:
        return None
    seconds = delta.days * 86400 + delta.seconds
    return seconds * 1_000_000_000 + int((fraction or "0").ljust(9, "0"))


def api_shutdown_complete(logs: str, pid: int, started_at: str) -> bool:
    """Reduce private timestamped logs to one boolean; never persist/emit logs."""
    start = rfc3339_nanoseconds(started_at)
    if start is None:
        return False
    complete = None
    for line in logs.splitlines():
        timestamp, _, message = line.partition(" ")
        observed = rfc3339_nanoseconds(timestamp)
        if observed is None or observed < start:
            continue
        if re.fullmatch(r"INFO:\s+Application shutdown complete\.", message):
            complete = observed
        elif (
            complete is not None
            and observed >= complete
            and re.fullmatch(rf"INFO:\s+Finished server process \[{pid}\]", message)
        ):
            return True
    return False


PROC = r"""
import json,os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TextIO, cast

Record = dict[str, Any]


class PauseDriver(Protocol):
    def inspect(self, container: str) -> Record: ...
    def target(self, container: str, role: str) -> Record: ...
    def term(self, container: str) -> None: ...
    def child_term(self, container: str, target: Record) -> None: ...
    def start(self, container: str) -> None: ...
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
rows=[]
for p in Path('/proc').iterdir():
 if not p.name.isdecimal(): continue
 try:
  fields=(p/'stat').read_text().rsplit(')',1)[1].split()
  cmd=(p/'cmdline').read_bytes().split(b'\0'); role=os.sys.argv[1]
  pid=int(p.name); ppid=int(fields[1]); ticks=fields[19]
  shell=cmd[0].split(b'/')[-1] in (b'sh',b'bash')
  python=b'python' in cmd[0]
  if role=='sheets-api':
   match=b'zeler_sheets.app:make_app' in cmd and any(b'uvicorn' in a for a in cmd)
  else:
   expected=b'zeler_sheets' if role=='sheets-worker' else b'zeler_bootstrap.dispatcher_worker'
   match=python and expected in cmd
  if role=='sheets-api' and pid==1 and shell: rows.append({'parent_shell':True})
  if match and ((role=='sheets-api' and ppid==1) or (role!='sheets-api' and pid==1)):
   rows.append({'pid':pid,'start_ticks':ticks,'role':role})
 except (OSError,IndexError,ValueError): continue
parents=[r for r in rows if r.get('parent_shell')]; targets=[r for r in rows if 'pid' in r]
if len(targets)!=1 or (role=='sheets-api' and len(parents)!=1): raise SystemExit(4)
print(json.dumps(targets[0]))
"""
CHILD_TERM = r"""
import json,os,signal,sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TextIO, cast

Record = dict[str, Any]


class PauseDriver(Protocol):
    def inspect(self, container: str) -> Record: ...
    def target(self, container: str, role: str) -> Record: ...
    def term(self, container: str) -> None: ...
    def child_term(self, container: str, target: Record) -> None: ...
    def start(self, container: str) -> None: ...
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
target=json.loads(sys.argv[1]); p=Path('/proc')/str(target['pid'])
fields=(p/'stat').read_text().rsplit(')',1)[1].split(); cmd=(p/'cmdline').read_bytes().split(b'\0')
if fields[19]!=target['start_ticks'] or int(fields[1])!=1: raise SystemExit(4)
if b'zeler_sheets.app:make_app' not in cmd: raise SystemExit(4)
if not any(b'uvicorn' in a for a in cmd): raise SystemExit(4)
os.kill(target['pid'],signal.SIGTERM)
"""
INSPECT = (
    '{"Id":{{json .Id}},"Image":{{json .Image}},"RestartCount":{{json .RestartCount}},'
    '"Config":{"Cmd":{{json .Config.Cmd}},"Entrypoint":{{json .Config.Entrypoint}},'
    '"StopSignal":{{json (index .Config "StopSignal")}},'
    '"Healthcheck":{{json (index .Config "Healthcheck")}}},'
    '"HostConfig":{"RestartPolicy":{{json .HostConfig.RestartPolicy}}},'
    '"State":{"Running":{{json .State.Running}},"Restarting":{{json .State.Restarting}},'
    '"Paused":{{json .State.Paused}},"OOMKilled":{{json .State.OOMKilled}},'
    '"StartedAt":{{json .State.StartedAt}},"ExitCode":{{json .State.ExitCode}}}}'
)


class Docker:
    @staticmethod
    def run(args: list[str]) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed Docker executable and argv, no shell.
                args, capture_output=True, timeout=15, check=False
            )
        except (subprocess.TimeoutExpired, OSError):
            raise SafetyError("docker_rpc_unconfirmed") from None
        if completed.returncode:
            raise SafetyError("docker_rpc_failed")
        return completed.stdout.decode()

    def inspect(self, container: str) -> Record:
        return cast(
            Record, json.loads(self.run(["docker", "inspect", "--format", INSPECT, container]))
        )

    def target(self, container: str, role: str) -> Record:
        return cast(
            Record, json.loads(self.run(["docker", "exec", container, PYTHON, "-c", PROC, role]))
        )

    def term(self, container: str) -> None:
        self.run(["docker", "kill", "--signal=TERM", container])

    def child_term(self, container: str, target: Record) -> None:
        self.run(["docker", "exec", container, PYTHON, "-c", CHILD_TERM, json.dumps(target)])

    def api_shutdown_complete(self, record: Record) -> bool:
        # Uvicorn gracefully shuts down, then re-emits TERM: shell exit143 is
        # accepted ONLY with both sentinels for the recorded PID/generation.
        args = [
            "docker",
            "logs",
            "--timestamps",
            "--since",
            record["started_at"],
            "--tail=1000",
            record["id"],
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell.
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            raise SafetyError("shutdown_log_rpc_unconfirmed") from None
        if completed.returncode:
            raise SafetyError("shutdown_log_rpc_failed")
        return api_shutdown_complete(
            completed.stdout.decode(errors="replace"),
            record["target"]["pid"],
            record["started_at"],
        )

    def start(self, container: str) -> None:
        self.run(["docker", "start", container])

    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def save_state(path: Path, records: list[Record]) -> None:
    temporary = path.with_suffix(".writing")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(records, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def guard(
    driver: PauseDriver,
    load: Callable[[], list[Record]],
    save: Callable[[], None],
    *,
    arm_seconds: float = 600,
    recover_seconds: float = 150,
    prepare_recovery: Callable[[], None] = lambda: None,
) -> bool:
    """Re-read journal until recovery deadline; never mark a hung target recovered."""
    arm_deadline = driver.now() + arm_seconds
    while driver.now() < arm_deadline:
        records = load()
        if any(r["marked"] for r in records) and all(
            not r["marked"] or r["resumed"] for r in records
        ):
            return True
        driver.sleep(0.5)
    prepare_recovery()  # CLI serializes main/guard recovery before refreshing journal.
    records = load()
    recovery_deadline = driver.now() + recover_seconds
    pending = list(reversed(records))
    while pending and driver.now() < recovery_deadline:
        pending = [r for r in pending if not resume(driver, r, timeout=0.5, save=save)]
    return not pending


def guard_arm_seconds(arguments: list[str]) -> float:
    """Reserve recovery margin inside the 15-minute cut; allow shorter rehearsal."""
    if not arguments:
        return 600
    try:
        value = float(arguments[0])
    except ValueError:
        raise SafetyError("guard_arm_budget") from None
    if len(arguments) != 1 or not 0 < value <= 720:
        raise SafetyError("guard_arm_budget")
    return value


def main() -> None:
    # Stdin supplies containers ONLY for capture. No implicit production names.
    action, filename = sys.argv[1:3]
    path = Path(filename)
    driver = Docker()
    if action == "capture":
        if path.exists():
            raise SafetyError("journal_exists")
        containers = json.load(sys.stdin)
        if set(containers) != set(IMAGES):
            raise SafetyError("exact_three_roles_required")
        version = driver.run(["docker", "version", "--format", "{{.Server.Version}}"]).strip()
        if version != "29.4.1":
            raise SafetyError("daemon_version_not_rehearsed")
        records = [
            capture(driver, containers[role], role)
            for role in ("bootstrap-dispatcher", "sheets-api", "sheets-worker")
        ]
        save_state(path, records)
    else:
        lock_stream: TextIO | None = None

        def lock() -> None:
            nonlocal lock_stream
            fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            lock_stream = os.fdopen(fd, "w")
            until = driver.now() + 15
            while True:
                try:
                    fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except BlockingIOError:
                    if driver.now() >= until:
                        raise SafetyError("recovery_operator_lock_pending") from None
                    driver.sleep(0.25)

        if action != "guard":
            lock()
        records = json.loads(path.read_text())

        def save() -> None:
            save_state(path, records)

        if action == "guard":

            def load() -> list[Record]:
                nonlocal records
                records = json.loads(path.read_text())
                return cast(list[Record], records)

            if not guard(
                driver,
                load,
                save,
                prepare_recovery=lock,
                arm_seconds=guard_arm_seconds(sys.argv[3:]),
            ):
                raise SafetyError("recovery_pending_application_drain")
        elif action == "pause":
            try:
                for record in records:
                    pause(driver, record, save=save)
            except BaseException:
                # Caller MUST run recovery until every marked target is resumed.
                # This bounded attempt never claims success for a draining process.
                for record in reversed(records):
                    resume(driver, record, timeout=10, save=save)
                raise
        elif action == "resume":
            deadline = driver.now() + 120
            pending = list(reversed(records))
            while pending and driver.now() < deadline:
                pending = [
                    record for record in pending if not resume(driver, record, timeout=1, save=save)
                ]
            if pending:
                raise SafetyError("recovery_pending_application_drain")
        else:
            raise SafetyError("action_not_allowed")
    print(
        json.dumps(
            {
                "action": action,
                "targets": len(records),
                "stopped": sum(bool(r["stopped"]) for r in records),
                "resumed": sum(bool(r["resumed"]) for r in records),
                "no_timed_stop_requests": True,
                "health_verified": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except SafetyError as exc:
        print(json.dumps({"ok": False, "code": str(exc), "no_timed_stop_requests": True}))
        raise SystemExit(1) from None
