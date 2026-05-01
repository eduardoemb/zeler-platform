from __future__ import annotations

from infra.operations.preflight import PreflightContext, PreflightResult, main, run_preflight

__all__ = ["PreflightContext", "PreflightResult", "main", "run_preflight"]


if __name__ == "__main__":
    raise SystemExit(main())
