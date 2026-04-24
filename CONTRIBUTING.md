# Contributing to zeler-platform

## Local setup

- Python 3.11 is required.
- `uv` is the workspace package manager.
- Run `uv sync` to install all workspace packages and tooling.

## Daily workflow

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
```

## Module-to-Meli boundary

Modules must call Meli through the gateway proxy by default. The only sanctioned
escape hatch is `POST /internal/tokens/issue`, which is reserved for high-throughput
workers such as Repricer.

Rules for `/internal/tokens/issue`:

- callers must present a valid internal module JWT;
- requested scopes must be a subset of the module's `module_registry.allowed_meli_scopes`;
- `ttl_s` must be short-lived (`<= 300` seconds);
- the gateway writes one `audit_log` issuance event;
- modules must still avoid hardcoded `api.mercadolibre.com` URLs in source code so the
  direct-Meli linter remains the merge gate.

## Strict TDD mandate

This repository follows **Strict TDD**.

Every non-trivial change must follow **RED → GREEN → REFACTOR**:

1. write a failing test first,
2. implement the minimum code to make it pass,
3. refactor with tests still green.

If you skip the failing test first, the change is not acceptable.

## Commit conventions

Use conventional commits only:

- `feat:`
- `fix:`
- `refactor:`
- `test:`
- `docs:`
- `chore:`

Never add AI attribution or co-author trailers unless explicitly requested.

## Branch naming

Use `type/short-description`, for example:

- `feat/oauth-callback`
- `fix/health-endpoint`
- `chore/bootstrap-workspace`

## SDD references

The design, proposal, and tasks for this repo live locally at:

- `sdd/zeler-platform-greenfield/`

Legacy references may still mention `../zeler-core/sdd/zeler-platform-greenfield/`, but
that sibling path is not canonical for this repository.

Read those artifacts before implementing changes.
