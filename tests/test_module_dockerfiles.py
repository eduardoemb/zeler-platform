from __future__ import annotations

from pathlib import Path

import pytest

# Baseline captured before this change: uv run pytest -q -> 504 passing tests.
# Final regression after this change: uv run pytest -q -> 557 passing tests (+53).
REPO_ROOT = Path(__file__).resolve().parents[1]
API_MODULES = ("repricer", "sheets", "publicador", "autoreply", "fulldock")
WORKER_MODULES = ("repricer", "sheets", "autoreply", "fulldock")


def dockerfile_path(module_name: str, variant: str) -> Path:
    return REPO_ROOT / "modules" / module_name / f"Dockerfile.{variant}"


def assert_stanzas_in_order(text: str, stanzas: tuple[str, ...]) -> None:
    cursor = -1
    for stanza in stanzas:
        position = text.find(stanza, cursor + 1)
        assert position > cursor, f"Missing or out-of-order stanza: {stanza}"
        cursor = position


def expected_api_stanzas(module_name: str) -> tuple[str, ...]:
    return (
        "FROM python:3.11-slim AS runtime",
        "ENV PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "PORT=8080",
        "WORKDIR /app",
        "RUN pip install --no-cache-dir uv",
        "COPY pyproject.toml uv.lock ./",
        "COPY core ./core",
        f"COPY modules/{module_name} ./modules/{module_name}",
        f"RUN uv sync --frozen --package zeler-{module_name} --no-dev",
        "RUN useradd --system --create-home --uid 1001 appuser",
        "USER appuser",
    )


def expected_worker_stanzas(module_name: str) -> tuple[str, ...]:
    return (
        "FROM python:3.11-slim AS runtime",
        "ENV PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "WORKDIR /app",
        "RUN pip install --no-cache-dir uv",
        "COPY pyproject.toml uv.lock ./",
        "COPY core ./core",
        f"COPY modules/{module_name} ./modules/{module_name}",
        f"RUN uv sync --frozen --package zeler-{module_name} --no-dev",
        "RUN useradd --system --create-home --uid 1001 appuser",
        "USER appuser",
    )


@pytest.mark.parametrize("module_name", API_MODULES)
def test_api_dockerfile_exists(module_name: str) -> None:
    dockerfile = dockerfile_path(module_name, "api")

    assert dockerfile.is_file()


@pytest.mark.parametrize("module_name", API_MODULES)
def test_api_dockerfile_contains_required_stanzas_in_order(module_name: str) -> None:
    text = dockerfile_path(module_name, "api").read_text()

    assert_stanzas_in_order(text, expected_api_stanzas(module_name))


@pytest.mark.parametrize("module_name", API_MODULES)
def test_api_dockerfile_cmd_matches_contract(module_name: str) -> None:
    text = dockerfile_path(module_name, "api").read_text()

    assert "uv run" not in text
    assert (
        f'CMD ["sh", "-c", ".venv/bin/uvicorn zeler_{module_name}.app:make_app '
        '--factory --host 0.0.0.0 --port ${PORT:-8080}"]'
    ) in text


@pytest.mark.parametrize("module_name", WORKER_MODULES)
def test_worker_dockerfile_exists(module_name: str) -> None:
    dockerfile = dockerfile_path(module_name, "worker")

    assert dockerfile.is_file()


def test_publicador_has_no_worker_dockerfile() -> None:
    dockerfile = dockerfile_path("publicador", "worker")

    assert not dockerfile.exists()


@pytest.mark.parametrize("module_name", WORKER_MODULES)
def test_worker_dockerfile_contains_required_stanzas_in_order(
    module_name: str,
) -> None:
    text = dockerfile_path(module_name, "worker").read_text()

    assert_stanzas_in_order(text, expected_worker_stanzas(module_name))
    assert "PORT=8080" not in text


@pytest.mark.parametrize("module_name", WORKER_MODULES)
def test_worker_dockerfile_cmd_matches_contract(module_name: str) -> None:
    text = dockerfile_path(module_name, "worker").read_text()

    assert "uv run" not in text
    assert f'CMD ["sh", "-c", ".venv/bin/python -m zeler_{module_name}"]' in text
