from __future__ import annotations

import json
from pathlib import Path

ENTITY_SCHEMAS: dict[str, dict[str, object]] = {
    "items": {
        "required": [
            "_id",
            "seller_id",
            "title",
            "price",
            "base_price",
            "available_quantity",
            "status",
            "category_id",
            "last_meli_sync_at",
            "date_created",
            "last_updated",
            "schema_version",
        ],
        "properties": {
            "_id": {"bsonType": "string"},
            "seller_id": {"bsonType": ["string", "long", "int"]},
            "title": {"bsonType": "string"},
            "schema_version": {"bsonType": "int"},
        },
    }
}


def export_schemas(output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for collection, partial_schema in ENTITY_SCHEMAS.items():
        payload = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": partial_schema["required"],
                "properties": partial_schema["properties"],
            }
        }
        path = output_dir / f"{collection}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path.name)
    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Export Mongo $jsonSchema validators from core models"
    )
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    export_schemas(args.output_dir)


if __name__ == "__main__":
    main()
