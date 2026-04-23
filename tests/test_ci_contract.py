from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lint_workflow_runs_ruff_and_mypy() -> None:
    workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v4" in workflow
    assert "astral-sh/setup-uv@v5" in workflow
    assert "uv sync" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run mypy ." in workflow


def test_test_workflow_runs_pytest() -> None:
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v4" in workflow
    assert "astral-sh/setup-uv@v5" in workflow
    assert "uv sync" in workflow
    assert "uv run pytest" in workflow
