from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

CANONICAL_VALIDATOR_FILES = {
    "audit_log.json",
    "bootstrap_jobs.json",
    "claims.json",
    "events.json",
    "fulldock_history.json",
    "fulldock_inventory_rules.json",
    "items.json",
    "meli_accounts.json",
    "messages.json",
    "module_registry.json",
    "orders.json",
    "questions.json",
    "repricer_history.json",
    "repricer_rules.json",
    "shipments.json",
    "users.json",
    "webhook_events.json",
}


@dataclass(frozen=True)
class ValidatorResult:
    valid: bool
    missing_required_fields: list[str]


def canonical_validator_files(schemas_dir: Path) -> set[str]:
    return {
        path.name for path in schemas_dir.glob("*.json") if path.name in CANONICAL_VALIDATOR_FILES
    }


def validate_document_against_schema(
    document: dict[str, Any], validator: dict[str, Any]
) -> ValidatorResult:
    schema = validator.get("$jsonSchema", validator)
    if not isinstance(schema, dict):
        msg = "validator must contain a $jsonSchema object"
        raise ValueError(msg)
    required = schema.get("required", [])
    if not isinstance(required, list):
        msg = "validator required field must be a list"
        raise ValueError(msg)
    missing = [field for field in required if field not in document]
    return ValidatorResult(valid=not missing, missing_required_fields=missing)
