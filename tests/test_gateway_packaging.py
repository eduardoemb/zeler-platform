from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_DIR = ROOT / "gateway"
DOCKERFILE = GATEWAY_DIR / "Dockerfile"


# ---------------------------------------------------------------------------
# 1. Dockerfile existence
# ---------------------------------------------------------------------------


def test_gateway_dockerfile_exists() -> None:
    assert DOCKERFILE.exists(), "gateway/Dockerfile must exist"


# ---------------------------------------------------------------------------
# 2–7. Dockerfile content checks
# ---------------------------------------------------------------------------


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_gateway_dockerfile_uses_python_311_slim() -> None:
    assert "python:3.11-slim" in _dockerfile_text()


def test_gateway_dockerfile_syncs_gateway_package() -> None:
    text = _dockerfile_text()
    assert "uv sync" in text
    assert "--package zeler-gateway" in text
    assert "--frozen" in text
    assert "--no-dev" in text


def test_gateway_dockerfile_runs_uvicorn_with_zeler_gateway_app() -> None:
    text = _dockerfile_text()
    assert "uv run" not in text
    assert ".venv/bin/uvicorn zeler_gateway.app:app" in text
    assert "uvicorn zeler_gateway.app:app" in text
    assert "--host 0.0.0.0" in text
    assert "${PORT" in text or "$PORT" in text


def test_gateway_dockerfile_runs_as_non_root_user() -> None:
    text = _dockerfile_text()
    # Must have a USER directive that is NOT 'USER root'
    user_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("USER ")]
    assert user_lines, "Dockerfile must have at least one USER directive"
    non_root = [line for line in user_lines if line != "USER root"]
    assert non_root, "Dockerfile must switch to a non-root USER"
    # Must also create that user
    assert "useradd" in text or "adduser" in text, (
        "Dockerfile must create a non-root user with useradd or adduser"
    )


def test_gateway_dockerfile_does_not_hardcode_reload() -> None:
    assert "--reload" not in _dockerfile_text()


def test_gateway_dockerfile_copies_core_package() -> None:
    assert "COPY core" in _dockerfile_text()


# ---------------------------------------------------------------------------
# 8. gateway/pyproject.toml declares uvicorn
# ---------------------------------------------------------------------------


def test_gateway_pyproject_declares_uvicorn() -> None:
    pyproject = GATEWAY_DIR / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    assert any(d.startswith("uvicorn") for d in deps), (
        "gateway/pyproject.toml must declare uvicorn in [project] dependencies"
    )


# ---------------------------------------------------------------------------
# 9. gateway/pyproject.toml does NOT declare gunicorn
# ---------------------------------------------------------------------------


def test_gateway_pyproject_does_not_declare_gunicorn() -> None:
    pyproject = GATEWAY_DIR / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    assert not any(d.startswith("gunicorn") for d in deps), (
        "gateway/pyproject.toml must NOT declare gunicorn"
    )


# ---------------------------------------------------------------------------
# 10. Root pyproject.toml dev group does NOT declare uvicorn
# ---------------------------------------------------------------------------


def test_root_pyproject_dev_group_does_not_declare_uvicorn() -> None:
    root_pyproject = ROOT / "pyproject.toml"
    data = tomllib.loads(root_pyproject.read_text(encoding="utf-8"))
    dev_deps: list[str] = data.get("dependency-groups", {}).get("dev", [])
    assert not any(isinstance(d, str) and d.startswith("uvicorn") for d in dev_deps), (
        "Root pyproject.toml [dependency-groups.dev] must NOT declare uvicorn"
    )
