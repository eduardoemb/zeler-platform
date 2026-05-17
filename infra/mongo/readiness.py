from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pymongo import MongoClient

Severity = Literal["pass", "fail"]
EXPECTED_ADMIN_CLIENT_SCOPES = {
    "zeler-app": {
        "admin:repricer",
        "admin:sheets",
        "admin:publicador",
        "admin:autoreply",
    }
}


@dataclass(frozen=True)
class MongoReadinessFinding:
    severity: Severity
    resource_type: Literal["schema", "index", "collection", "seed", "module_registry_doc"]
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


def _seed_files(seeds_dir: Path | None) -> list[Path]:
    return sorted(seeds_dir.glob("*.json")) if seeds_dir and seeds_dir.exists() else []


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


def _is_module_registry_seed_document(document: Any) -> bool:
    return isinstance(document, dict) and isinstance(document.get("_id"), str)


def _validate_module_registry_seed_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_object_fields = {
        "version": str,
        "allowed_meli_scopes": list,
        "routing_keys": list,
        "owned_collections": list,
        "health_endpoint": str,
        "status": str,
        "schema_version": int,
    }
    for field_name, expected_type in required_object_fields.items():
        if not isinstance(document.get(field_name), expected_type):
            errors.append(f"{field_name} must be {expected_type.__name__}")
    if document.get("status") != "enabled":
        errors.append("status must be enabled")
    if not all(isinstance(scope, str) for scope in document.get("allowed_meli_scopes", [])):
        errors.append("allowed_meli_scopes must contain only strings")
    return errors


def _find_admin_scope_mismatch(document: dict[str, Any]) -> str | None:
    module_id = document["_id"]
    expected_scopes = EXPECTED_ADMIN_CLIENT_SCOPES.get(module_id)
    if expected_scopes is None:
        return None
    actual_scopes = set(document.get("allowed_meli_scopes", []))
    missing_scopes = sorted(expected_scopes - actual_scopes)
    unexpected_scopes = sorted(actual_scopes - expected_scopes)
    if missing_scopes or unexpected_scopes:
        return (
            f"Expected scopes {sorted(expected_scopes)}; "
            f"missing={missing_scopes}; unexpected={unexpected_scopes}."
        )
    return None


def _validate_seed_files(
    seeds_dir: Path | None,
) -> tuple[dict[str, int], list[MongoReadinessFinding]]:
    findings: list[MongoReadinessFinding] = []
    seed_files = _seed_files(seeds_dir)
    errors = 0
    seed_docs = 0
    module_registry_admin_clients = 0
    scope_mismatches = 0

    for seed_path in seed_files:
        try:
            loaded = _load_json(seed_path)
            if not isinstance(loaded, dict):
                raise ValueError("seed file must contain a JSON object")
            if loaded.get("collection") != "module_registry":
                raise ValueError("seed collection must be module_registry")
            documents = loaded.get("documents")
            if not isinstance(documents, list):
                raise ValueError("seed documents must be a JSON array")
            seed_docs += len(documents)
            for document in documents:
                if not _is_module_registry_seed_document(document):
                    raise ValueError("module_registry seed document requires string _id")
                document_errors = _validate_module_registry_seed_document(document)
                if document_errors:
                    errors += 1
                    findings.append(
                        MongoReadinessFinding(
                            severity="fail",
                            resource_type="seed",
                            resource_name=document["_id"],
                            detail="; ".join(document_errors),
                        )
                    )
                if document["_id"] in EXPECTED_ADMIN_CLIENT_SCOPES:
                    module_registry_admin_clients += 1
                    if mismatch := _find_admin_scope_mismatch(document):
                        scope_mismatches += 1
                        findings.append(
                            MongoReadinessFinding(
                                severity="fail",
                                resource_type="seed",
                                resource_name=document["_id"],
                                detail=mismatch,
                            )
                        )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors += 1
            findings.append(
                MongoReadinessFinding(
                    severity="fail",
                    resource_type="seed",
                    resource_name=seed_path.name,
                    detail=str(exc),
                )
            )

    return (
        {
            "seed_files": len(seed_files),
            "seed_documents": seed_docs,
            "seed_file_errors": errors,
            "module_registry_admin_clients": module_registry_admin_clients,
            "module_registry_scope_mismatches": scope_mismatches,
        },
        findings,
    )


def _load_module_registry_export(export_path: Path) -> list[dict[str, Any]]:
    loaded = _load_json(export_path)
    if isinstance(loaded, list):
        documents = loaded
    elif isinstance(loaded, dict) and isinstance(loaded.get("documents"), list):
        documents = loaded["documents"]
    else:
        raise ValueError(
            "module_registry export must be a JSON array or an object with documents array"
        )
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError("module_registry export documents must be objects")
    return cast(list[dict[str, Any]], documents)


def _module_registry_export_findings(
    module_registry_export_path: Path | None,
) -> tuple[dict[str, int], list[MongoReadinessFinding]]:
    if module_registry_export_path is None:
        return (
            {
                "module_registry_export_docs_checked": 0,
                "module_registry_missing_admin_clients": 0,
                "module_registry_export_scope_mismatches": 0,
            },
            [],
        )

    documents = _load_module_registry_export(module_registry_export_path)
    by_id = {document.get("_id"): document for document in documents}
    findings: list[MongoReadinessFinding] = []
    missing_admin_clients = 0
    scope_mismatches = 0

    for module_id in sorted(EXPECTED_ADMIN_CLIENT_SCOPES):
        document = by_id.get(module_id)
        if document is None:
            missing_admin_clients += 1
            findings.append(
                MongoReadinessFinding(
                    severity="fail",
                    resource_type="module_registry_doc",
                    resource_name=module_id,
                    detail="Expected admin client is missing from provided module_registry export.",
                )
            )
            continue
        if mismatch := _find_admin_scope_mismatch(document):
            scope_mismatches += 1
            findings.append(
                MongoReadinessFinding(
                    severity="fail",
                    resource_type="module_registry_doc",
                    resource_name=module_id,
                    detail=mismatch,
                )
            )

    return (
        {
            "module_registry_export_docs_checked": len(documents),
            "module_registry_missing_admin_clients": missing_admin_clients,
            "module_registry_export_scope_mismatches": scope_mismatches,
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
    seeds_dir: Path | None = None,
    module_registry_export_path: Path | None = None,
    mongo_uri: str | None = None,
) -> MongoReadinessReport:
    schema_summary, schema_findings = _validate_schema_files(schemas_dir)
    index_summary, index_findings = _validate_index_files(indexes_dir)
    seed_summary, seed_findings = _validate_seed_files(seeds_dir)
    module_registry_summary, module_registry_findings = _module_registry_export_findings(
        module_registry_export_path
    )

    summary = {
        **schema_summary,
        **index_summary,
        **seed_summary,
        **module_registry_summary,
        "missing_collections": 0,
    }
    findings = [*schema_findings, *index_findings, *seed_findings, *module_registry_findings]

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
        "- Seed safety: Seed files are local JSON contracts only; readiness does not "
        "insert or upsert seed documents.",
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
    parser.add_argument("--seeds-dir", type=Path, default=Path("infra/mongo/seeds"))
    parser.add_argument(
        "--module-registry-export",
        type=Path,
        default=None,
        help="Optional JSON export of module_registry documents for read-only comparison.",
    )
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
        seeds_dir=args.seeds_dir,
        module_registry_export_path=cast(Path | None, args.module_registry_export),
        mongo_uri=cast(str | None, args.mongo_uri),
    )
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_mongo_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
