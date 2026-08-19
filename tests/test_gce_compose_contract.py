"""
Contract tests for GCE infra artifacts: docker-compose.yml, Caddyfile, env-templates.

Task 1.7: Compose contract
  (10 active services, no :latest, network, private Mongo port, caddy ports).
Task 1.8: Caddyfile contract (5 active site blocks + retired Fulldock parking under zeler.ai only).
Task 1.9: Env-template contract (required keys per service per design §7).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
INFRA_GCE = PROJECT_ROOT / "infra" / "gce"
COMPOSE_FILE = INFRA_GCE / "docker-compose.yml"
CADDYFILE = INFRA_GCE / "Caddyfile"
ENV_TEMPLATES_DIR = INFRA_GCE / "env-templates"
SECRETS_SCRIPT = INFRA_GCE / "zeler-platform-secrets.sh"
STARTUP_SCRIPT = INFRA_GCE / "platform-vm-startup.sh"
DOCKER_MAINTENANCE_SCRIPT = INFRA_GCE / "docker-maintenance.sh"
DOCKER_DEPLOY_PREFLIGHT_SCRIPT = INFRA_GCE / "docker-deploy-preflight.sh"
DEVOLUCIONES_TOPOLOGY_WRAPPER = INFRA_GCE / "zelerdata-devoluciones-topology.sh"
SMOKE_ENV_VARIABLE_PATTERN = re.compile(r"\bZELERDATA_SMOKE_[A-Z0-9_]+\b")

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
}

EXPECTED_SUBDOMAINS = {
    "gateway.zeler.ai",
    "sheets.zeler.ai",
    "repricer.zeler.ai",
    "publicador.zeler.ai",
    "autoreply.zeler.ai",
}
PARKED_SUBDOMAINS = {"fulldock.zeler.ai"}

SCOPED_GATEWAY_TOKEN_ENV_TEMPLATES = (
    "gateway",
    "repricer-api",
    "sheets-api",
    "publicador-api",
    "autoreply-api",
    "repricer-worker",
    "sheets-worker",
    "autoreply-worker",
)

WORKER_RUN_ENTRY_TESTS = (
    PROJECT_ROOT / "modules" / "repricer" / "tests" / "test_repricer_run_entry.py",
    PROJECT_ROOT / "modules" / "sheets" / "tests" / "test_sheets_run_entry.py",
    PROJECT_ROOT / "modules" / "autoreply" / "tests" / "test_autoreply_run_entry.py",
)

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
        "OAUTH_SUCCESS_URL",
        "KMS_MELI_TOKENS_KEY",
        "KMS_PLATFORM_JWT_KEY",
        "ZELER_APP_BROKER_SECRET",
        "MELI_ALLOWED_IPS",
    },
    "repricer-api": BASE_KEYS,
    "publicador-api": BASE_KEYS,
    "autoreply-api": BASE_KEYS,
    "sheets-api": BASE_KEYS
    | {
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "EXTENSION_TOKEN_PEPPER",
        "KMS_GOOGLE_TOKENS_KEY",
    },
    "sheets-worker": BASE_KEYS
    | {
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "KMS_GOOGLE_TOKENS_KEY",
        "GATEWAY_BASE_URL",
        "RABBITMQ_MANAGEMENT_URL",
        "GATEWAY_URL",
        "SHEETS_URL",
    },
    "repricer-worker": BASE_KEYS | {"GATEWAY_BASE_URL"},
    "autoreply-worker": BASE_KEYS | {"GATEWAY_BASE_URL"},
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

    def test_compose_declares_exactly_10_active_services(self) -> None:
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

    def test_mongo_publishes_only_private_bind_port(self) -> None:
        data = load_compose()
        mongo_cfg = data["services"]["mongo"]
        assert mongo_cfg.get("ports") == ["${MONGO_PRIVATE_BIND_IP:-127.0.0.1}:27017:27017"]

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

    def test_sheets_worker_has_local_healthcheck_and_restart_safe_policy(self) -> None:
        sheets_worker = load_compose()["services"]["sheets-worker"]

        assert sheets_worker["restart"] == "unless-stopped"
        healthcheck = sheets_worker["healthcheck"]
        assert healthcheck["test"][0:2] == ["CMD", "python"]
        assert "http://127.0.0.1:8080/health" in healthcheck["test"][3]
        assert healthcheck["interval"] == "10s"
        assert healthcheck["timeout"] == "3s"
        assert healthcheck["retries"] == 6

    def test_sheets_dlq_snapshot_mount_and_startup_install_are_root_only(self) -> None:
        snapshot_path = "/var/lib/zeler-platform/sheets-dlq-snapshot"
        compose = load_compose()["services"]
        worker = compose["sheets-worker"]
        startup = STARTUP_SCRIPT.read_text(encoding="utf-8")
        wrapper = (INFRA_GCE / "sheets-dlq-snapshot-execute.sh").read_text(encoding="utf-8")

        assert worker.get("volumes") == [
            {"type": "bind", "source": snapshot_path, "target": snapshot_path, "read_only": False}
        ]
        assert "volumes" not in compose["sheets-api"]
        assert "user" not in worker
        assert "install -d -o root -g root -m 0700" in startup
        assert snapshot_path in startup
        assert "/opt/zeler-platform/sheets-dlq-snapshot-execute.sh" in startup
        assert "install -m 0755" in startup
        assert wrapper.strip() in startup

    @pytest.mark.parametrize("path", (SECRETS_SCRIPT, COMPOSE_FILE))
    def test_materializer_and_compose_boundary_has_no_smoke_variables(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")

        assert sorted(set(SMOKE_ENV_VARIABLE_PATTERN.findall(text))) == []


# ===========================================================================
# Task 1.8 — Caddyfile contract
# ===========================================================================


class TestCaddyfileContract:
    def test_caddyfile_exists(self) -> None:
        assert CADDYFILE.exists(), f"Missing: {CADDYFILE}"

    def test_caddyfile_has_exactly_5_active_site_blocks_and_retired_parking(self) -> None:
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
        assert found == EXPECTED_SUBDOMAINS | PARKED_SUBDOMAINS, (
            f"Expected site blocks {(EXPECTED_SUBDOMAINS | PARKED_SUBDOMAINS)!r}, got {found!r}"
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
        }
        for subdomain, upstream in expected_upstreams.items():
            assert upstream in text, (
                f"Caddyfile missing reverse_proxy to {upstream!r} (expected for {subdomain})"
            )

    def test_retired_fulldock_hostname_is_parked_not_proxied(self) -> None:
        text = CADDYFILE.read_text()

        assert "fulldock.zeler.ai" in text
        assert 'respond "Fulldock is decommissioned" 410' in text
        assert "fulldock-api" not in text

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

    @pytest.mark.parametrize("service", SCOPED_GATEWAY_TOKEN_ENV_TEMPLATES)
    def test_scoped_env_templates_do_not_declare_gateway_token(self, service: str) -> None:
        keys = load_template_keys(service)
        assert "GATEWAY_TOKEN" not in keys, (
            f"{service}.env.template must not declare deprecated GATEWAY_TOKEN; "
            "scoped services use minted JWT/KMS gateway auth"
        )

    @pytest.mark.parametrize(
        "forbidden",
        ("platform-gateway-token", "GATEWAY_INTERNAL_TOKEN", "GATEWAY_TOKEN="),
    )
    def test_secrets_script_does_not_emit_deprecated_gateway_token(self, forbidden: str) -> None:
        text = SECRETS_SCRIPT.read_text()
        assert forbidden not in text, (
            f"{SECRETS_SCRIPT.name} must not contain deprecated scoped gateway token "
            f"pattern {forbidden!r}"
        )

    def test_secrets_script_emits_gateway_proxy_base_url(self) -> None:
        text = SECRETS_SCRIPT.read_text()

        assert "GATEWAY_PROXY_BASE_URL=http://gateway:8080/proxy/meli" in text
        assert "GATEWAY_BASE_URL=$GATEWAY_PROXY_BASE_URL" in text
        assert 'GATEWAY_BASE_URL=http://gateway:8080"' not in text

    def test_sheets_worker_emits_explicit_preflight_service_targets(self) -> None:
        text = SECRETS_SCRIPT.read_text()
        sheets_worker_section = text.split("# sheets-worker", 1)[1].split("# Workers", 1)[0]

        assert "RABBITMQ_MANAGEMENT_URL=$(s cloudamqp-management-url)" in text
        assert '"RABBITMQ_MANAGEMENT_URL=$RABBITMQ_MANAGEMENT_URL"' in sheets_worker_section
        assert '"GATEWAY_URL=$GATEWAY_SERVICE_ROOT_URL"' in sheets_worker_section
        assert '"SHEETS_URL=$SHEETS_API_SERVICE_ROOT_URL"' in sheets_worker_section

    def test_sheets_worker_preflight_targets_do_not_reuse_proxy_or_transport_urls(self) -> None:
        text = SECRETS_SCRIPT.read_text()
        sheets_worker_section = text.split("# sheets-worker", 1)[1].split("# Workers", 1)[0]

        assert "GATEWAY_SERVICE_ROOT_URL=http://gateway:8080" in text
        assert "SHEETS_API_SERVICE_ROOT_URL=http://sheets-api:8080" in text
        assert '"RABBITMQ_MANAGEMENT_URL=$RABBITMQ_URL"' not in sheets_worker_section
        assert '"GATEWAY_URL=$GATEWAY_PROXY_BASE_URL"' not in sheets_worker_section
        assert "/proxy/meli" not in "\n".join(
            line for line in sheets_worker_section.splitlines() if "GATEWAY_URL=" in line
        )

    def test_sheets_worker_rendered_env_keeps_preflight_targets_separate(
        self, tmp_path: Path
    ) -> None:
        env_dir = tmp_path / "env"
        fake_gcloud = tmp_path / "gcloud"
        fake_gcloud.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  *--secret=cloudamqp-management-url*) printf '%s' 'https://management.test' ;;\n"
            "  *--secret=cloudamqp-url*) printf '%s' 'amqps://transport.test' ;;\n"
            "  *) printf '%s' 'placeholder' ;;\n"
            "esac\n"
        )
        fake_gcloud.chmod(0o755)
        sandboxed_script = tmp_path / SECRETS_SCRIPT.name
        sandboxed_script.write_text(
            SECRETS_SCRIPT.read_text().replace(
                "ENV_DIR=/opt/zeler-platform/env", f"ENV_DIR={env_dir}"
            )
        )

        completed = subprocess.run(  # noqa: S603 - test executes its sandboxed copy of a checked-in script.
            ["/bin/bash", str(sandboxed_script)],
            capture_output=True,
            check=False,
            env={"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
            text=True,
        )

        assert completed.returncode == 0, completed.stderr
        values = dict(
            line.split("=", 1)
            for line in (env_dir / "sheets-worker.env").read_text().splitlines()
            if line and not line.startswith("#")
        )
        assert values["RABBITMQ_MANAGEMENT_URL"] == "https://management.test"
        assert values["GATEWAY_URL"] == "http://gateway:8080"
        assert values["SHEETS_URL"] == "http://sheets-api:8080"
        assert values["SHEETS_SYNC_JOBS_POLLER_ENABLED"] == "true"
        assert values["RABBITMQ_MANAGEMENT_URL"] != values["RABBITMQ_URL"]
        assert values["GATEWAY_URL"] != values["GATEWAY_BASE_URL"]

    def test_sheets_worker_template_enables_sync_jobs_poller(self) -> None:
        template = (ENV_TEMPLATES_DIR / "sheets-worker.env.template").read_text()

        assert "SHEETS_SYNC_JOBS_POLLER_ENABLED=true" in template

    def test_secrets_script_fetches_zeler_app_broker_secret_for_gateway_only(self) -> None:
        text = SECRETS_SCRIPT.read_text()

        assert "ZELER_APP_BROKER_SECRET=$(s zeler-app-broker-secret)" in text
        assert "ZELER_APP_BROKER_SECRET=$ZELER_APP_BROKER_SECRET" in text
        module_api_section = text.split("# Module APIs", 1)[1]
        assert "ZELER_APP_BROKER_SECRET" not in module_api_section

    def test_gateway_oauth_success_url_points_to_live_app_linked_accounts(self) -> None:
        expected = "OAUTH_SUCCESS_URL=https://app.zeler.ai/accounts/linked"

        assert expected in (ENV_TEMPLATES_DIR / "gateway.env.template").read_text()
        assert f'"{expected}"' in SECRETS_SCRIPT.read_text()

    def test_gateway_webhook_allowlist_is_fetched_from_secret_manager(self) -> None:
        text = SECRETS_SCRIPT.read_text()

        assert "MELI_ALLOWED_IPS=$(s meli-allowed-ips)" in text
        assert "MELI_ALLOWED_IPS=$MELI_ALLOWED_IPS" in text
        assert (
            "MELI_ALLOWED_IPS=__PLACEHOLDER__"
            in (ENV_TEMPLATES_DIR / "gateway.env.template").read_text()
        )

    def test_deploy_runbook_documents_zeler_app_live_validation(self) -> None:
        text = (PROJECT_ROOT / "docs" / "deploy.md").read_text()

        required_snippets = [
            "## 5c. zeler-app live integration runtime config + VM-only validation",
            "ZELER_APP_BROKER_SECRET",
            "zeler-app-broker-secret",
            "OAUTH_SUCCESS_URL",
            "https://app.zeler.ai/accounts/linked",
            "https://gateway.zeler.ai",
            "https://repricer.zeler.ai",
            "https://sheets.zeler.ai",
            "https://publicador.zeler.ai",
            "https://autoreply.zeler.ai",
            "platform-vm",
            "us-central1-a",
            "zeler-platform-dev",
            "ensure_zeler_app_admin_client",
            "Do not print MONGO_URI",
            "seller `82453304`",
        ]
        for snippet in required_snippets:
            assert snippet in text

    @pytest.mark.parametrize("path", WORKER_RUN_ENTRY_TESTS)
    def test_worker_run_entry_tests_do_not_set_gateway_token(self, path: Path) -> None:
        text = path.read_text()
        assert 'setenv("GATEWAY_TOKEN"' not in text, (
            f"{path.relative_to(PROJECT_ROOT)} must not set deprecated GATEWAY_TOKEN"
        )

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

    def test_secrets_script_fetches_extension_token_pepper_for_sheets_api_only(self) -> None:
        text = SECRETS_SCRIPT.read_text()

        assert "EXTENSION_TOKEN_PEPPER=$(s extension-token-pepper)" in text
        sheets_api_section = text.split("# sheets-api", 1)[1].split("# sheets-worker", 1)[0]
        assert "EXTENSION_TOKEN_PEPPER=$EXTENSION_TOKEN_PEPPER" in sheets_api_section
        sheets_worker_section = text.split("# sheets-worker", 1)[1]
        assert "EXTENSION_TOKEN_PEPPER" not in sheets_worker_section

    def test_mongo_template_has_init_credentials(self) -> None:
        keys = load_template_keys("mongo")
        assert "MONGO_INITDB_ROOT_USERNAME" in keys
        assert "MONGO_INITDB_ROOT_PASSWORD" in keys


# ===========================================================================
# Ops hardening — platform-vm root disk safeguards
# ===========================================================================


class TestDockerRootDiskSafeguards:
    @pytest.mark.parametrize(
        "path",
        (DOCKER_MAINTENANCE_SCRIPT, DOCKER_DEPLOY_PREFLIGHT_SCRIPT, STARTUP_SCRIPT),
    )
    def test_docker_maintenance_artifacts_never_prune_volumes(self, path: Path) -> None:
        text = path.read_text()

        forbidden_patterns = (
            "docker volume prune",
            "docker system prune --volumes",
            "docker system prune -a --volumes",
            "--volumes",
        )
        for forbidden in forbidden_patterns:
            assert forbidden not in text, (
                f"{path.relative_to(PROJECT_ROOT)} must not prune Docker volumes; "
                "Mongo data lives on /var/lib/zeler-mongo"
            )

    def test_maintenance_script_prunes_only_safe_docker_objects_with_retention(self) -> None:
        text = DOCKER_MAINTENANCE_SCRIPT.read_text()

        assert "DOCKER_PRUNE_UNTIL=${DOCKER_PRUNE_UNTIL:-72h}" in text
        assert "docker container prune" in text
        assert "docker image prune" in text
        assert "docker builder prune" in text
        assert "until=$DOCKER_PRUNE_UNTIL" in text
        assert "docker system df" in text
        assert "df -h /" in text

    def test_deploy_preflight_checks_root_free_space_then_runs_safe_cleanup(self) -> None:
        text = DOCKER_DEPLOY_PREFLIGHT_SCRIPT.read_text()

        assert "MIN_FREE_GIB=${MIN_FREE_GIB:-5}" in text
        assert "df -Pk /" in text
        assert "/opt/zeler-platform/docker-maintenance.sh" in text
        assert "50GB" in text
        assert "cleanup cannot maintain" in text

    def test_startup_installs_log_rotation_and_maintenance_timer(self) -> None:
        text = STARTUP_SCRIPT.read_text()

        assert "/etc/docker/daemon.json" in text
        assert '"log-driver": "local"' in text
        assert '"max-size": "50m"' in text
        assert '"max-file": "5"' in text
        assert "cmp -s" in text
        assert "/opt/zeler-platform/docker-maintenance.sh" in text
        assert "/opt/zeler-platform/docker-deploy-preflight.sh" in text
        assert "zeler-docker-maintenance.service" in text
        assert "zeler-docker-maintenance.timer" in text
        assert "systemctl enable --now zeler-docker-maintenance.timer" in text

    def test_exact_devoluciones_topology_wrapper_is_installed_without_startup_mutation(
        self,
    ) -> None:
        wrapper = DEVOLUCIONES_TOPOLOGY_WRAPPER.read_text()
        startup = STARTUP_SCRIPT.read_text()

        assert "set -euo pipefail" in wrapper
        assert 'cd "$PLATFORM_ROOT"' in wrapper
        assert "/opt/zeler-platform/.venv/bin/python" not in wrapper
        assert 'docker compose --file "$COMPOSE_FILE" run --rm --no-deps -T' in wrapper
        assert "--user 0:0" in wrapper
        assert "--entrypoint /app/.venv/bin/python" in wrapper
        assert "/var/run/docker.sock:/var/run/docker.sock" in wrapper
        assert "-m infra.rabbitmq.sheets_devoluciones_topology" in wrapper
        assert '[[ "$command" == "bind-claims"' in wrapper
        assert "rollback --execute --failure-triggered" in wrapper
        assert "/opt/zeler-platform/zelerdata-devoluciones-topology.sh" in startup
        assert wrapper.strip() in startup
        assert "prestart --execute" not in startup
        assert "bind-claims --execute" not in startup

    def test_deploy_runbook_runs_preflight_before_single_service_pull(self) -> None:
        text = (PROJECT_ROOT / "docs" / "deploy.md").read_text()

        deploy_section = text.split("## 5. Re-deploy a Single Service", 1)[1].split("---", 1)[0]
        assert "/opt/zeler-platform/docker-deploy-preflight.sh" in deploy_section
        assert deploy_section.index(
            "/opt/zeler-platform/docker-deploy-preflight.sh"
        ) < deploy_section.index('docker compose --file "$COMPOSE_FILE" pull "$SERVICE"')
        assert "never prune volumes" in text.lower()
        assert "/var/lib/zeler-mongo" in text
