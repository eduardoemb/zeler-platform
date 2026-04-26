from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEV_COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-dev.yml"
PROD_COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-prod.yml"


def _load_compose(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _mongo_service(document: dict[str, Any]) -> dict[str, Any]:
    services = document.get("services")
    assert isinstance(services, dict)
    mongo = services.get("mongo")
    assert isinstance(mongo, dict)
    return mongo


def test_mongo_compose_files_are_isolated_by_project_network_volume_and_container() -> None:
    dev = _load_compose(DEV_COMPOSE_PATH)
    prod = _load_compose(PROD_COMPOSE_PATH)
    dev_mongo = _mongo_service(dev)
    prod_mongo = _mongo_service(prod)

    assert dev.get("name") == "zeler-mongo-dev"
    assert prod.get("name") == "zeler-mongo-prod"
    assert dev["name"] != prod["name"]

    dev_networks = set(dev.get("networks", {}))
    prod_networks = set(prod.get("networks", {}))
    assert dev_networks == {"zeler-platform-dev"}
    assert prod_networks == {"zeler-platform-prod"}
    assert dev_networks.isdisjoint(prod_networks)

    dev_volumes = set(dev.get("volumes", {}))
    prod_volumes = set(prod.get("volumes", {}))
    assert dev_volumes == {"zeler-mongo-data"}
    assert prod_volumes == {"zeler-mongo-prod-data"}
    assert dev_volumes.isdisjoint(prod_volumes)

    assert dev_mongo.get("container_name") == "zeler-mongo-dev"
    assert prod_mongo.get("container_name") == "zeler-mongo-prod"
    assert dev_mongo["container_name"] != prod_mongo["container_name"]
