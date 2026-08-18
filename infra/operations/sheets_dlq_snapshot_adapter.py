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

import asyncio
import fcntl
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol

BUFFER_CAPACITY = 24
SNAPSHOT_CAP = 24

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

    async def acquire(self, queue_name: str) -> list[SnapshotDelivery]:
        """Acquire and retain unacked deliveries up to the snapshot cap."""
        self.state = STATE_ACQUIRING
        buffered: list[SnapshotDelivery] = []
        while len(buffered) < self._snapshot_cap:
            delivery = await self._broker.get_one(queue_name)
            if delivery is None:
                break
            buffered.append(delivery)
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
            buffered = await self.acquire(queue_name)
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
