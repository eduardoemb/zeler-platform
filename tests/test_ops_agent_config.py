"""Ops Agent, Caddy, and startup classified-log configuration contracts."""

from __future__ import annotations

import json
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


CADDY_SENSITIVE_FIELDS = (
    "jsonPayload.request.headers",
    "jsonPayload.request.uri",
    "jsonPayload.resp_headers",
)


def _redaction_processor(config: dict[str, Any]) -> dict[str, Any]:
    pipeline = config["service"]["pipelines"]["caddy_classified"]
    for name in pipeline["processors"]:
        processor = config["processors"][name]
        if processor["type"] == "modify_fields":
            return processor
    raise AssertionError("caddy pipeline has no modify_fields processor")


def _lookup_path(entry: dict[str, Any], path: str) -> Any:
    node: Any = entry
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _unset_path(entry: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    node: Any = entry
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def _simulated_caddy_entry(config: dict[str, Any]) -> dict[str, Any]:
    parsed = {
        "request": {
            "method": "GET",
            "host": "gateway.zeler.ai",
            "uri": "/?token=SECRET_QUERY",
            "headers": {
                "Authorization": ["Bearer synthetic.jwt"],
                "Cookie": ["session=abc123"],
                "X-Request-Id": ["req-123"],
            },
        },
        "resp_headers": {"Set-Cookie": ["sid=xyz789"]},
        "status": 200,
        "duration": 0.0123,
    }
    entry: dict[str, Any] = {"jsonPayload": json.loads(json.dumps(parsed))}
    for field_path, ops in _redaction_processor(config)["fields"].items():
        value = _lookup_path(entry, field_path)
        map_values = ops.get("map_values") or {}
        if ops.get("map_values_exclusive") is True and all(
            value != key for key in map_values
        ):
            _unset_path(entry, field_path)
    return entry


def test_caddy_pipeline_parses_then_redacts_exactly_three_fields() -> None:
    config = load_ops_agent_config()
    pipeline = config["service"]["pipelines"]["caddy_classified"]
    processors = [config["processors"][name] for name in pipeline["processors"]]

    assert [processor["type"] for processor in processors] == ["parse_json", "modify_fields"]
    redaction = processors[1]
    assert set(redaction["fields"]) == set(CADDY_SENSITIVE_FIELDS)
    for field in CADDY_SENSITIVE_FIELDS:
        assert redaction["fields"][field] == {
            "map_values": {},
            "map_values_exclusive": True,
        }


def test_gateway_pipeline_remains_single_parse_processor() -> None:
    config = load_ops_agent_config()
    pipeline = config["service"]["pipelines"]["gateway_classified"]

    assert len(pipeline["processors"]) == 1
    assert config["processors"][pipeline["processors"][0]]["type"] == "parse_json"


def test_simulated_caddy_entry_removes_sensitive_values_and_keeps_diagnostics() -> None:
    payload = _simulated_caddy_entry(load_ops_agent_config())
    text = json.dumps(payload)

    assert "synthetic.jwt" not in text
    assert "abc123" not in text
    assert "xyz789" not in text
    assert "SECRET_QUERY" not in text
    assert "headers" not in text
    assert "resp_headers" not in text
    assert payload["jsonPayload"]["request"]["method"] == "GET"
    assert payload["jsonPayload"]["request"]["host"] == "gateway.zeler.ai"
    assert payload["jsonPayload"]["status"] == 200
    assert payload["jsonPayload"]["duration"] == 0.0123
