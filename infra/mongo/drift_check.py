from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from infra.mongo.apply_validators import DEFAULT_SCHEMAS_DIR, _desired_validator, _load_schema
from pymongo import MongoClient


def load_repo_validators(schemas_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        schema_path.stem: _desired_validator(_load_schema(schema_path))
        for schema_path in sorted(schemas_dir.glob("*.json"))
    }


def load_live_validators(mongo_uri: str, collection_names: set[str]) -> dict[str, dict[str, Any]]:
    client: MongoClient[Any] = MongoClient(mongo_uri)
    try:
        database = client.get_default_database()
        validators: dict[str, dict[str, Any]] = {}
        for collection_name in sorted(collection_names):
            result = database.command("listCollections", filter={"name": collection_name})
            first_batch = result.get("cursor", {}).get("firstBatch", [])
            if not first_batch:
                continue
            validator = first_batch[0].get("options", {}).get("validator", {})
            validators[collection_name] = validator if isinstance(validator, dict) else {}
        return validators
    finally:
        client.close()


def compare_validators(
    repo_validators: dict[str, dict[str, Any]],
    live_validators: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    collections: dict[str, dict[str, Any]] = {}
    names = set(repo_validators) | set(live_validators)
    for name in sorted(names):
        if name not in live_validators:
            status = "missing"
        elif name not in repo_validators:
            status = "extra"
        elif repo_validators[name] == live_validators[name]:
            status = "applied"
        else:
            status = "drifted"
        collections[name] = {
            "status": status,
            "repo_validator": repo_validators.get(name),
            "live_validator": live_validators.get(name),
        }
    return {
        "has_drift": any(item["status"] != "applied" for item in collections.values()),
        "collections": collections,
    }


def build_report(*, mongo_uri: str | None, schemas_dir: Path) -> dict[str, Any]:
    repo_validators = load_repo_validators(schemas_dir)
    live_validators = load_live_validators(mongo_uri, set(repo_validators)) if mongo_uri else {}
    return compare_validators(repo_validators, live_validators)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare repo Mongo validators with live Mongo")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGO_URI"))
    parser.add_argument("--schemas-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    parser.add_argument("--export-json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(mongo_uri=args.mongo_uri, schemas_dir=args.schemas_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["has_drift"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
