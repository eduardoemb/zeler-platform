from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import pathlib
from dataclasses import asdict
from types import SimpleNamespace
from typing import cast

import pytest
from infra.operations.sheets_dlq_reconcile import classify_and_sanitize_one
from infra.operations.sheets_dlq_snapshot_adapter import (
    AMQP_METADATA_ALLOWLIST,
    BUFFER_CAPACITY,
    SNAPSHOT_CAP,
    NackRequeueError,
    SnapshotAbortedError,
    SnapshotBroker,
    _build_parser,
    _run_snapshot,
    build_sanitized_report,
    build_snapshot_record,
    main,
)
from zeler_platform_test_support.sheets_dlq_snapshot import (
    FakeBroker,
    FakeRuntime,
    queue_state,
)

DLQ = "zeler.sheets.events.dlq"
ADAPTER_SOURCE = pathlib.Path("infra/operations/sheets_dlq_snapshot_adapter.py")
# Parser tests only; the path is never opened. S108 suppresses the tmp warning.
LOCK_PATH = "/tmp/snapshot.lock"  # noqa: S108


def _module_imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _body(index: int) -> bytes:
    return json.dumps({"message_id": f"msg-{index}"}).encode("utf-8")


def _delivery(*, tag: int = 7, body: bytes = b"{}", **metadata: object) -> SimpleNamespace:
    delivery = SimpleNamespace(delivery_tag=tag, body=body, headers={})
    for key, value in metadata.items():
        setattr(delivery, key, value)
    return delivery


def _runtime() -> FakeRuntime:
    return FakeRuntime(healthy=True)


def _wrap(broker: FakeBroker, lock_path: str) -> dict[str, list[dict[str, object]]]:
    return asyncio.run(
        _run_snapshot(
            broker=_as_broker(broker),
            runtime=_runtime(),
            queue_name=DLQ,
            lock_path=lock_path,
            offline_consumers=0,
            include_fingerprint=False,
            buffer_capacity=BUFFER_CAPACITY,
            snapshot_cap=SNAPSHOT_CAP,
        )
    )


def _as_broker(broker: FakeBroker) -> SnapshotBroker:
    """Cast a structurally-compatible test double to the narrow protocol."""
    return cast(SnapshotBroker, broker)


# --- 3.1 RED: parser contract -------------------------------------------------


def test_parser_requires_lock_path() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--queue", DLQ])


def test_parser_defaults_k_cap_and_fingerprint_absent() -> None:
    args = _build_parser().parse_args(["--lock-path", LOCK_PATH])
    assert args.buffer_capacity == 24
    assert args.snapshot_cap == 24
    assert args.offline_consumers == 0
    assert args.queue == DLQ
    assert args.payload_fingerprint_sha256 is False


def test_parser_accepts_explicit_caps() -> None:
    args = _build_parser().parse_args(
        ["--lock-path", LOCK_PATH, "--buffer-capacity", "10", "--snapshot-cap", "8"]
    )
    assert args.buffer_capacity == 10
    assert args.snapshot_cap == 8


def test_parser_enables_fingerprint_when_flag_passed() -> None:
    args = _build_parser().parse_args(["--lock-path", LOCK_PATH, "--payload-fingerprint-sha256"])
    assert args.payload_fingerprint_sha256 is True


def test_main_requires_lock_path() -> None:
    with pytest.raises(SystemExit):
        main([], broker=_as_broker(FakeBroker(states={})), runtime=_runtime())


def test_main_refuses_live_execution_without_injected_ports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--lock-path", LOCK_PATH])
    err = capsys.readouterr().err
    assert excinfo.value.code == 2
    assert "author" in err.lower()


# --- 3.2 RED: SnapshotRecord + sanitized report + import boundary --------------


def test_snapshot_record_emits_only_allowlisted_metadata_and_no_raw_payload() -> None:
    delivery = _delivery(
        body=b'{"api_key":"RAW-SECRET"}',
        content_type="application/json",
        delivery_mode="persistent",
        exchange="meli.events",
        routing_key="zeler.sheets.events.dlq",
        extra={"internal": "secret"},
    )

    record = build_snapshot_record(sequence=1, delivery=delivery, nack_outcome="requeue_requested")

    assert record.sequence == 1
    assert record.nack_outcome == "requeue_requested"
    assert record.payload_fingerprint is None
    assert set(record.metadata) == AMQP_METADATA_ALLOWLIST
    assert record.metadata["routing_key"] == "zeler.sheets.events.dlq"
    serialized = json.dumps(asdict(record), sort_keys=True)
    assert "RAW-SECRET" not in serialized
    assert "extra" not in serialized


def test_snapshot_record_metadata_drops_non_allowlisted_keys() -> None:
    delivery = _delivery(
        body=b"{}",
        content_type="text/plain",
        oauth_token="LEAK",  # noqa: S106
        raw_uri="https://secret",
    )
    record = build_snapshot_record(sequence=2, delivery=delivery, nack_outcome="outcome_unknown")
    assert set(record.metadata) == {"content_type"}
    serialized = json.dumps(asdict(record), sort_keys=True)
    assert "LEAK" not in serialized
    assert "https://secret" not in serialized


def test_fingerprint_absent_by_default() -> None:
    record = build_snapshot_record(
        sequence=1, delivery=_delivery(body=b"{}"), nack_outcome="requeue_requested"
    )
    assert record.payload_fingerprint is None


def test_fingerprint_is_deterministic_sha256_when_enabled() -> None:
    delivery = _delivery(body=b"{}")
    first = build_snapshot_record(
        sequence=1, delivery=delivery, nack_outcome="requeue_requested", include_fingerprint=True
    )
    second = build_snapshot_record(
        sequence=1, delivery=delivery, nack_outcome="requeue_requested", include_fingerprint=True
    )
    expected = hashlib.sha256(b"{}").hexdigest()
    assert first.payload_fingerprint == expected
    assert second.payload_fingerprint == expected


def test_report_contains_only_sequence_metadata_fingerprint_outcome() -> None:
    records = [
        build_snapshot_record(
            sequence=1, delivery=_delivery(tag=5, body=b"{}"), nack_outcome="requeue_requested"
        ),
        build_snapshot_record(
            sequence=2, delivery=_delivery(tag=6, body=b"{}"), nack_outcome="requeue_requested"
        ),
    ]

    report = build_sanitized_report(records)

    assert list(report) == ["records"]
    assert len(report["records"]) == 2
    first = report["records"][0]
    assert set(first) == {
        "sequence",
        "metadata",
        "payload_fingerprint",
        "classification",
        "nack_outcome",
    }
    assert "delivery_tag" not in first
    serialized = json.dumps(report, sort_keys=True)
    assert "RAW-SECRET" not in serialized
    assert "message_id" not in serialized


def test_adapter_has_no_telemetry_debug_or_subprocess_imports() -> None:
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
    imported = _module_imported_names(source)
    assert not imported.intersection(
        {"opentelemetry", "sentry_sdk", "pdb", "debugpy", "subprocess"}
    )


# --- 3.3/3.5 GREEN verification: wiring, emit after close, inactive entrypoint --


def test_snapshot_wiring_emits_sanitized_report_after_close(tmp_path: pathlib.Path) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=2)},
        messages={DLQ: [_body(1), _body(2)]},
    )
    report = _wrap(broker, str(tmp_path / "snapshot.lock"))

    assert "channel_close" in broker.calls
    assert len(report["records"]) == 2
    assert [record["nack_outcome"] for record in report["records"]] == [
        "requeue_requested",
        "requeue_requested",
    ]
    assert [record["sequence"] for record in report["records"]] == [1, 2]


def test_report_emitted_after_close_contains_no_raw_values(tmp_path: pathlib.Path) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=2)},
        messages={DLQ: [_body(7), _body(8)]},
    )
    report = _wrap(broker, str(tmp_path / "snapshot.lock"))

    serialized = json.dumps(report, sort_keys=True)
    assert "message_id" not in serialized
    assert "msg-7" not in serialized
    assert "msg-8" not in serialized


def test_main_emits_sanitized_report_after_run(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=2)},
        messages={DLQ: [_body(1), _body(2)]},
    )
    rc = main(
        ["--lock-path", str(tmp_path / "snapshot.lock")],
        broker=_as_broker(broker),
        runtime=_runtime(),
    )
    out = capsys.readouterr().out

    assert rc == 0
    report = json.loads(out)
    assert len(report["records"]) == 2
    assert all(
        set(record)
        == {"sequence", "metadata", "payload_fingerprint", "classification", "nack_outcome"}
        for record in report["records"]
    )


def test_main_output_has_no_confirmation_or_raw_values(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=1)},
        messages={DLQ: [_body(3)]},
    )
    main(
        ["--lock-path", str(tmp_path / "snapshot.lock")],
        broker=_as_broker(broker),
        runtime=_runtime(),
    )
    out = capsys.readouterr().out

    lowered = out.lower()
    assert "confirm" not in lowered
    assert "requeued" not in lowered
    assert "message_id" not in out
    assert "msg-3" not in out


# --- 3.4 RED: contract — forbidden actions/Mongo, sanitized errors -------------


def test_adapter_source_exposes_no_forbidden_action_or_mongo() -> None:
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
    imported = _module_imported_names(source)
    assert not imported.intersection({"motor", "pymongo"})

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in {
                "ack",
                "publish",
                "publish_confirmed",
                "declare_queue",
                "delete_queue",
                "quarantine",
                "disposition",
                "replay",
            }

    members = {name for name in dir(SnapshotBroker) if not name.startswith("__")}
    assert {"inspect_queue", "get_one", "nack_requeue", "close_channel"} <= members


def test_abort_error_message_contains_no_raw_payload(tmp_path: pathlib.Path) -> None:
    class SecretNackBroker(FakeBroker):
        def __init__(self) -> None:
            super().__init__(states={DLQ: queue_state(ready=1)}, messages={DLQ: [_body(1)]})

        async def nack_requeue(self, delivery: object) -> None:
            raise NackRequeueError("RAW-SECRET nack local failure")

    broker = SecretNackBroker()

    with pytest.raises(SnapshotAbortedError) as excinfo:
        _wrap(broker, str(tmp_path / "snapshot.lock"))

    assert "message_id" not in str(excinfo.value)
    assert "RAW-SECRET" not in str(excinfo.value)
    assert "channel_close" in broker.calls


def test_report_never_mentions_completion_proof(tmp_path: pathlib.Path) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=1)},
        messages={DLQ: [_body(1)]},
    )
    report = _wrap(broker, str(tmp_path / "snapshot.lock"))

    serialized = json.dumps(report, sort_keys=True).lower()
    assert "completion" not in serialized
    assert "proof" not in serialized


# --- CV.1 remediation RED: adapter must compose the canonical classifier -------


def test_adapter_composes_canonical_classifier_for_acquired_delivery(
    tmp_path: pathlib.Path,
) -> None:
    raw = json.dumps({"idempotency_key": "kp-1", "seller_id": 82453304}).encode("utf-8")
    broker = FakeBroker(
        states={DLQ: queue_state(ready=1)},
        messages={DLQ: [raw]},
    )
    report = _wrap(broker, str(tmp_path / "snapshot.lock"))

    record = report["records"][0]
    # Composition: the emitted taxonomy must equal the canonical wrapper's output
    # for the same raw message with the adapter's no-in-process-evidence mapping.
    expected = classify_and_sanitize_one(json.loads(raw), {})
    assert record["classification"] == expected
    assert record["classification"]["classification"] == "unknown_append_outcome"
    assert record["classification"]["reason_code"] == "replay_prerequisites_missing"
    assert record["classification"]["evidence_source"] is None

    serialized = json.dumps(report, sort_keys=True)
    assert "kp-1" not in serialized
    assert "82453304" not in serialized


def test_adapter_classifies_each_acquired_delivery_and_emits_only_sanitized_values(
    tmp_path: pathlib.Path,
) -> None:
    raws = [
        {"idempotency_key": "alpha-1", "seller_id": 111},
        {"idempotency_key": "beta-2", "seller_id": 222},
    ]
    broker = FakeBroker(
        states={DLQ: queue_state(ready=2)},
        messages={DLQ: [json.dumps(raw).encode("utf-8") for raw in raws]},
    )
    report = _wrap(broker, str(tmp_path / "snapshot.lock"))

    assert len(report["records"]) == 2
    for record, raw in zip(report["records"], raws, strict=True):
        assert record["classification"] == classify_and_sanitize_one(raw, {})

    serialized = json.dumps(report, sort_keys=True)
    assert "alpha-1" not in serialized
    assert "beta-2" not in serialized
    assert "111" not in serialized
    assert "222" not in serialized
