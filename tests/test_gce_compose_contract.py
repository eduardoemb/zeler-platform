"""
Contract tests for GCE infra artifacts: docker-compose.yml, Caddyfile, env-templates.

Task 1.7: Compose contract (12 services, no :latest, network, mongo no ports, caddy ports).
Task 1.8: Caddyfile contract (6 site blocks under zeler.ai only).
Task 1.9: Env-template contract (required keys per service per design §7).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

INFRA_GCE = Path(__file__).parent.parent / "infra" / "gce"
COMPOSE_FILE = INFRA_GCE / "docker-compose.yml"
CADDYFILE = INFRA_GCE / "Caddyfile"
ENV_TEMPLATES_DIR = INFRA_GCE / "env-templates"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_SERVICES = {
    "mongo",
    "caddy",
    "gateway",
    "repricer-api",
    "repricer-worker",
    "sheets-api",
    "sheets-worker",
    "publicador-api",
    "autoreply-api",
    "autoreply-worker",
    "fulldock-api",
    "fulldock-worker",
}

EXPECTED_SUBDOMAINS = {
    "gateway.zeler.ai",
    "sheets.zeler.ai",
    "repricer.zeler.ai",
    "publicador.zeler.ai",
    "autoreply.zeler.ai",
    "fulldock.zeler.ai",
}

# Design §7 — required keys per service (beyond BASE where applicable).
# BASE = MONGO_URI, MONGO_DB, RABBITMQ_URL, GOOGLE_CLOUD_PROJECT,
#        KMS_PROJECT_ID, KMS_LOCATION, KMS_KEYRING
BASE_KEYS = {
    "MONGO_URI",
    "MONGO_DB",
    "RABBITMQ_URL",
    "GOOGLE_CLOUD_PROJECT",
    "KMS_PROJECT_ID",
    "KMS_LOCATION",
    "KMS_KEYRING",
}

SERVICE_REQUIRED_KEYS: dict[str, set[str]] = {
    "mongo": {"MONGO_INITDB_ROOT_USERNAME", "MONGO_INITDB_ROOT_PASSWORD"},
    "caddy": set(),  # no secret vars; placeholder template only
    "gateway": BASE_KEYS
    | {
        "MELI_CLIENT_ID",
        "MELI_CLIENT_SECRET",
        "MELI_REDIRECT_URI",
        "KMS_MELI_TOKENS_KEY",
        "KMS_PLATFORM_JWT_KEY",
    },
    "repricer-api": BASE_KEYS,
    "publicador-api": BASE_KEYS,
    "autoreply-api": BASE_KEYS,
    "fulldock-api": BASE_KEYS,
    "sheets-api": BASE_KEYS
    | {
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "KMS_GOOGLE_TOKENS_KEY",
    },
    "sheets-worker": BASE_KEYS
    | {
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "KMS_GOOGLE_TOKENS_KEY",
    },
    "repricer-worker": BASE_KEYS | {"GATEWAY_BASE_URL", "GATEWAY_TOKEN"},
    "autoreply-worker": BASE_KEYS | {"GATEWAY_BASE_URL", "GATEWAY_TOKEN"},
    "fulldock-worker": BASE_KEYS | {"GATEWAY_BASE_URL", "GATEWAY_TOKEN"},
}


def load_compose() -> dict:  # type: ignore[type-arg]
    with COMPOSE_FILE.open() as fh:
        return yaml.safe_load(fh)  # type: ignore[no-any-return]


def load_template_keys(service: str) -> set[str]:
    path = ENV_TEMPLATES_DIR / f"{service}.env.template"
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


# ===========================================================================
# Task 1.7 — Compose contract
# ===========================================================================


class TestComposeServices:
    def test_compose_file_exists(self) -> None:
        assert COMPOSE_FILE.exists(), f"Missing: {COMPOSE_FILE}"

    def test_compose_declares_exactly_12_services(self) -> None:
        data = load_compose()
        services = set(data.get("services", {}).keys())
        assert services == EXPECTED_SERVICES, f"Expected {EXPECTED_SERVICES!r}, got {services!r}"

    def test_no_latest_image_tag(self) -> None:
        data = load_compose()
        latest_culprits: list[str] = []
        for svc_name, svc_cfg in data.get("services", {}).items():
            img = svc_cfg.get("image", "")
            if isinstance(img, str) and ":latest" in img:
                latest_culprits.append(svc_name)
        assert latest_culprits == [], f"Services using :latest: {latest_culprits}"

    def test_all_services_on_platform_default_network(self) -> None:
        data = load_compose()
        missing_network: list[str] = []
        for svc_name, svc_cfg in data.get("services", {}).items():
            nets = svc_cfg.get("networks", [])
            if "platform_default" not in nets:
                missing_network.append(svc_name)
        assert missing_network == [], (
            f"Services missing 'platform_default' network: {missing_network}"
        )

    def test_mongo_has_no_host_ports(self) -> None:
        data = load_compose()
        mongo_cfg = data["services"]["mongo"]
        assert "ports" not in mongo_cfg, (
            f"mongo service MUST NOT publish ports to host (found: {mongo_cfg.get('ports')})"
        )

    def test_caddy_publishes_only_80_and_443(self) -> None:
        data = load_compose()
        caddy_ports = data["services"]["caddy"].get("ports", [])
        # Normalize to set of strings like "80:80", "443:443"
        port_strings = set()
        for p in caddy_ports:
            port_strings.add(str(p))
        assert "80:80" in port_strings, f"Caddy missing port 80:80, got {port_strings}"
        assert "443:443" in port_strings, f"Caddy missing port 443:443, got {port_strings}"
        # No other services should have ports 80/443
        for svc_name, svc_cfg in data["services"].items():
            if svc_name == "caddy":
                continue
            svc_ports = svc_cfg.get("ports", [])
            for p in svc_ports:
                ps = str(p)
                assert "80" not in ps and "443" not in ps, (
                    f"Service {svc_name!r} unexpectedly binds port 80/443: {ps}"
                )

    def test_all_services_have_restart_unless_stopped(self) -> None:
        data = load_compose()
        bad: list[str] = []
        for svc_name, svc_cfg in data.get("services", {}).items():
            if svc_cfg.get("restart") != "unless-stopped":
                bad.append(svc_name)
        assert bad == [], f"Services missing 'restart: unless-stopped': {bad}"

    def test_platform_default_network_declared(self) -> None:
        data = load_compose()
        networks = data.get("networks", {})
        assert "platform_default" in networks, (
            f"Top-level network 'platform_default' not declared; got: {list(networks.keys())}"
        )


# ===========================================================================
# Task 1.8 — Caddyfile contract
# ===========================================================================


class TestCaddyfileContract:
    def test_caddyfile_exists(self) -> None:
        assert CADDYFILE.exists(), f"Missing: {CADDYFILE}"

    def test_caddyfile_has_exactly_6_site_blocks(self) -> None:
        text = CADDYFILE.read_text()
        # Site blocks start with a hostname at line-start (not inside braces/snippets).
        # Pattern: lines that are "<hostname> {" (site block headers).
        # Exclude snippet definitions like "(common) {" and global block "{"
        site_block_pattern = re.compile(
            r"^([a-zA-Z0-9][a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\s*\{",
            re.MULTILINE,
        )
        matches = site_block_pattern.findall(text)
        found = set(matches)
        assert found == EXPECTED_SUBDOMAINS, (
            f"Expected site blocks {EXPECTED_SUBDOMAINS!r}, got {found!r}"
        )

    def test_caddyfile_only_zeler_ai_domains(self) -> None:
        text = CADDYFILE.read_text()
        # Any domain-like token that is NOT under zeler.ai is a violation
        site_block_pattern = re.compile(
            r"^([a-zA-Z0-9][a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\s*\{",
            re.MULTILINE,
        )
        for match in site_block_pattern.finditer(text):
            domain = match.group(1)
            assert domain.endswith(".zeler.ai"), (
                f"Non-zeler.ai domain found in Caddyfile site block: {domain!r}"
            )

    def test_caddyfile_each_subdomain_proxies_correct_upstream(self) -> None:
        text = CADDYFILE.read_text()
        expected_upstreams = {
            "gateway.zeler.ai": "gateway:8080",
            "sheets.zeler.ai": "sheets-api:8080",
            "repricer.zeler.ai": "repricer-api:8080",
            "publicador.zeler.ai": "publicador-api:8080",
            "autoreply.zeler.ai": "autoreply-api:8080",
            "fulldock.zeler.ai": "fulldock-api:8080",
        }
        for subdomain, upstream in expected_upstreams.items():
            assert upstream in text, (
                f"Caddyfile missing reverse_proxy to {upstream!r} (expected for {subdomain})"
            )

    def test_caddyfile_has_global_email(self) -> None:
        text = CADDYFILE.read_text()
        assert "ops@zeler.ai" in text, "Caddyfile missing global email ops@zeler.ai"


# ===========================================================================
# Task 1.9 — Env-template contract
# ===========================================================================


class TestEnvTemplateContract:
    def test_env_templates_dir_exists(self) -> None:
        assert ENV_TEMPLATES_DIR.exists(), f"Missing dir: {ENV_TEMPLATES_DIR}"

    @pytest.mark.parametrize("service", list(SERVICE_REQUIRED_KEYS.keys()))
    def test_env_template_exists(self, service: str) -> None:
        path = ENV_TEMPLATES_DIR / f"{service}.env.template"
        assert path.exists(), f"Missing env template: {path}"

    @pytest.mark.parametrize("service,required", list(SERVICE_REQUIRED_KEYS.items()))
    def test_env_template_has_required_keys(self, service: str, required: set[str]) -> None:
        if not required:
            pytest.skip(f"No required keys for {service}")
        path = ENV_TEMPLATES_DIR / f"{service}.env.template"
        if not path.exists():
            pytest.fail(f"Template missing: {path}")
        keys = load_template_keys(service)
        missing = required - keys
        assert not missing, f"Template {service}.env.template missing keys: {sorted(missing)}"

    def test_gateway_template_has_gateway_token(self) -> None:
        """Gateway validates the internal token — it must be in its template."""
        keys = load_template_keys("gateway")
        assert "GATEWAY_TOKEN" in keys, (
            "gateway.env.template must include GATEWAY_TOKEN "
            "(gateway validates bearer on proxy calls)"
        )

    def test_worker_templates_have_gateway_token(self) -> None:
        workers = ["repricer-worker", "autoreply-worker", "fulldock-worker"]
        for worker in workers:
            keys = load_template_keys(worker)
            assert "GATEWAY_TOKEN" in keys, f"{worker}.env.template missing GATEWAY_TOKEN"

    def test_sheets_templates_have_google_oauth_keys(self) -> None:
        google_keys = (
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_REDIRECT_URI",
        )
        for svc in ("sheets-api", "sheets-worker"):
            keys = load_template_keys(svc)
            for k in google_keys:
                assert k in keys, f"{svc}.env.template missing {k}"

    def test_mongo_template_has_init_credentials(self) -> None:
        keys = load_template_keys("mongo")
        assert "MONGO_INITDB_ROOT_USERNAME" in keys
        assert "MONGO_INITDB_ROOT_PASSWORD" in keys
