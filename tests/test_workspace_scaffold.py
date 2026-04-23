from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_root_contains_required_files() -> None:
    required_files = [
        "pyproject.toml",
        ".python-version",
        ".gitignore",
        ".env.example",
        "README.md",
        "CONTRIBUTING.md",
        "AGENTS.md",
        "SECURITY.md",
        ".pre-commit-config.yaml",
        ".github/workflows/lint.yml",
        ".github/workflows/test.yml",
        "infra/docker/mongo-dev.yml",
        "docs/README.md",
        "sdd/README.md",
    ]

    missing = [file_name for file_name in required_files if not (ROOT / file_name).exists()]

    assert missing == []


def test_workspace_root_declares_uv_members_and_python_version() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.11"' in pyproject
    assert "[tool.uv.workspace]" in pyproject
    assert '"gateway"' in pyproject
    assert '"core"' in pyproject
    assert '"modules/*"' in pyproject
    assert '"bootstrap"' in pyproject
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11"
