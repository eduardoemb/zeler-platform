from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
DEFAULT_MONGO_URI = (
    "mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/"
    "zeler_platform_dev?authSource=admin"
)


def _load_schema(schema_path: Path) -> dict[str, Any]:
    import json

    with schema_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    if not isinstance(loaded, dict):
        msg = f"Schema file must contain a JSON object: {schema_path}"
        raise ValueError(msg)

    return loaded


def _desired_validator(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {}

    return {"$jsonSchema": schema}


def _current_validator(
    database: Database[Mapping[str, Any]],
    collection_name: str,
) -> dict[str, Any]:
    result = database.command("listCollections", filter={"name": collection_name})
    cursor = result.get("cursor", {})
    first_batch = cursor.get("firstBatch", [])

    if not first_batch:
        return {}

    collection_info = first_batch[0]
    options = collection_info.get("options", {})
    validator = options.get("validator", {})

    if not isinstance(validator, dict):
        msg = f"Validator for collection {collection_name} must be a document"
        raise ValueError(msg)

    return validator


def apply_validators(mongo_uri: str, schemas_dir: Path) -> dict[str, str]:
    client: MongoClient[Mapping[str, Any]] = MongoClient(mongo_uri)

    try:
        database = client.get_default_database()
        results: dict[str, str] = {}

        for schema_path in sorted(schemas_dir.glob("*.json")):
            collection_name = schema_path.stem
            schema = _load_schema(schema_path)
            desired_validator = _desired_validator(schema)

            if collection_name not in database.list_collection_names():
                if desired_validator:
                    database.create_collection(collection_name, validator=desired_validator)
                else:
                    database.create_collection(collection_name)
                results[collection_name] = "created"
                continue

            current_validator = _current_validator(database, collection_name)

            if not desired_validator:
                database.command("collMod", collection_name, validator={})
                results[collection_name] = "unchanged" if current_validator == {} else "applied"
                continue

            if current_validator == desired_validator:
                results[collection_name] = "unchanged"
                continue

            database.command("collMod", collection_name, validator=desired_validator)
            results[collection_name] = "applied"

        return results
    finally:
        client.close()


def main() -> None:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    schemas_dir = Path(os.environ.get("SCHEMAS_DIR", str(DEFAULT_SCHEMAS_DIR)))
    apply_validators(mongo_uri, schemas_dir)


if __name__ == "__main__":
    main()
