from __future__ import annotations

import ast
from pathlib import Path

from zeler_sheets import consumer


def _is_infra_import(module_name: str) -> bool:
    return module_name == "infra" or module_name.startswith("infra.")


def test_sheets_worker_uses_packaged_retry_delay_publisher() -> None:
    retry_delay_publisher = consumer.__dict__["RetryDelayPublisher"]
    assert retry_delay_publisher.__module__ == "zeler_platform_core.runtime.retry_delay"


def test_sheets_consumer_does_not_import_top_level_infra_runtime_code() -> None:
    source = Path(consumer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_infra_modules: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _is_infra_import(node.module)
        ):
            imported_infra_modules.append(node.module)
        if isinstance(node, ast.Import):
            imported_infra_modules.extend(
                alias.name for alias in node.names if _is_infra_import(alias.name)
            )

    assert imported_infra_modules == []
