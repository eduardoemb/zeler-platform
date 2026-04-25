from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-prod.yml"


def _document() -> dict[str, Any]:
    assert COMPOSE_PATH.exists(), "infra/docker/mongo-prod.yml must exist"
    document = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _mongo_service() -> dict[str, Any]:
    document = _document()
    services = document.get("services")
    assert isinstance(services, dict)
    mongo = services.get("mongo")
    assert isinstance(mongo, dict)
    return mongo


def test_image_is_mongo_7() -> None:
    image = _mongo_service().get("image")
    assert isinstance(image, str)
    assert re.fullmatch(r"mongo:7(?:\..*)?", image)


def test_container_name_is_zeler_mongo_prod() -> None:
    assert _mongo_service().get("container_name") == "zeler-mongo-prod"


def test_port_mapping_loopback_27019() -> None:
    ports = _mongo_service().get("ports")
    assert ports == ["127.0.0.1:27019:27017"]


def test_command_flags_exact() -> None:
    assert _mongo_service().get("command") == [
        "mongod",
        "--replSet",
        "rs0",
        "--auth",
        "--keyFile",
        "/etc/mongo/keyfile/rs0.key",
        "--bind_ip_all",
    ]


def test_keyfile_bind_mount_readonly() -> None:
    volumes = _mongo_service().get("volumes")
    assert isinstance(volumes, list)
    assert "./mongo-keyfiles:/etc/mongo/keyfile:ro" in volumes


def test_named_volume_for_data() -> None:
    document = _document()
    mongo = _mongo_service()
    volumes = mongo.get("volumes")
    assert isinstance(volumes, list)
    assert "zeler-mongo-prod-data:/data/db" in volumes

    declared_volumes = document.get("volumes")
    assert isinstance(declared_volumes, dict)
    assert "zeler-mongo-prod-data" in declared_volumes


def test_environment_uses_prod_root_credentials() -> None:
    environment = _mongo_service().get("environment")
    assert environment == {
        "MONGO_INITDB_ROOT_USERNAME": "${MONGO_PROD_ROOT_USER}",
        "MONGO_INITDB_ROOT_PASSWORD": "${MONGO_PROD_ROOT_PASSWORD}",
    }


def test_healthcheck_uses_mongosh_ping() -> None:
    healthcheck = _mongo_service().get("healthcheck")
    assert isinstance(healthcheck, dict)
    assert healthcheck.get("test") == [
        "CMD",
        "mongosh",
        "--quiet",
        "--eval",
        "db.adminCommand({ping:1}).ok",
    ]
    assert healthcheck.get("interval") == "10s"
    assert healthcheck.get("timeout") == "5s"
    assert healthcheck.get("retries") == 5
    assert healthcheck.get("start_period") == "20s"


def test_network_zeler_platform_prod() -> None:
    document = _document()
    mongo = _mongo_service()
    assert mongo.get("networks") == ["zeler-platform-prod"]

    networks = document.get("networks")
    assert isinstance(networks, dict)
    assert "zeler-platform-prod" in networks


def test_restart_policy_unless_stopped() -> None:
    assert _mongo_service().get("restart") == "unless-stopped"
