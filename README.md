# zeler-platform

Unified Mercado Libre integration platform for Zeler.

## Monorepo packages

- `gateway/` — FastAPI gateway entrypoint and future OAuth/proxy/webhook flows.
- `core/` — shared domain models and reusable libraries.
- `modules/` — module packages (`repricer`, `sheets`, `publicador`, `autoreply`, `fulldock`).
- `bootstrap/` — one-shot bootstrap jobs.
- `infra/` — platform infrastructure assets and local development helpers.

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
