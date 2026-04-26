from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from zeler_gateway.config import Settings

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-dev.yml"
PROD_COMPOSE_PATH = ROOT / "infra" / "docker" / "mongo-prod.yml"
RS_URI_SUFFIX = "?replicaSet=rs0-dev&directConnection=true&authSource=admin"


def _load_compose(path: Path = COMPOSE_PATH) -> dict[str, Any]:
    assert COMPOSE_PATH.exists(), "infra/docker/mongo-dev.yml must exist"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _mongo_service(document: dict[str, Any]) -> dict[str, Any]:
    services = document.get("services")
    assert isinstance(services, dict)
    mongo = services.get("mongo")
    assert isinstance(mongo, dict)
    return mongo


def test_mongo_dev_uses_mongo_7_image() -> None:
    mongo = _mongo_service(_load_compose())

    image = mongo.get("image")
    assert isinstance(image, str)
    assert image == "mongo:7" or image.startswith("mongo:7.")


def test_mongo_dev_compose_project_name_is_zeler_mongo_dev() -> None:
    assert _load_compose().get("name") == "zeler-mongo-dev"


def test_mongo_dev_preserves_localhost_port_mapping() -> None:
    mongo = _mongo_service(_load_compose())

    ports = mongo.get("ports")
    assert ports == ["127.0.0.1:${MONGO_HOST_PORT:-27017}:27017"]


def test_mongo_dev_has_root_credentials_env_contract() -> None:
    mongo = _mongo_service(_load_compose())

    environment = mongo.get("environment")
    assert isinstance(environment, dict)
    assert environment["MONGO_INITDB_ROOT_USERNAME"] == "${MONGO_ROOT_USER}"
    password_key = "MONGO_INITDB_ROOT_" + "PASSWORD"
    password_env_ref = "${MONGO_ROOT_" + "PASSWORD}"
    assert environment[password_key] == password_env_ref


def test_mongo_dev_uses_single_node_replica_set_command_with_keyfile() -> None:
    mongo = _mongo_service(_load_compose())

    command = mongo.get("command")
    assert command == [
        "mongod",
        "--replSet",
        "rs0-dev",
        "--bind_ip_all",
        "--auth",
        "--keyFile",
        "/etc/mongo/keyfile/rs0.key",
    ]
    # Option B rejected by mongod 7.0+ (BadValue). Consciously replaced per spec scenario 1.3.
    assert "--keyFile" in command
    assert command[command.index("--keyFile") + 1] == "/etc/mongo/keyfile/rs0.key"


def test_mongo_dev_keeps_named_volume() -> None:
    document = _load_compose()
    mongo = _mongo_service(document)

    volumes = mongo.get("volumes")
    assert isinstance(volumes, list)
    assert "zeler-mongo-data:/data/db" in volumes

    declared_volumes = document.get("volumes")
    assert isinstance(declared_volumes, dict)
    assert "zeler-mongo-data" in declared_volumes


def test_mongo_dev_mounts_shared_keyfile_readonly() -> None:
    mongo = _mongo_service(_load_compose())

    volumes = mongo.get("volumes")
    assert isinstance(volumes, list)
    assert "./mongo-keyfiles:/etc/mongo/keyfile:ro" in volumes


def test_mongo_dev_has_healthcheck_ping_contract() -> None:
    mongo = _mongo_service(_load_compose())

    healthcheck = mongo.get("healthcheck")
    assert isinstance(healthcheck, dict)
    assert healthcheck["test"] == [
        "CMD",
        "mongosh",
        "--quiet",
        "--eval",
        "db.adminCommand({ping:1}).ok",
    ]
    assert healthcheck["interval"] == "10s"
    assert healthcheck["timeout"] == "5s"
    assert healthcheck["retries"] == 5
    assert healthcheck["start_period"] == "20s"


def test_mongo_dev_uses_declared_network_and_restart_policy() -> None:
    document = _load_compose()
    mongo = _mongo_service(document)

    networks = document.get("networks")
    assert isinstance(networks, dict)
    assert "zeler-platform-dev" in networks

    service_networks = mongo.get("networks")
    assert service_networks == ["zeler-platform-dev"]
    assert mongo.get("restart") == "unless-stopped"


def test_dev_rs_name_is_distinct_from_prod() -> None:
    dev_command = _mongo_service(_load_compose()).get("command")
    prod_command = _mongo_service(_load_compose(PROD_COMPOSE_PATH)).get("command")

    assert isinstance(dev_command, list)
    assert isinstance(prod_command, list)
    dev_rs_name = dev_command[dev_command.index("--replSet") + 1]
    prod_rs_name = prod_command[prod_command.index("--replSet") + 1]
    assert dev_rs_name == "rs0-dev"
    assert prod_rs_name == "rs0"
    assert dev_rs_name != prod_rs_name


def test_env_example_mongo_uri_is_replica_set_aware() -> None:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")

    mongo_uri_line = next(line for line in content.splitlines() if line.startswith("MONGO_URI="))
    assert mongo_uri_line.endswith(RS_URI_SUFFIX)


def test_default_mongo_uri_fixture_fallback_is_replica_set_aware() -> None:
    from conftest import _DEV_FALLBACK_MONGO_URI

    assert _DEV_FALLBACK_MONGO_URI.endswith(RS_URI_SUFFIX)


def test_gateway_settings_default_mongo_uri_is_replica_set_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_DB", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.mongo_uri.endswith(RS_URI_SUFFIX)
    assert settings.mongo_db == "zeler_platform_dev"
