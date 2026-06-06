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
  --confirm-approved-runtime
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
| `--include-buyer-address-pii` | Exceptional | Allows bounded buyer/address processing in approved runtime; output remains count-only. |

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
- validator error
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
