"""Ops Agent, Caddy, and startup classified-log configuration contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
INFRA_GCE = ROOT / "infra" / "gce"
OPS_AGENT_CONFIG = INFRA_GCE / "ops-agent-config.yaml"
CADDYFILE = INFRA_GCE / "Caddyfile"
STARTUP = INFRA_GCE / "platform-vm-startup.sh"

GATEWAY_CLASSIFIED_LOG_TYPE = "zeler-platform/gateway-classified"
CADDY_CLASSIFIED_LOG_TYPE = "zeler-platform/caddy-classified"
DOCKER_CONTAINER_LOGS_GLOB = "/var/lib/docker/containers/*/*-json.log"

EMBEDDED_CFG_PATTERN = re.compile(
    r"cat > /opt/zeler-platform/ops-agent-config\.yaml << 'OPSAGENT'\n(.*?)\nOPSAGENT",
    re.DOTALL,
)


def load_ops_agent_config() -> dict[str, Any]:
    with OPS_AGENT_CONFIG.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _pipeline_export_log_type(config: dict[str, Any], pipeline_name: str) -> str:
    pipeline = config["service"]["pipelines"][pipeline_name]
    exporter_name = pipeline["exporters"][0]
    log_type = config["exporters"][exporter_name]["log_type"]
    assert isinstance(log_type, str)
    return log_type


def test_config_parses_and_has_expected_top_level_sections() -> None:
    config = load_ops_agent_config()

    assert set(config) == {"receivers", "processors", "exporters", "service"}


def test_both_classified_pipelines_are_defined() -> None:
    pipelines = set(load_ops_agent_config()["service"]["pipelines"])

    assert pipelines == {"gateway_classified", "caddy_classified"}


def test_gateway_pipeline_tails_docker_and_parses_json() -> None:
    config = load_ops_agent_config()
    pipeline = config["service"]["pipelines"]["gateway_classified"]
    receiver = config["receivers"][pipeline["receivers"][0]]
    processor = config["processors"][pipeline["processors"][0]]

    assert DOCKER_CONTAINER_LOGS_GLOB in receiver["include_paths"]
    assert processor == {"type": "parse_json", "parse_from": "log"}


def test_pipelines_export_to_classified_log_types() -> None:
    config = load_ops_agent_config()

    assert _pipeline_export_log_type(config, "gateway_classified") == GATEWAY_CLASSIFIED_LOG_TYPE
    assert _pipeline_export_log_type(config, "caddy_classified") == CADDY_CLASSIFIED_LOG_TYPE


def test_caddyfile_keeps_json_logs_and_echoes_request_id_upstream() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")

    assert "output stdout" in text
    assert "format json" in text
    directive = "header_up X-Request-Id {http.request.header.X-Request-Id}"
    assert text.count(directive) == 5


def test_startup_embeds_byte_exact_ops_agent_config() -> None:
    startup_text = STARTUP.read_text(encoding="utf-8")
    match = EMBEDDED_CFG_PATTERN.search(startup_text)

    assert match is not None
    embedded = match.group(1).rstrip("\n") + "\n"
    assert embedded == OPS_AGENT_CONFIG.read_text(encoding="utf-8")


def test_startup_validates_before_install_and_restart() -> None:
    startup_text = STARTUP.read_text(encoding="utf-8")
    validate_index = startup_text.index("ops-agent-ctl validate-config")
    install_index = startup_text.index(
        "install -m 0644 /opt/zeler-platform/ops-agent-config.yaml"
    )
    restart_index = startup_text.index("systemctl restart google-cloud-ops-agent")

    assert validate_index < install_index < restart_index


def test_startup_keeps_prior_config_when_validation_fails() -> None:
    assert "prior config kept" in STARTUP.read_text(encoding="utf-8")
