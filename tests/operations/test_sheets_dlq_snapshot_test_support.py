from __future__ import annotations

from pathlib import Path

from zeler_platform_test_support import sheets_dlq_snapshot


def test_snapshot_runtime_uses_unique_support_package_without_tests_imports() -> None:
    runtime_source = (
        Path(__file__).with_name("test_sheets_dlq_snapshot_runtime.py").read_text(encoding="utf-8")
    )

    assert "from tests" not in runtime_source
    assert "import tests" not in runtime_source
    assert sheets_dlq_snapshot.__name__ == "zeler_platform_test_support.sheets_dlq_snapshot"
