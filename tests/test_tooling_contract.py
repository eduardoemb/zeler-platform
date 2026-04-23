from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_pyproject_contains_required_tooling_sections() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    required_snippets = [
        "[tool.ruff]",
        'target-version = "py311"',
        "line-length = 100",
        "[tool.ruff.lint]",
        'select = ["E", "F", "I", "B", "UP", "N", "S", "BLE", "RET", "SIM"]',
        "[tool.mypy]",
        'python_version = "3.11"',
        "strict = true",
        "[tool.pytest.ini_options]",
        'addopts = "-ra -q --strict-markers --strict-config',
    ]

    assert all(snippet in pyproject for snippet in required_snippets)


def test_pre_commit_config_contains_quality_and_commit_hooks() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "ruff-check" in config
    assert "ruff-format" in config
    assert "mypy" in config
    assert "commitizen" in config
