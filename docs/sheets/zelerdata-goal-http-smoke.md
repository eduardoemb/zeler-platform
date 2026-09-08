# Observe all 52 formulas without claiming data correctness

`zeler_sheets.scripts.goal_formula_smoke` makes one authenticated execution per
active formula. It is an operator CLI, not a service, job or automatic hook.
The existing B1 smoke counts 52 contracts but executes only DEVOLUCIONES for a
June range; that runner and its separate authorization/lifecycle remain unchanged.

## Validate without network access

Prepare a protected JSON file with these six fields, using real pilot-owned
identities: `skus`, `id_publicaciones`, `codigo_ml`, `id_ordenes`, `fecha_inicial`,
`fecha_final`. All values are nonempty strings. Initially use `2026-08-08` through
`2026-09-06`; select a newer bounded window explicitly when needed. The CLI does
not discover, fabricate or print identifiers. Input ownership must be checked
through authorized API/runtime evidence before execution.

```bash
uv run python -m zeler_sheets.scripts.goal_formula_smoke --inputs /protected/pilot.json
```

This validates all required parameters for exactly 52 local contracts and performs
no HTTP request. `--help` also performs no HTTP request.

## Authorized execution only

Use a legitimate linked ZelerData user and a narrowly scoped, short-lived token.
The approved operator credential lifecycle must supply `ZELERDATA_SMOKE_TOKEN`
and `ZELERDATA_SMOKE_SELLER` in memory/environment, then revoke the token when
finished. Never put tokens in argv, input JSON, chat, logs or repository files.
Do not redirect the fixed B1 launcher to this CLI or bypass its authorization.
The user identity, approved input file and credential lifecycle must be resolved
before adding `--execute` to the validation command.

Execution targets only `https://sheets.zeler.ai/sheets/formulas:execute`, without
redirect following, environment proxies, credential creation or retries. A 25s
total deadline applies per formula. HTTP 401/403 stops the run. Normal formula
execution can admit asynchronous recovery through the existing API; it is not
guaranteed to be a database-read-only operation.

## Interpret the report

Output contains only fixed formula names, bounded statuses, HTTP codes, row counts
and elapsed seconds. It does not include returned data, identifiers or errors from
the server. `all_responded` means 52 HTTP-200 responses, not successful formulas.
Exit 1 flags incomplete executions, missing/partial/empty data or malformed/error
responses; exit 2 flags configuration failure. Exit 0 means all 52 returned data
requiring review, not verified business correctness. `correctness_verified` is
always false: compare actual values against authorized source evidence separately.
One timing per formula does not establish p95 or real Google Sheets latency.

Rollback: remove this standalone CLI, its tests and this guide together. No
service entrypoint, credential lifecycle or production schema depends on it.
