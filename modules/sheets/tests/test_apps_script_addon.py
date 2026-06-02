from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from zeler_sheets.formulas.handlers_core import CORE_FORMULA_NAMES

REPO_ROOT = Path(__file__).parents[3]
CONTRACT_PATH = REPO_ROOT / "tests" / "sheets" / "fixtures" / "sheetseller_formula_contracts.json"
ADDON_DIR = REPO_ROOT / "modules" / "sheets" / "apps_script" / "sheetseller"


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


def test_apps_script_manifest_declares_private_pilot_runtime_and_scopes() -> None:
    manifest = json.loads(_read_addon_file("appsscript.json"))

    assert manifest["timeZone"] == "America/Argentina/Buenos_Aires"
    assert manifest["runtimeVersion"] == "V8"
    assert manifest["exceptionLogging"] == "STACKDRIVER"
    assert manifest["oauthScopes"] == [
        "https://www.googleapis.com/auth/script.container.ui",
        "https://www.googleapis.com/auth/script.external_request",
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
    ]


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
    assert not re.search(r"password|contraseñ|username|usuario", config_source, re.IGNORECASE)


def test_config_ui_uses_zelerdata_visible_copy_and_property_keys() -> None:
    config_source = _read_addon_file("Config.gs")

    assert '.createMenu("ZelerData")' in config_source
    assert '.setTitle("ZelerData settings")' in config_source
    assert '"ZelerData extension token cleared"' in config_source
    assert '"ZelerData"' in config_source
    assert "ZelerData private pilot" in config_source
    assert "ZELERDATA_EXTENSION_TOKEN" in config_source
    assert "ZELERDATA_API_BASE_URL" in config_source
    assert "function showZelerDataSettings" in config_source
    assert "function setZelerDataExtensionToken" in config_source
    assert "SHEETSELLER_" not in config_source


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


def test_formula_api_envelopes_are_converted_to_sheets_safe_2d_values() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "function zelerdataEnvelopeToValues_(envelope)" in client_source
    assert "Array.isArray(envelope.values)" in client_source
    assert "envelope.values.length === 0" in client_source
    assert 'return [[""]]' in client_source
    assert "return zelerdataCoerce2d_(envelope.values)" in client_source
    assert "DATA_UNAVAILABLE" in client_source
    assert "TOKEN_MISSING" in client_source
    assert "return [[message]]" in client_source
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


def test_private_manual_installation_docs_cover_setup_without_secrets() -> None:
    docs = _read_addon_file("README.md")

    assert "Private/manual Apps Script pilot" in docs
    assert "Create Apps Script project" in docs
    assert "setZelerDataApiBaseUrl" in docs
    assert "showZelerDataSettings" in docs
    assert "extension token" in docs
    assert "Authorize scopes" in docs
    assert "ZELERDATA_SKU" in docs
    assert "Do not paste tokens into this repository" in docs
    assert "Marketplace" in docs
    assert "Sheetseller" not in docs
    assert "SHEETSELLER" not in docs
    assert "username" not in docs.lower()
    assert "password" not in docs.lower()


def test_private_manual_installation_docs_use_zelerdata_as_primary_display_name() -> None:
    docs = _read_addon_file("README.md")

    assert "ZelerData Apps Script project" in docs
    assert "ZelerData → Settings" in docs
    assert "**ZelerData** menu appears" in docs


def test_private_pilot_runbook_locks_deployment_prerequisites_and_token_safety() -> None:
    docs = _read_addon_file("README.md")

    assert "Pilot seller: `82453304`" in docs
    assert "Formula API deployed" in docs
    assert "extension token pepper" in docs
    assert "zeler-app `/sheets/config` deployed" in docs
    assert "show-once extension token" in docs
    assert "Do not paste real tokens into repo/issues/logs" in docs
    assert "Do not deploy from this checklist" in docs
    assert "Use only seller `82453304`" in docs
    assert "private Apps Script project" in docs


def test_private_pilot_runbook_lists_current_formula_validation_matrix_and_stable_errors() -> None:
    docs = _read_addon_file("README.md")

    assert "## Validation matrix for currently implemented wrappers" in docs
    assert "`cuenta` must be the seller nickname or canonical seller visible to token scope" in docs
    for formula_name in sorted(CORE_FORMULA_NAMES):
        assert formula_name in docs

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
