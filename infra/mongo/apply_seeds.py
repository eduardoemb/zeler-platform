"""Idempotent seed applicator for zeler-platform MongoDB collections.

Applies all ``*.json`` seed files under a given directory to the target database
via ``update_one`` with ``$setOnInsert`` and ``upsert=True``.

Idempotency guarantee
---------------------
``$setOnInsert`` means the document is written **only on insertion**.  If a
document with the same ``_id`` already exists the operation is a no-op — live
data is never overwritten.  Seeds are bootstrap-only: they bring an empty
database to a known starting state and are safe to re-run at any time.

Separation of concerns
-----------------------
This script is intentionally separate from ``apply_validators.py``.  Validators
define the *shape* of collections; seeds supply *initial content*.  Running
both is idempotent and order-independent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEEDS_DIR = ROOT / "infra" / "mongo" / "seeds"
DEFAULT_MONGO_URI = (
    "mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/"
    "zeler_platform_dev?authSource=admin"
)


def _load_seed(seed_path: Path) -> dict[str, Any]:
    with seed_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    if not isinstance(loaded, dict):
        msg = f"Seed file must contain a JSON object: {seed_path}"
        raise ValueError(msg)

    if "collection" not in loaded or not isinstance(loaded["collection"], str):
        msg = f"Seed file must have a string 'collection' field: {seed_path}"
        raise ValueError(msg)

    if "documents" not in loaded or not isinstance(loaded["documents"], list):
        msg = f"Seed file must have a 'documents' array: {seed_path}"
        raise ValueError(msg)

    for doc in loaded["documents"]:
        if not isinstance(doc, dict):
            msg = f"Each document must be a JSON object: {seed_path}"
            raise ValueError(msg)
        if "_id" not in doc:
            msg = f"Each document must have an '_id' field: {seed_path}"
            raise ValueError(msg)

    return loaded


def apply_seeds(mongo_uri: str, seeds_dir: Path) -> dict[str, str]:
    """Apply all seed JSON files in *seeds_dir* to the database.

    Parameters
    ----------
    mongo_uri:
        MongoDB connection URI.  The database name is taken from the URI path.
    seeds_dir:
        Directory containing ``*.json`` seed files.

    Returns
    -------
    dict[str, str]
        Mapping of ``"collection/_id"`` → ``"inserted"`` | ``"unchanged"``
        for every document processed.  Returns ``{}`` if *seeds_dir* does not
        exist.
    """
    client: MongoClient[Mapping[str, Any]] = MongoClient(mongo_uri)

    try:
        if not seeds_dir.exists():
            return {}

        database = client.get_default_database()
        results: dict[str, str] = {}

        for seed_path in sorted(seeds_dir.glob("*.json")):
            seed = _load_seed(seed_path)
            collection_name: str = seed["collection"]
            documents: list[dict[str, Any]] = seed["documents"]

            for doc in documents:
                doc_id = doc["_id"]
                result = database[collection_name].update_one(
                    {"_id": doc_id},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
                key = f"{collection_name}/{doc_id}"
                if result.upserted_id is not None:
                    results[key] = "inserted"
                else:
                    results[key] = "unchanged"

        return results
    finally:
        client.close()


def main() -> None:
    mongo_uri = os.environ.get("MONGO_URI", DEFAULT_MONGO_URI)
    seeds_dir = Path(os.environ.get("SEEDS_DIR", str(DEFAULT_SEEDS_DIR)))
    apply_seeds(mongo_uri, seeds_dir)


if __name__ == "__main__":
    main()
