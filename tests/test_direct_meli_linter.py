from __future__ import annotations

from pathlib import Path

from infra.lint.check_direct_meli import find_direct_meli_calls


def test_linter_flags_mercadolibre_url(tmp_path: Path) -> None:
    module_file = tmp_path / "modules" / "repricer" / "src" / "bad.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text(
        'MELI_URL = "https://api.mercadolibre.com/items/MLA123"\n',
        encoding="utf-8",
    )

    findings = find_direct_meli_calls(module_file.parents[3])

    assert [(finding.path.name, finding.line, finding.host) for finding in findings] == [
        ("bad.py", 1, "api.mercadolibre.com")
    ]


def test_linter_passes_on_clean_module(tmp_path: Path) -> None:
    module_file = tmp_path / "modules" / "repricer" / "src" / "good.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text('GATEWAY_PATH = "/proxy/meli/items/MLA123"\n', encoding="utf-8")

    findings = find_direct_meli_calls(module_file.parents[3])

    assert findings == []
