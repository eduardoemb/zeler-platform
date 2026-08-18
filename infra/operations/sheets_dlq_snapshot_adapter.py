"""Bounded R1 snapshot adapter core for the Sheets DLQ.

Inactive-by-default. The coordinator acquires at most ``SNAPSHOT_CAP`` distinct
deliveries while they remain unacked, then nacks them in ascending
delivery-tag order. The broker surface is deliberately narrow (inspect, get,
nack, close) so no ack, publish, topology, purge, delete, quarantine, or
disposition capability exists. Same-host exclusion uses a non-blocking
``fcntl.flock`` on an operator-supplied path. Preflight fails closed and no
Mongo write capability is exposed.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import signal
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

from infra.operations.sheets_dlq_reconcile import classify_and_sanitize_one

BUFFER_CAPACITY = 24
SNAPSHOT_CAP = 24
DLQ_QUEUE_NAME = "zeler.sheets.events.dlq"

# Closed set of AMQP delivery metadata the sanitized report may carry. All
# other fields (raw payloads, ids, credentials, URIs, headers) never cross the
# report boundary.
AMQP_METADATA_ALLOWLIST = frozenset({"content_type", "delivery_mode", "exchange", "routing_key"})

STATE_INIT = "INIT"
STATE_LOCKED = "LOCKED"
STATE_PREFLIGHTED = "PREFLIGHTED"
STATE_ACQUIRING = "ACQUIRING"
STATE_DRAINING = "DRAINING"
STATE_ABORTING = "ABORTING"
STATE_CLOSED = "CLOSED"
STATE_FINISHED = "FINISHED"
STATE_COMPLETE = "COMPLETE"
STATE_FAILED = "FAILED"

OUTCOME_REQUEUE_REQUESTED = "requeue_requested"
OUTCOME_REQUEUE_SEND_FAILED = "requeue_send_failed"
OUTCOME_UNKNOWN = "outcome_unknown"


class SnapshotDelivery(Protocol):
    """Minimal unacked delivery surface (delivery tag lives in memory only)."""

    delivery_tag: int
    body: bytes


class QueueInspection(Protocol):
    """Structural readiness observations used by the preflight."""

    ready: int
    unacked: int
    consumers: int


class SnapshotBroker(Protocol):
    """Narrow broker surface: inspection plus no-ack get/nack/close only."""

    async def inspect_queue(
        self, queue_name: str, *, timeout: float | None = None
    ) -> QueueInspection | None: ...

    async def get_one(self, queue_name: str) -> SnapshotDelivery | None: ...

    async def nack_requeue(self, delivery: SnapshotDelivery) -> None: ...

    async def close_channel(self) -> None: ...


class WorkerRuntime(Protocol):
    """Read-only Sheets worker health probe used by the preflight."""

    async def worker_is_healthy(self) -> bool: ...


class PreflightError(RuntimeError):
    """One or more preflight gates failed; the run is rejected."""


class SameHostExclusionError(RuntimeError):
    """Another process holds the same-host snapshot lock."""


class NackRequeueError(RuntimeError):
    """A requeue nack could not be sent (definite local send failure)."""


class BrokerChannelLostError(RuntimeError):
    """Transport loss or ambiguous send; the requeue outcome is unknown."""


class SnapshotAbortedError(RuntimeError):
    """The bounded drain aborted after an unsatisfactory requeue outcome."""


def _acquire_flock(lock_path: str) -> BinaryIO:
    """Open the operator-supplied path and take a non-blocking exclusive flock."""
    handle = Path(lock_path).open("a+b")  # noqa: SIM115 - handle must stay open for lock lifetime
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise SameHostExclusionError(str(exc)) from None
    return handle


def _release_flock(handle: BinaryIO) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def same_host_exclusion(lock_path: str) -> Iterator[None]:
    """Acquire a non-blocking ``fcntl.flock`` on the operator-supplied path.

    No additional path form, permission, file-type, symlink, or parent-creation
    policy is invented: the caller supplies the exact path. ``LOCK_NB`` makes
    a contended lock fail closed immediately.
    """
    with Path(lock_path).open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SameHostExclusionError(str(exc)) from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def install_signal_handlers(cancel: Callable[[], None]) -> tuple[signal.Signals, ...]:
    """Route SIGINT/SIGTERM to cancellation; abrupt death emits no proof."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda _signum, _frame: cancel())
    return (signal.SIGINT, signal.SIGTERM)


def completion_proof(state: str) -> str | None:
    """Return a completion proof only for an orderly ``STATE_COMPLETE`` run."""
    if state == STATE_COMPLETE:
        return "run reached COMPLETE; channel closed; unacked auto-requeue expected"
    return None


async def run_preflight(
    *,
    broker: SnapshotBroker,
    runtime: WorkerRuntime,
    queue_name: str,
    offline_consumers: int = 0,
) -> None:
    """Fail closed unless consumers are zero, the worker is healthy, no Mongo.

    ``offline_consumers`` is an operator-supplied observation from the offline
    inspection of the DLQ; the live queue inspection must also report zero
    consumers. There is no Mongo client or write path in this module, so the
    Mongo-write gate is structurally satisfied.
    """
    if offline_consumers != 0:
        raise PreflightError(f"offline consumer count != 0: {offline_consumers}")
    live = await broker.inspect_queue(queue_name)
    if live is None:
        raise PreflightError("live queue inspection returned no consumer proof")
    if live.consumers != 0:
        raise PreflightError(f"live consumer count != 0: {live.consumers}")
    if not await runtime.worker_is_healthy():
        raise PreflightError("sheets worker runtime is unhealthy")


class SnapshotCoordinator:
    """State-machine coordinator for the bounded snapshot run.

    State flow: INIT -> LOCKED -> PREFLIGHTED -> ACQUIRING -> DRAINING ->
    CLOSED -> COMPLETE. Any handled failure drives ABORTING -> CLOSED -> FAILED
    and raises; the channel is closed so unacked deliveries auto-requeue.
    """

    def __init__(
        self,
        *,
        broker: SnapshotBroker,
        buffer_capacity: int = BUFFER_CAPACITY,
        snapshot_cap: int = SNAPSHOT_CAP,
    ) -> None:
        self._broker = broker
        self._buffer_capacity = buffer_capacity
        self._snapshot_cap = snapshot_cap
        self.state = STATE_INIT
        self.outcomes: list[str] = []

    async def acquire(
        self,
        queue_name: str,
        on_acquire: Callable[[SnapshotDelivery], None] | None = None,
    ) -> list[SnapshotDelivery]:
        """Acquire and retain unacked deliveries up to the snapshot cap."""
        self.state = STATE_ACQUIRING
        buffered: list[SnapshotDelivery] = []
        while len(buffered) < self._snapshot_cap:
            delivery = await self._broker.get_one(queue_name)
            if delivery is None:
                break
            buffered.append(delivery)
            if on_acquire is not None:
                on_acquire(delivery)
            if len(buffered) >= self._buffer_capacity:
                break
        return buffered

    async def drain(self, buffered: list[SnapshotDelivery]) -> list[str]:
        """Nack in ascending tag order, recording honest outcomes.

        Each nack returns ``requeue_requested`` only when the send returned
        cleanly (never a broker confirmation claim). A definite local send
        failure records ``requeue_send_failed``; transport loss or an ambiguous
        send records ``outcome_unknown``. Any unsatisfactory outcome closes the
        channel, records no further gets/nacks, and aborts via
        :class:`SnapshotAbortedError`.
        """
        self.state = STATE_DRAINING
        self.outcomes = []
        aborted = False
        for item in sorted(buffered, key=lambda item: item.delivery_tag):
            if aborted:
                break
            try:
                await self._broker.nack_requeue(item)
            except BrokerChannelLostError:
                self.outcomes.append(OUTCOME_UNKNOWN)
                aborted = True
                break
            except NackRequeueError:
                self.outcomes.append(OUTCOME_REQUEUE_SEND_FAILED)
                aborted = True
                break
            except Exception:  # noqa: BLE001 - ambiguous send must map to outcome_unknown.
                # Ambiguous failure: treat as a lost/unknown outcome and abort.
                # Any unexpected nack failure must still map to an honest outcome.
                self.outcomes.append(OUTCOME_UNKNOWN)
                aborted = True
                break
            self.outcomes.append(OUTCOME_REQUEUE_REQUESTED)
        if aborted:
            await self._best_effort_close()
            self.state = STATE_ABORTING
            raise SnapshotAbortedError("bounded drain aborted on requeue failure")
        return self.outcomes

    async def _best_effort_close(self) -> None:
        try:
            await self._broker.close_channel()
        except Exception:  # noqa: BLE001 - close must never mask the original failure.
            self.state = STATE_ABORTING

    async def _close_after_run(self) -> None:
        await self._broker.close_channel()
        self.state = STATE_CLOSED

    async def run(
        self,
        *,
        queue_name: str,
        lock_path: str,
        runtime: WorkerRuntime,
        offline_consumers: int = 0,
        on_acquire: Callable[[SnapshotDelivery], None] | None = None,
    ) -> list[str]:
        """Run preflight, acquire, ordered drain, and close.

        On cancellation or a handled exception the channel is closed best-effort
        so unacked deliveries auto-requeue; the run never claims completion or
        proof. Hard process death (SIGKILL, OOM, segfault) cannot run this
        cleanup and emits no completion claim.
        """
        if not lock_path:
            raise SameHostExclusionError("--lock-path is required")
        handle = _acquire_flock(lock_path)
        self.state = STATE_LOCKED
        try:
            await run_preflight(
                broker=self._broker,
                runtime=runtime,
                queue_name=queue_name,
                offline_consumers=offline_consumers,
            )
            self.state = STATE_PREFLIGHTED
            buffered = await self.acquire(queue_name, on_acquire=on_acquire)
            outcomes = await self.drain(buffered)
            await self._close_after_run()
            self.state = STATE_COMPLETE
            return outcomes
        except asyncio.CancelledError:
            await self._best_effort_close()
            self.state = STATE_FAILED
            raise
        except SnapshotAbortedError:
            await self._best_effort_close()
            self.state = STATE_FAILED
            raise
        except Exception:
            await self._best_effort_close()
            self.state = STATE_FAILED
            raise
        finally:
            _release_flock(handle)


# ---------------------------------------------------------------------------
# SnapshotRecord + sanitized report (PR3)
# ---------------------------------------------------------------------------

_MISSING = object()


@dataclass(frozen=True)
class SnapshotRecord:
    """One sanitized audit line: sequence, allowlisted metadata, fingerprint.

    Delivery tags and raw bodies never cross this boundary; they remain only in
    the bounded in-memory buffer.
    """

    sequence: int
    metadata: dict[str, object] = field(default_factory=dict)
    payload_fingerprint: str | None = None
    classification: dict[str, str | None] = field(default_factory=dict)
    nack_outcome: str = ""


def _delivery_metadata(delivery: object) -> dict[str, object]:
    """Return only allowlisted AMQP metadata taken from a delivery."""
    result: dict[str, object] = {}
    for key in AMQP_METADATA_ALLOWLIST:
        value = getattr(delivery, key, _MISSING)
        if value is not _MISSING:
            result[key] = value
    return result


def _classify_delivery(delivery: object) -> dict[str, str | None]:
    """Compose the canonical classifier and sanitize one delivery body.

    Delegates to ``classify_and_sanitize_one`` so the four-class taxonomy
    cannot drift from the reconciler. The adapter holds no in-process evidence,
    so an empty mapping preserves the fail-closed unknown classification. Only
    the three allowlisted verdict fields are returned; the decoded local view
    dies on return so raw fields never reach the report.
    """
    body = getattr(delivery, "body", None)
    if not isinstance(body, bytes):
        raise TypeError("delivery body must be bytes for classification")
    try:
        message = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise TypeError("delivery body is not valid JSON") from exc
    if not isinstance(message, Mapping):
        raise TypeError("delivery body must decode to a JSON object for classification")
    return classify_and_sanitize_one(message, {})


def build_snapshot_record(
    *,
    sequence: int,
    delivery: object,
    nack_outcome: str,
    include_fingerprint: bool = False,
) -> SnapshotRecord:
    """Build a sanitized record: metadata, optional fingerprint, classification."""
    metadata = _delivery_metadata(delivery)
    fingerprint: str | None = None
    if include_fingerprint:
        body = getattr(delivery, "body", None)
        if not isinstance(body, bytes):
            raise TypeError("delivery body must be bytes for payload fingerprinting")
        fingerprint = hashlib.sha256(body).hexdigest()
    return SnapshotRecord(
        sequence=sequence,
        metadata=metadata,
        payload_fingerprint=fingerprint,
        classification=_classify_delivery(delivery),
        nack_outcome=nack_outcome,
    )


def build_sanitized_report(records: Sequence[SnapshotRecord]) -> dict[str, list[dict[str, object]]]:
    """Serialize sanitized records only; raw fields never appear."""
    return {
        "records": [
            {
                "sequence": record.sequence,
                "metadata": dict(record.metadata),
                "payload_fingerprint": record.payload_fingerprint,
                "classification": dict(record.classification),
                "nack_outcome": record.nack_outcome,
            }
            for record in records
        ]
    }


async def _run_snapshot(
    *,
    broker: SnapshotBroker,
    runtime: WorkerRuntime,
    queue_name: str,
    lock_path: str,
    offline_consumers: int,
    include_fingerprint: bool,
    buffer_capacity: int,
    snapshot_cap: int,
) -> dict[str, list[dict[str, object]]]:
    """Wire lock -> offline -> preflight -> acquire -> drain -> close -> emit.

    Records are built from each acquired delivery (allowlisted metadata plus
    optional fingerprint) and paired with the honest nack outcome in ascending
    delivery-tag order. On any abort the coordinator closes the channel and
    raises, so no report is emitted.
    """
    coordinator = SnapshotCoordinator(
        broker=broker,
        buffer_capacity=buffer_capacity,
        snapshot_cap=snapshot_cap,
    )
    captured: list[tuple[int, object]] = []

    def on_acquire(delivery: SnapshotDelivery) -> None:
        captured.append((delivery.delivery_tag, delivery))

    outcomes = await coordinator.run(
        queue_name=queue_name,
        lock_path=lock_path,
        runtime=runtime,
        offline_consumers=offline_consumers,
        on_acquire=on_acquire,
    )
    deliveries_by_tag = [delivery for _, delivery in sorted(captured, key=lambda pair: pair[0])]
    records = [
        build_snapshot_record(
            sequence=sequence,
            delivery=delivery,
            nack_outcome=outcome,
            include_fingerprint=include_fingerprint,
        )
        for sequence, (delivery, outcome) in enumerate(
            zip(deliveries_by_tag, outcomes, strict=True), start=1
        )
    ]
    return build_sanitized_report(records)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded R1 snapshot of distinct current Sheets DLQ messages. "
            "Inactive by default: live broker execution requires injected ports "
            "under separate authorization. Launches no shell or subprocess."
        )
    )
    parser.add_argument("--lock-path", required=True, help="Same-host flock path")
    parser.add_argument("--queue", default=DLQ_QUEUE_NAME, help="DLQ queue name")
    parser.add_argument("--offline-consumers", type=int, default=0, help="Offline consumer count")
    parser.add_argument(
        "--buffer-capacity", type=int, default=BUFFER_CAPACITY, help="In-memory buffer cap (K)"
    )
    parser.add_argument(
        "--snapshot-cap",
        type=int,
        default=SNAPSHOT_CAP,
        help="Distinct snapshot cap",
    )
    parser.add_argument(
        "--payload-fingerprint-sha256",
        action="store_true",
        default=False,
        help="Include deterministic sha256 fingerprint of each raw body",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    broker: SnapshotBroker | None = None,
    runtime: WorkerRuntime | None = None,
) -> int:
    """Inactive-by-default CLI: never dials a broker without injected ports.

    Without ``broker``/``runtime`` the CLI refuses to execute and contacts no
    live broker or Mongo. Structured execution is only reachable through the
    explicitly injected ports under separate authorization.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if broker is None or runtime is None:
        parser.error("live broker execution requires injected ports under separate authorization")
    report = asyncio.run(
        _run_snapshot(
            broker=broker,
            runtime=runtime,
            queue_name=args.queue,
            lock_path=args.lock_path,
            offline_consumers=args.offline_consumers,
            include_fingerprint=args.payload_fingerprint_sha256,
            buffer_capacity=args.buffer_capacity,
            snapshot_cap=args.snapshot_cap,
        )
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
