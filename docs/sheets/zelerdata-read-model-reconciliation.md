# ZelerData read-model reconciliation

Use this runbook to plan the June 1-4 ZelerData read-model reconciliation with sanitized, aggregate-only output. It documents the helper contracts only; it does not authorize production writes or local production Mongo access.

## Quick path

1. Run only from an approved VM/VPC/runtime, never from the local assistant environment.
2. Start with `--dry-run` and `--confirm-approved-runtime`.
3. Stop before any write unless a separate production-write authorization explicitly allows `--write --confirm-production-write`.

## Command shape

```bash
uv run python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id <seller> \
  --date-from 2026-06-01 \
  --date-to 2026-06-04 \
  --dry-run \
  --confirm-approved-runtime \
  --emit-phase2-contract
```

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

## Rollout and rollback

- Keep `ZELERDATA_ENRICHMENT_ENABLED` disabled until the additive models and formula readers are deployed.
- Pilot with `ZELERDATA_ENRICHMENT_ENABLED=1`, `--dry-run`, `--max-orders`, `--max-items`, `--max-shipments`, and low `--concurrency` from the approved VM/VPC/runtime only.
- Use `--sleep-ms`, `--error-threshold`, `--stop-on-rate-limit`, and `--resume-after-order-id` for staged continuation after sanitized counts are reviewed.
- Rollback is `rollback-to-NA`: disable `ZELERDATA_ENRICHMENT_ENABLED` and stop reconciliation writes. Formula readers must return `NA` when trusted snapshots are absent, stale, unauthorized, malformed, or basis-mismatched.

## Phase 2 read-only contract

This PR2 helper contract defines what the approved runtime must collect before any write is considered. It does not execute production operations locally and it does not grant write approval.

### Required preflight targets

Collect sanitized aggregate counters for orders, shipments, items, sheets_item_formula_rows, sheets_item_sku_index, and status models.

Each target must report expected, persisted, missing, complete, NA, 0, and >0 counts. For formula rows, include distribution checks for listing type, current status, sale price, listing fixed fee, unit cost, realized shipping cost, realized fee, pack/cart ID, and buyer/address presence.

Status model checks are truth-bound: use observed `item_status_states` / `item_status_transitions` only. Do not synthesize paused/status history.

### Required dry-run scopes

Dry-run June 1-4 for orders, shipments, pack/cart ID, buyer/address presence-only, realized shipping, and realized fees where implemented; otherwise keep NA.

### Export references

Record private export IDs/counts for `orders`, `shipments`, `items`, `sheets_item_formula_rows`, `sheets_item_sku_index`, and status models. Shared logs may include only sanitized export references and document counts, not raw documents or raw IDs.

Live runtime execution is pending until an approved VM/VPC/runtime command is available without deploy, push, restart, local production Mongo access, or production writes.

## Runtime boundary

- Do not query production Mongo locally.
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
