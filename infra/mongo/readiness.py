from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pymongo import MongoClient

Severity = Literal["pass", "fail"]


@dataclass(frozen=True)
class MongoReadinessFinding:
    severity: Severity
    resource_type: Literal["schema", "index", "collection"]
    resource_name: str
    detail: str


@dataclass(frozen=True)
class MongoReadinessReport:
    mode: Literal["offline", "read-only-live-check"]
    safe_to_execute: bool
    read_only: bool
    live_target_checked: bool
    mutations_attempted: int
    summary: dict[str, int]
    findings: tuple[MongoReadinessFinding, ...]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_files(schemas_dir: Path) -> list[Path]:
    return sorted(schemas_dir.glob("*.json"))


def _index_files(indexes_dir: Path) -> list[Path]:
    return sorted(indexes_dir.glob("*.json")) if indexes_dir.exists() else []


def _validate_schema_files(schemas_dir: Path) -> tuple[dict[str, int], list[MongoReadinessFinding]]:
    findings: list[MongoReadinessFinding] = []
    schema_files = _schema_files(schemas_dir)
    errors = 0
    active = 0
    for schema_path in schema_files:
        try:
            loaded = _load_json(schema_path)
            if not isinstance(loaded, dict):
                raise ValueError("schema file must contain a JSON object")
            json_schema = loaded.get("$jsonSchema", loaded)
            if not isinstance(json_schema, dict):
                raise ValueError("$jsonSchema must be a JSON object")
            if json_schema:
                active += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors += 1
            findings.append(
                MongoReadinessFinding(
                    severity="fail",
                    resource_type="schema",
                    resource_name=schema_path.name,
                    detail=str(exc),
                )
            )
    return (
        {
            "schema_files": len(schema_files),
            "active_schema_files": active,
            "schema_file_errors": errors,
        },
        findings,
    )


def _validate_index_files(indexes_dir: Path) -> tuple[dict[str, int], list[MongoReadinessFinding]]:
    findings: list[MongoReadinessFinding] = []
    index_files = _index_files(indexes_dir)
    errors = 0
    index_count = 0
    for index_path in index_files:
        try:
            loaded = _load_json(index_path)
            if not isinstance(loaded, list):
                raise ValueError("index file must contain a JSON array")
            for index_definition in loaded:
                if not isinstance(index_definition, dict):
                    raise ValueError("index definition must be a JSON object")
                if not isinstance(index_definition.get("keys"), dict):
                    raise ValueError("index definition requires object keys")
                if not isinstance(index_definition.get("options", {}), dict):
                    raise ValueError("index definition options must be an object")
            index_count += len(loaded)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors += 1
            findings.append(
                MongoReadinessFinding(
                    severity="fail",
                    resource_type="index",
                    resource_name=index_path.name,
                    detail=str(exc),
                )
            )
    return (
        {
            "index_files": len(index_files),
            "index_definitions": index_count,
            "index_file_errors": errors,
        },
        findings,
    )


def _live_read_only_findings(
    *,
    mongo_uri: str,
    schemas_dir: Path,
    indexes_dir: Path,
) -> tuple[dict[str, int], list[MongoReadinessFinding]]:
    client: MongoClient[dict[str, Any]] = MongoClient(mongo_uri)
    try:
        database = client.get_default_database()
        existing_collections = set(database.list_collection_names())
        expected_collections = {path.stem for path in _schema_files(schemas_dir)}
        missing_collections = sorted(expected_collections - existing_collections)
        findings = [
            MongoReadinessFinding(
                severity="fail",
                resource_type="collection",
                resource_name=collection_name,
                detail="Expected collection is missing from the target database.",
            )
            for collection_name in missing_collections
        ]

        collections_with_validators = 0
        for collection_name in sorted(expected_collections & existing_collections):
            result = database.command("listCollections", filter={"name": collection_name})
            first_batch = result.get("cursor", {}).get("firstBatch", [])
            options = first_batch[0].get("options", {}) if first_batch else {}
            if options.get("validator"):
                collections_with_validators += 1

        expected_index_collections = {path.stem for path in _index_files(indexes_dir)}
        live_index_collections_checked = 0
        for collection_name in sorted(expected_index_collections & existing_collections):
            # list_indexes is read-only. Do not call create_index here.
            list(database[collection_name].list_indexes())
            live_index_collections_checked += 1

        return (
            {
                "missing_collections": len(missing_collections),
                "collections_with_validators": collections_with_validators,
                "live_index_collections_checked": live_index_collections_checked,
            },
            findings,
        )
    finally:
        client.close()


def build_mongo_readiness_report(
    *,
    schemas_dir: Path,
    indexes_dir: Path,
    mongo_uri: str | None = None,
) -> MongoReadinessReport:
    schema_summary, schema_findings = _validate_schema_files(schemas_dir)
    index_summary, index_findings = _validate_index_files(indexes_dir)

    summary = {**schema_summary, **index_summary, "missing_collections": 0}
    findings = [*schema_findings, *index_findings]

    if mongo_uri:
        live_summary, live_findings = _live_read_only_findings(
            mongo_uri=mongo_uri,
            schemas_dir=schemas_dir,
            indexes_dir=indexes_dir,
        )
        summary.update(live_summary)
        findings.extend(live_findings)

    if not findings:
        findings.append(
            MongoReadinessFinding(
                severity="pass",
                resource_type="schema",
                resource_name="local-files",
                detail="Schema and index files are readable; no drift detected in selected mode.",
            )
        )

    return MongoReadinessReport(
        mode="read-only-live-check" if mongo_uri else "offline",
        safe_to_execute=True,
        read_only=True,
        live_target_checked=bool(mongo_uri),
        mutations_attempted=0,
        summary=summary,
        findings=tuple(findings),
    )


def render_mongo_markdown(report: MongoReadinessReport) -> str:
    lines = [
        "# Mongo Readiness Validation",
        "",
        f"- mode: {report.mode}",
        f"- safe_to_execute: {str(report.safe_to_execute).lower()}",
        f"- read_only: {str(report.read_only).lower()}",
        f"- mutations_attempted: {report.mutations_attempted}",
        "- Safety model: No collMod, createIndex, drop, or import operations are attempted; "
        "live mode only uses listCollections and listIndexes.",
        "",
        "## Summary",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(report.summary.items()))
    lines.extend(["", "## Findings", ""])
    lines.extend(
        f"- [{finding.severity}] {finding.resource_type} "
        f"`{finding.resource_name}` — {finding.detail}"
        for finding in report.findings
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Mongo readiness without mutation.")
    parser.add_argument("--schemas-dir", type=Path, default=Path("infra/mongo/schemas"))
    parser.add_argument("--indexes-dir", type=Path, default=Path("infra/mongo/indexes"))
    parser.add_argument(
        "--mongo-uri",
        default=None,
        help="Optional target URI for read-only live check.",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    report = build_mongo_readiness_report(
        schemas_dir=args.schemas_dir,
        indexes_dir=args.indexes_dir,
        mongo_uri=cast(str | None, args.mongo_uri),
    )
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_mongo_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
