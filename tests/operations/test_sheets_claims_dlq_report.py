from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
from infra.operations.sheets_claims_dlq_report import (
    DLQ_CLASSES,
    build_sheets_claims_dlq_report,
    main,
    seller_ref,
)


def _dlq_line(
    *,
    seller_id: int | str | None,
    dlq_class: str,
    resource_path: str = "/post-purchase/v1/claims/secret-id",
    event_id: str = "evt-secret",
) -> str:
    record: dict[str, object] = {
        "event": "worker.message.dlq",
        "attempts": 1,
        "error_type": "HTTPStatusError",
        "status_code": 404,
        "resource_path": resource_path,
        "event_id": event_id,
    }
    if seller_id is not None:
        record["seller_id"] = seller_id
    if dlq_class is not None:
        record["dlq_class"] = dlq_class
    return json.dumps(record)


def test_taxonomy_matches_design_contract() -> None:
    assert DLQ_CLASSES == (
        "attribution_missing",
        "http_4xx",
        "http_5xx",
        "deserialization",
        "claims_unbound",
        "transient_timeout",
    )


def test_seller_ref_hashes_and_prefixes() -> None:
    expected = "sha256:" + hashlib.sha256(b"123456789").hexdigest()
    assert seller_ref(123456789) == expected
    assert seller_ref("123456789") == expected


def test_report_aggregates_per_seller_counts_without_payload() -> None:
    ndjson = "\n".join(
        [
            _dlq_line(seller_id=111, dlq_class="http_4xx"),
            _dlq_line(seller_id=111, dlq_class="http_4xx"),
            _dlq_line(seller_id=222, dlq_class="transient_timeout"),
        ]
    )

    report = build_sheets_claims_dlq_report(ndjson)

    assert report["schema_version"] == 1
    assert report["scope"] == "sheets_claims_dlq"
    assert report["read_only"] is True
    assert report["lines_read"] == 3
    assert report["dlq_events"] == 3
    assert report["invalid_lines"] == 0
    assert report["sellers"] == {
        seller_ref(111): {"count": 2, "by_class": {"http_4xx": 2}},
        seller_ref(222): {"count": 1, "by_class": {"transient_timeout": 1}},
    }
    assert report["unattributable"] == {"count": 0, "by_class": {}}
    serialized = json.dumps(report)
    assert "123456789" not in serialized
    assert "secret-id" not in serialized
    assert "evt-secret" not in serialized
    assert "resource_path" not in serialized
    assert "event_id" not in serialized
    assert "error_type" not in serialized
    assert "status_code" not in serialized


def test_report_counts_unattributable_lines_without_payload() -> None:
    ndjson = "\n".join(
        [
            _dlq_line(seller_id=None, dlq_class="attribution_missing"),
            _dlq_line(seller_id=None, dlq_class="attribution_missing"),
        ]
    )

    report = build_sheets_claims_dlq_report(ndjson)

    assert report["dlq_events"] == 2
    assert report["sellers"] == {}
    assert report["unattributable"] == {
        "count": 2,
        "by_class": {"attribution_missing": 2},
    }


def test_report_buckets_unknown_classes_bounded() -> None:
    ndjson = _dlq_line(seller_id=333, dlq_class="bogus_class")

    report = build_sheets_claims_dlq_report(ndjson)

    assert report["sellers"][seller_ref(333)] == {
        "count": 1,
        "by_class": {"unknown": 1},
    }


def test_report_counts_invalid_and_skipped_lines() -> None:
    ndjson = "\n".join(
        [
            _dlq_line(seller_id=111, dlq_class="http_4xx"),
            "not-json-at-all",
            json.dumps({"event": "worker.message.requeued", "seller_id": 999}),
        ]
    )

    report = build_sheets_claims_dlq_report(ndjson)

    assert report["lines_read"] == 3
    assert report["dlq_events"] == 1
    assert report["invalid_lines"] == 1
    assert report["skipped_lines"] == 1
    assert report["sellers"] == {seller_ref(111): {"count": 1, "by_class": {"http_4xx": 1}}}


def test_report_empty_input_is_zero_aggregate() -> None:
    report = build_sheets_claims_dlq_report("")

    assert report["lines_read"] == 0
    assert report["dlq_events"] == 0
    assert report["sellers"] == {}
    assert report["unattributable"] == {"count": 0, "by_class": {}}
    assert report["invalid_lines"] == 0


def test_report_is_deterministic_and_sorted() -> None:
    ndjson = "\n".join(
        [
            _dlq_line(seller_id=222, dlq_class="http_5xx"),
            _dlq_line(seller_id=111, dlq_class="deserialization"),
        ]
    )

    first = json.dumps(build_sheets_claims_dlq_report(ndjson), sort_keys=True)
    second = json.dumps(build_sheets_claims_dlq_report(ndjson), sort_keys=True)

    assert first == second
    assert list(json.loads(first)["sellers"]) == sorted([seller_ref(111), seller_ref(222)])


def test_main_reads_ndjson_file_and_prints_only_counts(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path: pathlib.Path = tmp_path / "dlq.ndjson"
    input_path.write_text(
        "\n".join(
            [
                _dlq_line(seller_id=111, dlq_class="http_4xx"),
                _dlq_line(seller_id=111, dlq_class="attribution_missing"),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["--input", str(input_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    printed = json.loads(captured.out)
    assert printed["read_only"] is True
    assert printed["sellers"] == {
        seller_ref(111): {"count": 2, "by_class": {"http_4xx": 1, "attribution_missing": 1}}
    }
    assert "111" not in json.dumps(printed)
    assert "secret" not in json.dumps(printed).lower()


def test_main_fails_closed_on_missing_input(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing: pathlib.Path = tmp_path / "missing.ndjson"

    exit_code = main(["--input", str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 65
    printed = json.loads(captured.out)
    assert printed["status_class"] == "evidence_invalid"
    assert printed["read_only"] is True
