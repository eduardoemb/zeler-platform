# zeler-platform

Unified Mercado Libre integration platform for Zeler.

## Monorepo packages

- `gateway/` — FastAPI gateway entrypoint and future OAuth/proxy/webhook flows.
- `core/` — shared domain models and reusable libraries.
- `modules/` — module packages (`repricer`, `sheets`, `publicador`, `autoreply`).
- `bootstrap/` — one-shot bootstrap jobs.
- `infra/` — platform infrastructure assets and local development helpers.

## Module display identities

Platform module IDs remain stable runtime contracts. Zeler-facing display names
are metadata layered on top of those IDs:

| Module ID | Display name | Legacy alias |
| --- | --- | --- |
| `sheets` | ZelerData | SheetsellerApp |
| `repricer` | ZelerPricing | EasyReprice |
| `publicador` | ZelerListings | Autopubli |
| `autoreply` | ZelerSupport | AutoReply |

`fulldock` is retired historical metadata only: FullDockManager maps to
ZelerStock, but no active routes, scopes, services, workers, or registry access
are enabled.

## Quick start

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
```

## SDD artifacts

The authoritative SDD artifacts currently live in this repository:

- `sdd/zeler-platform-greenfield/`

See `docs/README.md` and `sdd/README.md` for pointers.
