from __future__ import annotations

from typing import Any

import pytest

from zeler_sheets.scripts.authenticated_smoke import (
    ENV_BASE_URL,
    ENV_SELLER,
    ENV_TOKEN,
    SmokeConfig,
    SmokeConfigError,
    SmokeRedactionError,
    STAGE,
    assert_redacted,
    build_evidence,
    config_from_env,
    exit_code_for,
    redact_text,
)

TOKEN = "zs_ext_smoke_test_secret_token"  # noqa: S105 - test-only placeholder token.
SELLER = "82453304"
BASE_URL = "https://sheets.example"

ENV_OK = {
    ENV_BASE_URL: BASE_URL,
    ENV_TOKEN: TOKEN,
    ENV_SELLER: SELLER,
}


def test_taxonomy_status_classes_and_exit_codes_are_bounded() -> None:
    assert exit_code_for("success") == 0
    for status_class in (
        "config_missing",
        "inventory_mismatch",
        "auth_failed",
        "data_unavailable",
        "formula_failed",
        "transport_failed",
        "redaction_failed",
    ):
        assert exit_code_for(status_class) != 0


def test_build_evidence_emits_zelerdata_smoke_envelope() -> None:
    evidence = build_evidence("success", {"formulas_total": 52, "devoluciones": 1})

    assert set(evidence) == {"stage", "status_class", "counters"}
    assert evidence["stage"] == STAGE
    assert evidence["stage"] == "zelerdata_smoke"
    assert evidence["status_class"] == "success"
    assert evidence["counters"] == {"devoluciones": 1, "formulas_total": 52}


def test_config_from_env_requires_all_three_values_in_normal_mode() -> None:
    with pytest.raises(SmokeConfigError) as exc:
        config_from_env({})
    message = str(exc.value)
    assert ENV_BASE_URL in message
    assert ENV_TOKEN in message
    assert ENV_SELLER in message


@pytest.mark.parametrize("missing", [ENV_BASE_URL, ENV_TOKEN, ENV_SELLER])
def test_config_from_env_fails_closed_on_any_single_missing_value(
    missing: str,
) -> None:
    environment = {key: value for key, value in ENV_OK.items() if key != missing}
    with pytest.raises(SmokeConfigError) as exc:
        config_from_env(environment)
    assert missing in str(exc.value)


def test_config_from_env_dry_run_requires_token_only() -> None:
    config = config_from_env({ENV_TOKEN: TOKEN}, dry_run=True)

    assert config.base_url == ""
    assert config.seller == ""
    assert config.token == TOKEN

    with pytest.raises(SmokeConfigError):
        config_from_env({}, dry_run=True)


def test_config_from_env_strips_whitespace() -> None:
    config = config_from_env(
        {ENV_BASE_URL: f"  {BASE_URL}  ", ENV_TOKEN: f"  {TOKEN}  ", ENV_SELLER: f"  {SELLER}  "}
    )

    assert config == SmokeConfig(base_url=BASE_URL, token=TOKEN, seller=SELLER)


def test_redact_text_replaces_token_and_seller_everywhere() -> None:
    config = config_from_env(ENV_OK)
    text = f"token={TOKEN} seller={SELLER} again {TOKEN} {SELLER}"

    redacted = redact_text(text, config)

    assert TOKEN not in redacted
    assert SELLER not in redacted
    assert redacted.count("[REDACTED_TOKEN]") == 2
    assert redacted.count("[REDACTED_SELLER]") == 2


def test_redact_text_skips_empty_values_for_dry_run_config() -> None:
    config = config_from_env({ENV_TOKEN: TOKEN}, dry_run=True)

    assert redact_text(f"token={TOKEN}", config) == "token=[REDACTED_TOKEN]"
    assert redact_text("plain text", config) == "plain text"


def test_assert_redacted_accepts_clean_output() -> None:
    config = config_from_env(ENV_OK)

    assert_redacted('{"status_class": "success"}', config)


def test_assert_redacted_rejects_leaked_token_or_seller() -> None:
    config = config_from_env(ENV_OK)

    with pytest.raises(SmokeRedactionError) as token_exc:
        assert_redacted(f"leaked {TOKEN}", config)
    assert "token" in str(token_exc.value)
    with pytest.raises(SmokeRedactionError) as seller_exc:
        assert_redacted(f"leaked {SELLER}", config)
    assert "seller" in str(seller_exc.value)
