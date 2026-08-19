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


def test_snapshot_test_support_remains_hermetic_without_runtime_surfaces() -> None:
    # PR 3 (R12): the fake broker/runtime/channel support must stay a pure
    # in-memory double with no Mongo, broker, HTTP, shell, subprocess, socket,
    # Docker, or tests-package import. Assert the exact import allowlist so any
    # new forbidden import fails the contract (word scans would match comments).
    module_file = sheets_dlq_snapshot.__file__
    assert module_file is not None
    support_source = Path(module_file).read_text(encoding="utf-8")

    import_lines = [
        line.strip()
        for line in support_source.splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert import_lines == [
        "from __future__ import annotations",
        "from dataclasses import dataclass, field, replace",
    ]
