from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from zeler_sheets.formulas.runtime_states import get_formula_runtime_states

REPO_ROOT = Path(__file__).parents[3]
CONTRACT_PATH = REPO_ROOT / "tests" / "sheets" / "fixtures" / "sheetseller_formula_contracts.json"
ADDON_DIR = REPO_ROOT / "modules" / "sheets" / "apps_script" / "sheetseller"
MARKETPLACE_DOC_PATH = REPO_ROOT / "docs" / "sheets" / "zelerdata-marketplace-publication.md"
FORMULAS_DOC_PATH = REPO_ROOT / "docs" / "sheets" / "zelerdata-formulas.md"


def _contracts() -> list[dict[str, Any]]:
    loaded = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["contracts"]
    return cast("list[dict[str, Any]]", loaded)


def _canonical_formula_name(legacy_name: str) -> str:
    if legacy_name == "ZELERDATA_ENVIARAFULL":
        return "ZELERDATA_ENVIARAFULL"
    if legacy_name == "ZELERDATA_OBTENER_CATALOGO":
        return "ZELERDATA_OBTENER_CATALOGO"
    return legacy_name.replace("ZELERDATA_", "ZELERDATA_")


def _read_addon_file(name: str) -> str:
    return (ADDON_DIR / name).read_text(encoding="utf-8")


def _read_project_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _formula_names_by_runtime_state(runtime_state: str) -> list[str]:
    return sorted(
        formula_name
        for formula_name, state in get_formula_runtime_states().items()
        if state.state == runtime_state
    )


def _supported_formula_names() -> list[str]:
    return _formula_names_by_runtime_state("implemented")


def _unsupported_formula_names() -> list[str]:
    return _formula_names_by_runtime_state("unsupported")


def _markdown_section(docs: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<section>.*?)(?=^##\s+|\Z)",
        docs,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"missing docs section: {heading}"
    return match.group("section")


def _documented_formula_names(section: str) -> set[str]:
    return set(re.findall(r"`(ZELERDATA_[A-Z0-9_]+)`", section))


def _signature_parameters(signature: str) -> list[str]:
    body = signature.removeprefix("(").removesuffix(")")
    if not body:
        return []
    return [part.strip() for part in body.split(", ")]


def _parameter_name(parameter: str) -> str:
    return parameter.split("=", maxsplit=1)[0].strip()


def _function_arguments(source: str, function_name: str) -> str:
    match = re.search(rf"function\s+{re.escape(function_name)}\s*\(([^)]*)\)", source)
    assert match is not None, f"missing Apps Script wrapper for {function_name}"
    return match.group(1)


def test_apps_script_manifest_declares_public_marketplace_runtime_and_minimal_scopes() -> None:
    manifest = json.loads(_read_addon_file("appsscript.json"))

    assert manifest["timeZone"] == "America/Mexico_City"
    assert manifest["runtimeVersion"] == "V8"
    assert manifest["exceptionLogging"] == "STACKDRIVER"
    assert manifest["oauthScopes"] == [
        "https://www.googleapis.com/auth/script.container.ui",
        "https://www.googleapis.com/auth/script.external_request",
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
    ]
    assert set(manifest) == {
        "timeZone",
        "exceptionLogging",
        "runtimeVersion",
        "oauthScopes",
    }


def test_config_ui_stores_only_extension_token_in_user_properties() -> None:
    config_source = _read_addon_file("Config.gs")

    assert "onOpen" in config_source
    assert "showZelerDataSettings" in config_source
    assert "saveZelerDataSettings" in config_source
    assert "clearZelerDataExtensionToken" in config_source
    assert "PropertiesService.getUserProperties()" in config_source
    assert "ZELERDATA_EXTENSION_TOKEN" in config_source
    assert "PropertiesService.getDocumentProperties()" in config_source
    assert "ZELERDATA_API_BASE_URL" in config_source
    assert "UserProperties" in config_source
    assert "DocumentProperties" in config_source
    assert "tokenPrefix" not in config_source
    assert "Stored token prefix" not in config_source
    assert not re.search(r"password|contraseñ|username|usuario", config_source, re.IGNORECASE)


def test_public_addon_install_uses_same_menu_and_sidebar_as_open() -> None:
    config_source = _read_addon_file("Config.gs")

    assert re.search(
        r"function\s+onInstall\s*\(\s*e\s*\)\s*\{\s*onOpen\(e\);\s*\}",
        config_source,
        re.DOTALL,
    )
    assert re.search(r"function\s+onOpen\s*\(\s*e\s*\)", config_source)
    assert '.createMenu("ZelerData")' in config_source
    assert '.setTitle("ZelerData settings")' in config_source
    assert '"ZelerData extension token cleared"' in config_source
    assert '"ZelerData"' in config_source
    assert "ZELERDATA_EXTENSION_TOKEN" in config_source
    assert "ZELERDATA_API_BASE_URL" in config_source
    assert "function showZelerDataSettings" in config_source
    assert "function setZelerDataExtensionToken" in config_source
    assert "private pilot" not in config_source.lower()
    assert "SHEETSELLER_" not in config_source


def test_public_settings_sidebar_guides_marketplace_users_without_endpoint_editing() -> None:
    config_source = _read_addon_file("Config.gs")

    assert "Install ZelerData from Google Workspace Marketplace" in config_source
    assert "https://app.zeler.ai/sheets/config" in config_source
    assert 'ZELERDATA_DEFAULT_API_BASE_URL = "https://sheets.zeler.ai"' in config_source
    assert "https://api.zeler.app" not in config_source
    assert "show-once extension token" in config_source
    assert "Save token" in config_source
    assert "Token saved. You can now use ZELERDATA_* formulas." in config_source
    assert "Never paste tokens into spreadsheet cells" in config_source
    assert "Contact Zeler support" in config_source
    assert 'document.getElementById("apiBaseUrl")' not in config_source
    assert "<input id='apiBaseUrl'" not in config_source


def test_formula_api_client_posts_to_execute_route_with_bearer_token() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "UrlFetchApp.fetch" in client_source
    assert '"/sheets/formulas:execute"' in client_source
    assert "Authorization" in client_source
    assert '"Bearer " + token' in client_source
    assert "muteHttpExceptions: true" in client_source
    assert "JSON.stringify" in client_source
    assert "JSON.parse" in client_source
    assert "zelerdataEnvelopeToValues_" in client_source


def test_formula_api_client_returns_review_safe_auth_network_and_api_errors() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "function zelerdataPublicErrorMessage_(code, message)" in client_source
    assert "TOKEN_MISSING: open ZelerData > Settings" in client_source
    assert "TOKEN_REVOKED: create a new token" in client_source
    assert "SELLER_FORBIDDEN: this token is not authorized" in client_source
    assert "NETWORK_ERROR: ZelerData could not reach the Formula API" in client_source
    assert "SERVICE_UNAVAILABLE: ZelerData could not complete this request" in client_source
    assert "Formula API request failed" not in client_source
    assert "returned invalid JSON" not in client_source


def test_formula_api_envelopes_are_converted_to_sheets_safe_2d_values() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "function zelerdataEnvelopeToValues_(envelope)" in client_source
    assert "Array.isArray(envelope.values)" in client_source
    assert "envelope.values.length === 0" in client_source
    assert 'return [[""]]' in client_source
    assert "return zelerdataCoerce2d_(envelope.values)" in client_source
    assert "DATA_UNAVAILABLE" in client_source
    assert "TOKEN_MISSING" in client_source
    assert "return [[zelerdataPublicErrorMessage_(code, message)]]" in client_source
    assert "function zelerdataCoerce2d_(value)" in client_source
    assert "Sheetseller" not in client_source


def test_all_53_zelerdata_formula_wrappers_preserve_names_and_parameter_order() -> None:
    formulas_source = _read_addon_file("Formulas.gs")

    wrapper_names = re.findall(r"^function\s+([A-Za-z0-9_]+)\s*\(", formulas_source, re.MULTILINE)
    expected_names = [_canonical_formula_name(contract["name"]) for contract in _contracts()]
    expected_lowercase_names = [name.lower() for name in expected_names]

    assert wrapper_names == expected_names + expected_lowercase_names
    for contract in _contracts():
        canonical_name = _canonical_formula_name(contract["name"])
        arguments = _function_arguments(formulas_source, canonical_name)
        actual_names = [
            _parameter_name(part.strip()) for part in arguments.split(",") if part.strip()
        ]
        expected_parameters = _signature_parameters(contract["signature"])
        expected_names_for_formula = [
            _parameter_name(parameter) for parameter in expected_parameters
        ]
        assert actual_names == expected_names_for_formula, canonical_name
        for parameter in expected_parameters:
            if "=" in parameter:
                assert parameter in arguments, canonical_name
        assert _function_arguments(formulas_source, canonical_name.lower()) == arguments
    assert "SHEETSELLER_" not in formulas_source
    assert "sheetseller_" not in formulas_source


def test_canonical_formula_wrappers_expose_google_sheets_autocomplete_jsdoc() -> None:
    formulas_source = _read_addon_file("Formulas.gs")

    assert formulas_source.count("@customfunction") == len(_contracts())
    for contract in _contracts():
        canonical_name = _canonical_formula_name(contract["name"])
        match = re.search(
            rf"/\*\*(?P<doc>.*?)\*/\s*function\s+{re.escape(canonical_name)}\s*\(",
            formulas_source,
            re.DOTALL,
        )
        assert match is not None, canonical_name

        doc = match.group("doc")
        parameters = [
            _parameter_name(parameter) for parameter in _signature_parameters(contract["signature"])
        ]
        assert re.search(r"^\s*\*\s+[^@\s].+", doc, re.MULTILINE), canonical_name
        for parameter in parameters:
            assert re.search(rf"@param\s+\{{[^}}]+\}}\s+{parameter}\b", doc), canonical_name
        assert re.search(r"@returns?\s+\{[^}]+\}", doc), canonical_name
        assert "@customfunction" in doc, canonical_name

        alias_name = canonical_name.lower()
        alias_match = re.search(
            rf"(?P<doc>/\*\*.*?\*/\s*)?function\s+{re.escape(alias_name)}\s*\(",
            formulas_source,
            re.DOTALL,
        )
        assert alias_match is not None, alias_name
        assert "@customfunction" not in (alias_match.group("doc") or ""), alias_name


def test_wrappers_forward_cuenta_as_seller_nickname_and_all_args_to_formula_api() -> None:
    formulas_source = _read_addon_file("Formulas.gs")

    assert "databaseName:" not in formulas_source
    assert "collectionName:" not in formulas_source
    for contract in _contracts():
        canonical_name = _canonical_formula_name(contract["name"])
        parameters = [
            _parameter_name(parameter) for parameter in _signature_parameters(contract["signature"])
        ]
        first_parameter = parameters[0]
        body_pattern = (
            rf"function\s+{re.escape(canonical_name)}\s*\([^)]*\)\s*\{{(?P<body>.*?)\n\}}"
        )
        match = re.search(body_pattern, formulas_source, re.DOTALL)
        assert match is not None, canonical_name
        body = match.group("body")
        assert f'zelerdataExecute_("{canonical_name}", {first_parameter},' in body
        for parameter in parameters[1:]:
            assert f"{parameter}: {parameter}" in body, canonical_name


def test_public_addon_readme_covers_marketplace_install_setup_and_source_readiness() -> None:
    docs = _read_addon_file("README.md")

    assert "ZelerData Google Workspace Marketplace add-on" in docs
    assert "Google Workspace Marketplace" in docs
    assert "Install ZelerData" in docs
    assert "ZelerData → Settings" in docs
    assert "showZelerDataSettings" in docs
    assert "show-once extension token" in docs
    assert "immutable Apps Script version" in docs
    assert "Source readiness checklist" in docs
    assert "ZELERDATA_SKU" in docs
    assert "Do not paste tokens into this repository" in docs
    assert "Marketplace" in docs
    assert "private pilot" not in docs.lower()
    assert "pilot seller" not in docs.lower()
    assert "82453304" not in docs
    assert "Sheetseller" not in docs
    assert "SHEETSELLER" not in docs
    assert "username" not in docs.lower()
    assert "password" not in docs.lower()


def test_public_readme_uses_zelerdata_as_primary_display_name() -> None:
    docs = _read_addon_file("README.md")

    assert "ZelerData Apps Script project" in docs
    assert "ZelerData → Settings" in docs
    assert "**ZelerData** menu appears" in docs


def test_marketplace_publication_runbook_keeps_external_steps_manual_and_checklisted() -> None:
    docs = _read_project_file(MARKETPLACE_DOC_PATH)

    manual_steps = [
        "Google Cloud project linkage",
        "OAuth consent screen",
        "Apps Script immutable version",
        "Marketplace SDK listing",
        "Listing assets",
        "Review submission",
        "Post-approval smoke tests",
    ]
    for step in manual_steps:
        assert step in docs
    assert "Manual-only" in docs
    assert "Do not automate" in docs
    assert "outside repo implementation" in docs
    assert "Pass/Fail" in docs
    assert "Sanitized evidence" in docs


def test_marketplace_scope_matrix_aligns_manifest_oauth_and_listing_docs() -> None:
    manifest = json.loads(_read_addon_file("appsscript.json"))
    docs = _read_project_file(MARKETPLACE_DOC_PATH)

    for scope in manifest["oauthScopes"]:
        assert scope in docs
    assert "Show the ZelerData menu and settings sidebar" in docs
    assert "Call the ZelerData Formula API" in docs
    assert "Read and write only the current spreadsheet" in docs
    assert "No undocumented scopes" in docs


def test_marketplace_readiness_checklist_covers_release_evidence_and_support_paths() -> None:
    docs = _read_project_file(MARKETPLACE_DOC_PATH)

    prerequisites = [
        "Official Formula API URL",
        "Extension-token flow",
        "Audit and rate-limit behavior",
        "Support escalation",
        "Privacy policy URL",
        "Support URL",
        "Immutable submitted version",
        "Approved-context smoke evidence",
    ]
    for prerequisite in prerequisites:
        assert prerequisite in docs
    assert "<support-url>" in docs
    assert "<privacy-policy-url>" in docs
    assert "<apps-script-version>" in docs
    assert "<marketplace-listing-id>" in docs


def test_formula_docs_list_supported_examples_and_stable_error_expectations() -> None:
    docs = _read_project_file(FORMULAS_DOC_PATH)
    supported_section = _markdown_section(docs, "Supported formulas")
    deferred_section = _markdown_section(docs, "Deferred formulas")

    assert "Supported formulas" in docs
    assert "Deferred formulas" in docs
    assert "`cuenta` must be the seller nickname or canonical seller visible to token scope" in docs
    assert _documented_formula_names(supported_section) == set(_supported_formula_names())
    assert _documented_formula_names(deferred_section).isdisjoint(_supported_formula_names())

    example_formulas = [
        '=ZELERDATA_SKU("cuenta")',
        '=ZELERDATA_STOCK("cuenta", "SKU-1", "MLA1")',
        '=ZELERDATA_DASHBOARD("cuenta", "todos", "todos", "base", "si")',
        '=ZELERDATA_IMAGENES("cuenta", "todos", "todos")',
    ]
    for example in example_formulas:
        assert example in docs

    for error_code in [
        "DATA_UNAVAILABLE",
        "TOKEN_MISSING",
        "TOKEN_REVOKED",
        "SELLER_FORBIDDEN",
        "FORMULA_UNKNOWN",
        "BAD_ARGUMENT",
        "RATE_LIMITED",
        "INTERNAL",
    ]:
        assert error_code in docs


def test_formula_docs_document_every_deferred_formula_as_intentionally_unavailable() -> None:
    docs = _read_project_file(FORMULAS_DOC_PATH)
    supported_section = _markdown_section(docs, "Supported formulas")
    deferred_section = _markdown_section(docs, "Deferred formulas")

    unsupported = _unsupported_formula_names()
    assert unsupported
    assert _documented_formula_names(deferred_section) == set(unsupported)
    assert _documented_formula_names(supported_section).isdisjoint(unsupported)
    assert "returns DATA_UNAVAILABLE until a platform read model is implemented" in deferred_section


def test_review_artifacts_do_not_contain_private_pilot_copy_or_secret_like_values() -> None:
    reviewed_files = {
        "Config.gs": _read_addon_file("Config.gs"),
        "Client.gs": _read_addon_file("Client.gs"),
        "README.md": _read_addon_file("README.md"),
        "zelerdata-marketplace-publication.md": _read_project_file(MARKETPLACE_DOC_PATH),
        "zelerdata-formulas.md": _read_project_file(FORMULAS_DOC_PATH),
    }

    secret_patterns = [
        re.compile(r"zs_ext_[A-Za-z0-9_-]{16,}"),
        re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{16,}"),
        re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
        re.compile(r"ya29\.[0-9A-Za-z_-]+"),
    ]
    forbidden_copy = ["private pilot", "pilot seller", "82453304"]
    for file_name, content in reviewed_files.items():
        lowered = content.lower()
        for phrase in forbidden_copy:
            assert phrase not in lowered, file_name
        for pattern in secret_patterns:
            assert not pattern.search(content), file_name
