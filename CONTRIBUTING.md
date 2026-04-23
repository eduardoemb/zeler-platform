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

For now, the design, proposal, and tasks for this repo live in the sibling repository:

- `../zeler-core/sdd/zeler-platform-greenfield/`

Read those artifacts before implementing changes.
