from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).parents[3]
CONTRACT_PATH = REPO_ROOT / "tests" / "sheets" / "fixtures" / "sheetseller_formula_contracts.json"
ADDON_DIR = REPO_ROOT / "modules" / "sheets" / "apps_script" / "sheetseller"


def _contracts() -> list[dict[str, Any]]:
    loaded = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["contracts"]
    return cast("list[dict[str, Any]]", loaded)


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
    assert "showSheetsellerSettings" in config_source
    assert "saveSheetsellerSettings" in config_source
    assert "clearSheetsellerExtensionToken" in config_source
    assert "PropertiesService.getUserProperties()" in config_source
    assert "SHEETSELLER_EXTENSION_TOKEN" in config_source
    assert "PropertiesService.getDocumentProperties()" in config_source
    assert "SHEETSELLER_API_BASE_URL" in config_source
    assert "UserProperties" in config_source
    assert "DocumentProperties" in config_source
    assert not re.search(r"password|contraseñ|username|usuario", config_source, re.IGNORECASE)


def test_formula_api_client_posts_to_execute_route_with_bearer_token() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "UrlFetchApp.fetch" in client_source
    assert '"/sheets/formulas:execute"' in client_source
    assert "Authorization" in client_source
    assert '"Bearer " + token' in client_source
    assert "muteHttpExceptions: true" in client_source
    assert "JSON.stringify" in client_source
    assert "JSON.parse" in client_source
    assert "sheetsellerEnvelopeToValues_" in client_source


def test_formula_api_envelopes_are_converted_to_sheets_safe_2d_values() -> None:
    client_source = _read_addon_file("Client.gs")

    assert "function sheetsellerEnvelopeToValues_(envelope)" in client_source
    assert "Array.isArray(envelope.values)" in client_source
    assert "return envelope.values" in client_source
    assert "DATA_UNAVAILABLE" in client_source
    assert "TOKEN_MISSING" in client_source
    assert "return [[message]]" in client_source
    assert "function sheetsellerCoerce2d_(value)" in client_source


def test_all_53_legacy_formula_wrappers_preserve_names_and_parameter_order() -> None:
    formulas_source = _read_addon_file("Formulas.gs")

    wrapper_names = re.findall(r"^function\s+([A-Za-z0-9_]+)\s*\(", formulas_source, re.MULTILINE)
    expected_names = [contract["name"] for contract in _contracts()]

    assert wrapper_names == expected_names
    for contract in _contracts():
        arguments = _function_arguments(formulas_source, contract["name"])
        actual_names = [
            _parameter_name(part.strip()) for part in arguments.split(",") if part.strip()
        ]
        expected_parameters = _signature_parameters(contract["signature"])
        expected_names_for_formula = [
            _parameter_name(parameter) for parameter in expected_parameters
        ]
        assert actual_names == expected_names_for_formula, contract["name"]
        for parameter in expected_parameters:
            if "=" in parameter:
                assert parameter in arguments, contract["name"]


def test_wrappers_forward_cuenta_as_seller_nickname_and_all_args_to_formula_api() -> None:
    formulas_source = _read_addon_file("Formulas.gs")

    assert "databaseName is a legacy name; pass the seller nickname" in formulas_source
    assert "collectionName is a legacy name; pass the seller nickname" in formulas_source
    for contract in _contracts():
        parameters = [
            _parameter_name(parameter) for parameter in _signature_parameters(contract["signature"])
        ]
        first_parameter = parameters[0]
        body_pattern = (
            rf"function\s+{re.escape(contract['name'])}\s*\([^)]*\)\s*\{{(?P<body>.*?)\n\}}"
        )
        match = re.search(body_pattern, formulas_source, re.DOTALL)
        assert match is not None, contract["name"]
        body = match.group("body")
        assert f'sheetsellerExecute_("{contract["name"]}", {first_parameter},' in body
        for parameter in parameters[1:]:
            assert f"{parameter}: {parameter}" in body, contract["name"]
        assert "databaseName:" not in body
        assert "collectionName:" not in body


def test_private_manual_installation_docs_cover_setup_without_secrets() -> None:
    docs = _read_addon_file("README.md")

    assert "Private/manual Apps Script pilot" in docs
    assert "Create Apps Script project" in docs
    assert "setSheetsellerApiBaseUrl" in docs
    assert "showSheetsellerSettings" in docs
    assert "extension token" in docs
    assert "Authorize scopes" in docs
    assert "SHEETSELLER_SKU" in docs
    assert "Do not paste tokens into this repository" in docs
    assert "Marketplace" in docs
    assert "username" not in docs.lower()
    assert "password" not in docs.lower()
