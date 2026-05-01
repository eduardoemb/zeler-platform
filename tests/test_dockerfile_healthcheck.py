from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DOCKERFILES = (
    ROOT / "gateway" / "Dockerfile",
    ROOT / "modules" / "repricer" / "Dockerfile.api",
    ROOT / "modules" / "sheets" / "Dockerfile.api",
    ROOT / "modules" / "publicador" / "Dockerfile.api",
    ROOT / "modules" / "autoreply" / "Dockerfile.api",
    ROOT / "modules" / "fulldock" / "Dockerfile.api",
)
WORKER_DOCKERFILES = (
    ROOT / "modules" / "repricer" / "Dockerfile.worker",
    ROOT / "modules" / "sheets" / "Dockerfile.worker",
    ROOT / "modules" / "autoreply" / "Dockerfile.worker",
    ROOT / "modules" / "fulldock" / "Dockerfile.worker",
)


def test_api_dockerfile_has_healthcheck() -> None:
    missing = [path for path in API_DOCKERFILES if _missing(path, "'PORT','8000'")]

    assert missing == []


def test_worker_dockerfile_has_healthcheck() -> None:
    missing = [path for path in WORKER_DOCKERFILES if _missing(path, "'WORKER_HEALTH_PORT','8080'")]

    assert missing == []


def _missing(path: Path, port_expr: str) -> bool:
    content = path.read_text(encoding="utf-8")
    return (
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3" not in content
        or port_expr not in content
    )
