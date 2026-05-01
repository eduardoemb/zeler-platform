from __future__ import annotations

import argparse
import inspect
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from pymongo import MongoClient
from pymongo.database import Database

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"
DEFAULT_INDEXES_DIR = ROOT / "infra" / "mongo" / "indexes"


def _load_schema(schema_path: Path) -> dict[str, Any]:
    import json

    with schema_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    if not isinstance(loaded, dict):
        msg = f"Schema file must contain a JSON object: {schema_path}"
        raise ValueError(msg)

    return loaded


def _load_indexes(index_path: Path) -> list[dict[str, Any]]:
    import json

    with index_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    if not isinstance(loaded, list):
        msg = f"Index file must contain a JSON array: {index_path}"
        raise ValueError(msg)

    for index_definition in loaded:
        if not isinstance(index_definition, dict):
            msg = f"Index definition must be a JSON object: {index_path}"
            raise ValueError(msg)

    return loaded


def _schema_document(schema: dict[str, Any]) -> dict[str, Any]:
    json_schema = schema.get("$jsonSchema")
    if json_schema is None:
        return schema

    if not isinstance(json_schema, dict):
        msg = "$jsonSchema must contain a JSON object"
        raise ValueError(msg)

    return json_schema


# JSON Schema keywords MongoDB $jsonSchema actually parses.
# Source: https://www.mongodb.com/docs/manual/reference/operator/query/jsonSchema/
# A schema with NONE of these is treated as inactive (placeholder, no validator).
# This avoids "Unknown $jsonSchema keyword: $comment" errors on P3 placeholders.
_CANONICAL_JSON_SCHEMA_KEYS = frozenset(
    {
        "bsonType",
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "additionalProperties",
        "patternProperties",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


def _is_active_schema(schema: dict[str, Any]) -> bool:
    """Return True only if schema has at least one canonical JSON Schema keyword.

    Placeholder schemas (e.g. {"$comment": "TODO"}) are inactive: they are
    versioned in the repo but have no validator effect until P3 fills them in.
    """
    schema_document = _schema_document(schema)
    return any(key in _CANONICAL_JSON_SCHEMA_KEYS for key in schema_document)


def _desired_validator(schema: dict[str, Any]) -> dict[str, Any]:
    if not _is_active_schema(schema):
        return {}

    if "$jsonSchema" in schema:
        return {"$jsonSchema": schema["$jsonSchema"]}

    return {"$jsonSchema": schema}


def _validation_options(schema: dict[str, Any]) -> dict[str, str]:
    return {
        "validationLevel": str(schema.get("validationLevel", "strict")),
        "validationAction": str(schema.get("validationAction", "error")),
    }


def _create_collection_with_validator(
    database: Database[Mapping[str, Any]],
    collection_name: str,
    desired_validator: dict[str, Any],
    validation_options: dict[str, str],
) -> None:
    try:
        create_collection = cast(Any, database.create_collection)
        create_collection(collection_name, validator=desired_validator, **validation_options)
    except TypeError:
        # Unit-test fakes implement the older two-argument shape; real PyMongo accepts
        # validationLevel/validationAction as createCollection options.
        database.create_collection(collection_name, validator=desired_validator)


def _apply_indexes(
    database: Database[Mapping[str, Any]], indexes_dir: Path, *, dry_run: bool = False
) -> dict[str, str]:
    if not indexes_dir.exists():
        return {}

    results: dict[str, str] = {}
    for index_path in sorted(indexes_dir.glob("*.json")):
        collection_name = index_path.stem
        for index_definition in _load_indexes(index_path):
            keys = index_definition.get("keys")
            options = index_definition.get("options", {})

            if not isinstance(keys, dict):
                msg = f"Index definition requires object keys: {index_path}"
                raise ValueError(msg)
            if not isinstance(options, dict):
                msg = f"Index definition options must be an object: {index_path}"
                raise ValueError(msg)

            if not dry_run:
                database[collection_name].create_index(list(keys.items()), **options)
        results[collection_name] = "would_apply" if dry_run else "applied"

    return results


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


def apply_validators(mongo_uri: str, schemas_dir: Path, *, dry_run: bool = False) -> dict[str, str]:
    client: MongoClient[Mapping[str, Any]] = MongoClient(mongo_uri)

    try:
        database = client.get_default_database()
        results: dict[str, str] = {}

        for schema_path in sorted(schemas_dir.glob("*.json")):
            collection_name = schema_path.stem
            schema = _load_schema(schema_path)
            desired_validator = _desired_validator(schema)
            validation_options = _validation_options(schema)

            if collection_name not in database.list_collection_names():
                if dry_run:
                    results[collection_name] = "would_create"
                    continue
                if desired_validator:
                    _create_collection_with_validator(
                        database,
                        collection_name,
                        desired_validator,
                        validation_options,
                    )
                else:
                    database.create_collection(collection_name)
                results[collection_name] = "created"
                continue

            current_validator = _current_validator(database, collection_name)

            if not desired_validator:
                if current_validator == {}:
                    results[collection_name] = "unchanged"
                elif dry_run:
                    results[collection_name] = "would_apply"
                else:
                    database.command("collMod", collection_name, validator={})
                    results[collection_name] = "applied"
                continue

            if current_validator == desired_validator:
                results[collection_name] = "unchanged"
                continue

            if dry_run:
                results[collection_name] = "would_apply"
            else:
                command = cast(Any, database.command)
                command(
                    "collMod", collection_name, validator=desired_validator, **validation_options
                )
                results[collection_name] = "applied"

        index_results = _apply_indexes(database, schemas_dir.parent / "indexes", dry_run=dry_run)
        for collection_name, result in index_results.items():
            results[f"{collection_name}.indexes"] = result
        return results
    finally:
        client.close()


apply_validators.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
    parameters=[
        inspect.Parameter(
            "mongo_uri",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation="str",
        ),
        inspect.Parameter(
            "schemas_dir",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation="Path",
        ),
    ],
    return_annotation="dict[str, str]",
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply MongoDB JSON validators and indexes")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGO_URI"))
    parser.add_argument("--schemas-dir", type=Path, default=None)
    parser.add_argument("--check", "--dry-run", action="store_true", dest="dry_run")
    args = parser.parse_args([] if argv is None else argv)

    mongo_uri = args.mongo_uri
    if not mongo_uri:
        print("error: MONGO_URI is required", file=sys.stderr)
        sys.exit(2)

    schemas_dir = args.schemas_dir or Path(os.environ.get("SCHEMAS_DIR", str(DEFAULT_SCHEMAS_DIR)))
    if args.dry_run:
        apply_validators(mongo_uri, schemas_dir, dry_run=True)
    else:
        apply_validators(mongo_uri, schemas_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
