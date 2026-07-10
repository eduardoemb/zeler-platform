# ZelerData read-model reconciliation

Use this runbook to plan ZelerData read-model reconciliation with sanitized, aggregate-only output. It documents the helper contracts only; it does not authorize production writes or local production Mongo access.

## Quick path

1. Run only from the approved VM/VPC/runtime container, never from the local assistant environment.
2. Start with `--dry-run` and `--confirm-approved-runtime`; review sanitized counters and issue codes only.
3. Stop before any write unless a separate production-write authorization explicitly allows `--write --confirm-production-write` for the exact seller/range.
4. Roll back by stopping runs and marking affected freshness markers `stale`/`failed` from the approved runtime; formulas stay `DATA_UNAVAILABLE` until complete markers exist again.
5. For observed pause-basis repair, start with `--repair-observed-pause-basis --dry-run`; write mode is a later approved runtime action only.

## Chain context

This final docs/verification slice closes the chained `zelerdata-missing-formula-read-models` work. Review boundaries are:

| PR | Boundary |
|---|---|
| #107 | Foundation/safety contracts for dry-run, write authorization, sanitized output, and shared marker semantics. |
| #109 | `PREGUNTAS`/`PREGUNTASKPI` questions reconciliation and historical freshness gates. |
| #111 | `DEVOLUCIONES` claims/order reconciliation and explicit returned-quantity semantics. |
| #114 | Catalog readiness contracts for source mapping, required fields, and marker publication. |
| #115 | Catalog product and buybox snapshot writes from approved source rows. |
| Final docs/verification PR | Operator runbooks, smoke intent, rollback notes, and root quality-gate evidence. |

## Command shape

```bash
sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
  exec -T --workdir /app sheets-worker \
  /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id <seller> \
  --date-from 2026-06-01 \
  --date-to 2026-06-04 \
  --dry-run \
  --confirm-approved-runtime \
  --emit-phase2-contract
```

Observed pause-basis repair dry-run:

```bash
sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
  exec -T --workdir /app sheets-worker \
  /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id <seller> \
  --date-from 2026-06-01 \
  --date-to 2026-06-04 \
  --dry-run \
  --confirm-approved-runtime \
  --repair-observed-pause-basis \
  --max-items 100
```

## DEVOLUCIONES production range and lease

`ZELERDATA_DEVOLUCIONES` readiness is one exact non-unioned `devoluciones` marker
covering claims and the joined orders. It has a 30-minute marker lease.
Formula readers fail closed when the marker expires or does not enclose the
requested range; separate claims/orders markers cannot be combined.

For the pilot, scheduled reconciliation always verifies 2026-06-01 through the previous closed UTC day.
It must not shrink accepted coverage. The service
defaults make `2026-06-01` the historical start and `2026-07-09` the minimum
accepted-through date; reviewed non-secret overrides may live in
`/etc/zeler-platform/zelerdata-devoluciones-reconcile.env`. Overrides may only
widen the accepted coverage. Invalid, reversed, shrinking, or open ranges fail
without invoking the reconciliation command.

The timer runs every 10 minutes, with at most one minute of random delay. The
service has an eight-minute outer timeout and performs one bounded retry: two
three-minute attempts separated by one minute. `Persistent=true` provides catch-up after downtime, and
`OnFailure` invokes a sanitized journald alert. Missing wrapper, compose, or
container paths fail visibly; they are not skipped by a path condition.

Production rollout order is `plan → prestart → worker health → bind-claims`,
then frozen-runtime dry-run, authorized write, and acceptance. The initial
accepted half-open interval is
`[2026-06-01T00:00:00Z, 2026-07-10T00:00:00Z)` and must report
`expected/persisted/complete/missing = 9/9/9/0`. Capture an authenticated formula
smoke or sanitized operator evidence with timestamp, exact inputs/result, and
request/correlation ID. If neither is available, record
`OPERATOR_EVIDENCE_PENDING`; do not report success.

Enable scheduling last, after all acceptance evidence passes:

```bash
sudo systemctl enable --now zelerdata-devoluciones-reconcile.timer
sudo journalctl -u zelerdata-devoluciones-reconcile.service \
  -u zelerdata-devoluciones-reconcile-alert.service --since "30 minutes ago" \
  --no-pager
```

Use **failure-conditional rollback** only after a failed deployment, topology,
write, formula, or timer gate. Disable the timer, stale readiness through the
topology rollback, restore the prior worker runtime/routing/schedule, and retain
verified idempotent facts. Never roll back a successful release automatically.

## Flags

| Flag | Required | Purpose |
|---|---:|---|
| `--seller-id` | Yes | Selects the seller scope. Output must not print the raw value. |
| `--date-from` | Yes | Inclusive start date using `YYYY-MM-DD`. |
| `--date-to` | Yes | Inclusive end date using `YYYY-MM-DD`; the helper computes the exclusive next day. |
| `--dry-run` | Default | Plans/summarizes only. No writes, deploys, restarts, or production data mutation. |
| `--write` | Write phase only | Enables the write path after dry-run review and separate approval. |
| `--confirm-approved-runtime` | Every run | Confirms execution from the approved VM/VPC/runtime. |
| `--confirm-production-write` | With `--write` | Confirms separate production-write authorization. This flag is not enough by itself; the user must explicitly approve the scoped write phase. |
| `--max-orders` | Bounded trials / PII mode | Caps order processing for trial runs and is required for buyer/address PII mode. |
| `--max-items` | Bounded write trials | Caps item reconciliation scope for staged runs. |
| `--max-shipments` | Bounded write trials | Caps shipment reconciliation scope for staged runs. |
| `--concurrency` | Optional | Limits concurrent runtime fetch/write units; keep low during pilot runs. |
| `--sleep-ms` | Optional | Adds a throttle between bounded write phases to protect MercadoLibre and Mongo. |
| `--error-threshold` | Optional | Stops when sanitized error counters reach the configured threshold. |
| `--stop-on-rate-limit` | Optional | Stops instead of continuing when rate-limit diagnostics appear. |
| `--resume-after-order-id` | Resume only | Private cursor for approved runtime continuation. Output reports only that a cursor was provided. |
| `--include-buyer-address-pii` | Exceptional | Allows bounded buyer/address processing in approved runtime; output remains count-only. |
| `--emit-phase2-contract` | Phase 2 contract runs | Prints the read-only preflight and dry-run contract alongside the sanitized summary. |
| `--repair-observed-pause-basis` | Optional repair scope | Plans or runs bounded repair for current paused rows missing `paused_since`. Dry-run mutates nothing and reports sanitized aggregate counters only. Write mode still requires `--write --confirm-production-write` plus explicit scoped approval. |

## Formula/read-model mapping

| Formula | Required read model | Source and readiness rule |
|---|---|---|
| `ZELERDATA_PREGUNTAS` | `questions` | Historical search/detail reconciliation must prove the requested date range and required answer/detail fields. Event-only freshness is not enough. |
| `ZELERDATA_PREGUNTASKPI` | `questions` | Same historical reconciled marker requirement as `PREGUNTAS`; do not infer counts or dates from events alone. |
| `ZELERDATA_DEVOLUCIONES` | Joint `devoluciones` marker over `claims` plus `orders` | One unexpired enclosing marker must prove the exact closed range. Returned units use explicit positive `return_quantity` only; unknown or unmapped quantities keep the formula unavailable. |
| `ZELERDATA_CATALOGO_COMPLETO` | `catalog_product_snapshots` | Expected rows come from scoped item rows with distinct `catalog_product_id`; snapshots are fetched from `/products/{catalog_product_id}`. |
| `ZELERDATA_CATALOGOBUYBOX` | `catalog_buybox_snapshots` | Expected rows come from scoped item rows with `catalog_product_id`; buybox snapshots are fetched from `/items/{item_id}/price_to_win?version=v2`. |

`NA` is valid only for optional cells inside an otherwise ready formula row. Missing, stale, failed, or partial read models must produce stable `DATA_UNAVAILABLE` for the affected formula.

## Rollout and rollback

- Keep `ZELERDATA_ENRICHMENT_ENABLED` disabled until the additive models and formula readers are deployed.
- Pilot with `ZELERDATA_ENRICHMENT_ENABLED=1`, `--dry-run`, `--max-orders`, `--max-items`, `--max-shipments`, and low `--concurrency` from the approved VM/VPC/runtime only.
- Use `--sleep-ms`, `--error-threshold`, `--stop-on-rate-limit`, and `--resume-after-order-id` for staged continuation after sanitized counts are reviewed.
- Rollback is fail-closed: stop reconciliation runs, mark/read affected freshness markers as `stale` or `failed` from the approved runtime, and rerun corrected reconciliation only after the cause is understood. The older `rollback-to-NA` label now means marker rollback to formula-level `DATA_UNAVAILABLE`; it does not authorize serving guessed `NA` rows. Formula readers must return `DATA_UNAVAILABLE` when trusted markers are absent, stale, failed, partial, unauthorized, malformed, or basis-mismatched.

## Sanitized smoke intent

Use pilot seller `82453304` only as the known operational smoke seller. Shared evidence must keep the seller/range scope descriptive and sanitized: command shape, read-model names, marker states, aggregate counters, and issue codes are allowed; raw production rows, raw IDs, tokens, cookies, env values, OAuth codes, connection strings, buyer/address PII, and payloads are not.

An acceptable smoke note looks like:

```text
Scope: pilot seller 82453304, bounded date range approved for this run
Mode: dry-run, approved VM/runtime only
Read models: questions, claims, catalog_product_snapshots, catalog_buybox_snapshots
Result: no writes; sanitized expected/persisted/complete/missing counters reviewed
Next gate: explicit write authorization required before --write
```

## Phase 2 read-only contract

This PR2 helper contract defines what the approved runtime must collect before any write is considered. It does not execute production operations locally and it does not grant write approval.

### Required preflight targets

Collect sanitized aggregate counters for orders, shipments, items, sheets_item_formula_rows, sheets_item_sku_index, and status models.

Each target must report expected, persisted, missing, complete, NA, 0, and >0 counts. For formula rows, include distribution checks for listing type, current status, sale price, listing fixed fee, unit cost, realized shipping cost, realized fee, pack/cart ID, and buyer/address presence.

Status model checks are truth-bound: use observed `item_status_states` / `item_status_transitions` only. Do not synthesize paused/status history.

Observed pause-basis repair is intentionally bounded. It uses an existing reliable current status timestamp when present; otherwise it uses the repair execution time as a Zeler-observed basis. It must never be described as the historical Mercado Libre pause date.

### Required dry-run scopes

Dry-run June 1-4 for orders, shipments, pack/cart ID, buyer/address presence-only, realized shipping, and realized fees where implemented; otherwise keep NA.

### Export references

Record private export IDs/counts for `orders`, `shipments`, `items`, `sheets_item_formula_rows`, `sheets_item_sku_index`, and status models. Shared logs may include only sanitized export references and document counts, not raw documents or raw IDs.

Live runtime execution is pending until an approved VM/VPC/runtime command is available without deploy, push, restart, local production Mongo access, or production writes.

## Runtime boundary

- Do not query production Mongo locally; production Mongo validation or repair belongs only inside the approved VM/VPC/runtime-container context.
- Do not print connection strings, OAuth codes, cookies, credentials, env values, raw documents, or raw payloads.
- Operator output must contain aggregate counters only: expected, persisted, missing, complete, `NA`, `0`, `>0`, unauthorized, and error counts.
- Use private export references only as approved sanitized references; do not print raw collection documents or raw IDs.

## Stop criteria

Stop immediately and preserve only sanitized counts if any of these appear:

- unsanitized output
- unexpected count delta
- unauthorized PII
- validator or index anomaly
- auth error
- formula regression
- missing item-detail spike
- any output that violates this rule: no secrets, tokens, raw IDs, raw payloads, buyer/address PII, or raw env values

## Write boundary

The dry-run result is not write authorization. A write phase requires all of the following:

- completed sanitized dry-run review;
- approved VM/VPC/runtime execution;
- exact scoped production-write approval from the user;
- `--write --confirm-approved-runtime --confirm-production-write`;
- no active stop criteria.

If any condition is absent, do not insert, update, delete, deploy, restart, or repair production data.
