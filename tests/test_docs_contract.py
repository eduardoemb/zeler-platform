from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_contributing_documents_local_workflow_and_tdd_rules() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "uv sync" in contributing
    assert "uv run pytest" in contributing
    assert "uv run ruff check ." in contributing
    assert "uv run mypy ." in contributing
    assert "RED → GREEN → REFACTOR" in contributing
    assert "feat:" in contributing
    assert "../zeler-core/sdd/zeler-platform-greenfield/" in contributing


def test_agents_and_security_docs_capture_required_rules() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    skill_registry = (
        "/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md"
    )

    assert skill_registry in agents
    assert "TDD strict" in agents
    assert "Never commit without being asked" in agents
    assert "Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP" in agents
    assert "Tokens are NEVER stored plaintext" in security
    assert "AES-256-GCM + GCP KMS wrapped DEKs" in security
    assert "No credentials in source code, ever" in security


def test_webhook_backlog_replay_documents_stock_location_readiness_gates() -> None:
    runbook = (ROOT / "docs" / "ops" / "webhook-backlog-replay.md").read_text(encoding="utf-8")

    assert "stock-locations remains `NO_GO`" in runbook
    assert "GET /user-products/*/stock" in runbook
    assert "PUT /items/*/stock_locations" in runbook
    assert "no recent gateway `out_of_scope`" in runbook
    assert "no `malformed_resource`, `missing_mapping`, or `resource_not_found` spike" in runbook
    assert "429 requeue spikes" in runbook
