from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-dev.yml"


def test_mongo_dev_compose_contract() -> None:
    assert COMPOSE_PATH.exists(), "infra/docker/mongo-dev.yml must exist"

    document = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    assert isinstance(document, dict)

    services = document.get("services")
    assert isinstance(services, dict)

    mongo = services.get("mongo")
    assert isinstance(mongo, dict)

    image = mongo.get("image")
    assert isinstance(image, str)
    assert image == "mongo:7" or image.startswith("mongo:7.")

    ports = mongo.get("ports")
    assert ports == ["127.0.0.1:27017:27017"]

    environment = mongo.get("environment")
    assert isinstance(environment, dict)
    assert "MONGO_INITDB_ROOT_USERNAME" in environment
    assert "MONGO_INITDB_ROOT_PASSWORD" in environment

    volumes = mongo.get("volumes")
    assert isinstance(volumes, list)
    assert any(volume.endswith(":/data/db") for volume in volumes)

    declared_volumes = document.get("volumes")
    assert isinstance(declared_volumes, dict)
    assert any(volume.split(":", 1)[0] in declared_volumes for volume in volumes)

    networks = document.get("networks")
    assert isinstance(networks, dict)

    service_networks = mongo.get("networks")
    assert isinstance(service_networks, list)
    assert all(network in networks for network in service_networks)
