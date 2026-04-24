from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_HOSTS = ("api.mercadolibre.com", "auth.mercadolibre.com")


@dataclass(frozen=True)
class DirectMeliFinding:
    path: Path
    line: int
    host: str


def find_direct_meli_calls(root: Path) -> list[DirectMeliFinding]:
    modules_root = root / "modules"
    if not modules_root.exists():
        return []

    findings: list[DirectMeliFinding] = []
    for path in sorted(modules_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        findings.extend(_find_forbidden_strings(path))
    return findings


def _find_forbidden_strings(path: Path) -> list[DirectMeliFinding]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[DirectMeliFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for host in FORBIDDEN_HOSTS:
            if host in node.value:
                findings.append(DirectMeliFinding(path=path, line=node.lineno, host=host))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject direct MercadoLibre URLs under modules/.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()

    findings = find_direct_meli_calls(args.root)
    for finding in findings:
        print(f"{finding.path}:{finding.line}: direct MercadoLibre host forbidden: {finding.host}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
