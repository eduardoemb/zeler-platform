# ZelerData read-model reconciliation

Use this runbook to plan ZelerData read-model reconciliation with sanitized, aggregate-only output. It documents the helper contracts only; it does not authorize production writes or local production Mongo access.

## Quick path

1. Run only from the approved VM/VPC/runtime container, never from the local assistant environment.
2. Start with `--dry-run` and `--confirm-approved-runtime`; review sanitized counters and issue codes only.
3. Stop before any write unless a separate production-write authorization explicitly allows `--write --confirm-approved-runtime --confirm-production-write` for the exact seller/range.
4. Roll back by stopping runs and marking affected freshness markers `stale`/`failed` from the approved runtime; formulas stay `DATA_UNAVAILABLE` until complete markers exist again.
5. For observed pause-basis repair, start with `--repair-observed-pause-basis --dry-run --confirm-approved-runtime`; write mode is a later approved runtime action only.

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
  --read-model devoluciones \
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

The timer runs every 10 minutes, with at most one minute of random delay. Each invocation has one
single scheduled attempt with a 175-second shell stop; there is no wrapper retry or sleep that can
reset the source-call recorder. `Persistent=true` provides catch-up after downtime, and
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
sudo /opt/zeler-platform/zelerdata-devoluciones-enable-timer.sh
sudo journalctl -u zelerdata-devoluciones-reconcile.service \
  -u zelerdata-devoluciones-reconcile-alert.service --since "30 minutes ago" \
  --no-pager
```

### Intentional state

The timer is intentionally disabled and no campaign is currently accepted.
`ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH` defaults to `2026-07-09`, and campaign
identity (campaign ID plus both source/read-model fingerprint hashes) is sourced
only from `/etc/zeler-platform/zelerdata-devoluciones-reconcile.env`. Until a
campaign is durably accepted for the release,
`infra/operations/devoluciones_timer_status.py` reports
`timer_active=false` and `has_accepted_campaign=false`; the status script never
reads Mongo or private samples and never enables the timer.

Use **failure-conditional rollback** only after a failed deployment, topology,
write, formula, or timer gate. Disable the timer, stale readiness through the
topology rollback, restore the prior worker runtime/routing/schedule, and retain
verified idempotent facts. Never roll back a successful release automatically.

## Focused source and runtime budget

The scheduled command MUST use `--read-model devoluciones`. This selects one
claims-first immutable snapshot for proof and writes, followed by bounded targeted
revalidation; broad order-date, questions, items, shipments, and catalog hydration is prohibited.
Only authoritative claim pages, relevant claim/return details, and orders referenced by those
claims are allowed.

The sanitized physical-attempt recorder reports claim-page attempts (`P`), claim/return detail
attempts (`R`), order-detail attempts (`O`), and total attempts (`T`). Retries and failures are
charged before send. For each frozen inventory snapshot, `B = P + 3H` and `B ≤ 104`; a scheduled
write may use no more than two independent snapshots and must remain within the inclusive run cap
`C ≤ 208`. The attempt that would become 105 or 209 is rejected before send and is not counted.
Concurrency remains no greater than four, with a 165-second process deadline and a 175-second shell
stop. The single scheduled attempt cannot reset either snapshot or run accounting.

The focused run enforces a code-owned **1.25-second minimum start-to-start interval** for physical RETURNS attempts only.
The first RETURNS send does not wait, and pacing occurs before each later
send rather than after the previous or final send. Pre-detail cancellation exclusions never enter
the pacer; authoritative safe-404 exclusions do because absence is known only after the physical
RETURNS response. Claim-page, claim-detail, and order-detail sends are not paced. In frozen
inventory order, one pacer spans both snapshots so publication revalidation cannot create a
boundary burst.

The monotonic 165-second deadline is checked before a required wait and again after wakeup. If the
remaining margin cannot contain the wait, reconciliation fails before sleeping, charging, or
sending; if the deadline is reached after wakeup, it fails before charge/send. Otherwise the
existing recorder charges before exactly one physical send. A 429 remains terminal and the focused
path does not retry, expand `B ≤ 104` or `C ≤ 208`, or alter public/private evidence.

For the complete 34-candidate inventory, pacing inserts at most 33 intervals per snapshot and 67
per two-snapshot run: at most 41.25 seconds per snapshot and 83.75 seconds per run. The retained
110-second projected run envelope preserves 55 seconds of process-deadline margin and 65 seconds
before the shell stop. Acceptance still requires private timing correlation proving every
successive physical RETURNS start is at least 1.25 seconds apart, followed by fresh `9/9/9/0`
evidence. Any spacing, deadline, source, or 429 failure stops without retry, keeps the timer off,
and uses the existing failure-conditional rollback boundary.

Runtime acceptance requires 20 consecutive candidate-equivalent scheduled writes with stable
source/read-model fingerprints and one explicit campaign ID. A timeout, non-success, hard-limit
failure, source budget failure, or fingerprint drift disqualifies that campaign ID. Recovery requires
20 new valid writes under a new explicit campaign ID; a rolling last-20 window cannot forget the
failure. Set the reviewed non-secret `ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID` for each new campaign. Compute
nearest-rank p95 as `ceil(0.95 × eligible sample count)` over the actual durable window: every run must remain below 180 seconds; p95 must remain below 150 seconds. Enable scheduling last; the timer stays disabled
until source, write, marker, formula/operator, rollback, and timing evidence all pass.

Every allowlisted sample is atomically persisted at
`/var/lib/zeler-platform/zelerdata-devoluciones-campaign.json`. Disqualified campaign IDs are
permanent: an A→B→A sequence cannot reuse A to clear its failure. The timer enablement wrapper calls
the durable `require-accepted` preflight and refuses incomplete, p95-failing, hard-limit, drifted, or
previously disqualified campaigns.

The reconciliation command emits its typed scheduled transport only when the wrapper passes
`--private-scheduled-transport`. The transport is written under `umask 077`, parsed into a private campaign sample,
persisted to the schema-v1 campaign state, and deleted. Campaign identity, timing,
disqualification, and success-only source/read-model fingerprint hashes never enter stdout,
journald, or other shared evidence.

Every public path, including child failure, timeout, malformed evidence, state failure, publication
failure, and early wrapper fallback, emits exactly one JSON object with the keys `stage`, `status_class`, and `counters`.
The stage is `scheduled`; status classes and non-negative aggregate
counters are bounded. Child exits `42`, `124`, and arbitrary nonzero values remain authoritative.
Exit `65` and status class `evidence_invalid` are reserved for true evidence-contract errors; state and publication tooling retain their
actual nonzero exits. Raw output is never published and all temporary files are removed after state handling and publication.

## Registration and rollback-compatible API

The canonical Sheets manifest and registry contain exact 11 scopes and 5 routing keys, including
passive metadata for `claims.updated`. Physical claims bindings remain independently controlled by
the topology operation. Sheets startup registration completes before readiness, and `/health`
requires the exact canonical registry fingerprint before healthy; counts alone never pass.
This is an explicit registry fingerprint before healthy gate, not periodic repair.

For an ordinary worker/source rollback, retain the corrected candidate API while it is healthy so
its merge-safe registration writer keeps the registry exact. An API rollback may use only a
prebuilt immutable rollback-compatible API image: the approved prior API application,
dependencies, and entrypoint plus the corrected runtime manifest/registration writer and canonical
Sheets manifest. The old 8/4 writer is prohibited.

Run `infra/gce/docker-deploy-preflight.sh` with `SHEETS_ROLLBACK_PREFLIGHT=1`, an exact Artifact
Registry `repo@sha256` image reference, and the expected source commit. Repository JSON alone is not authority.
For Cloud Build v2 connected-repository builds, also set `SHEETS_ROLLBACK_CONNECTED_REPOSITORY`
to the expected repository resource. The preflight accepts the commit from either legacy
`sourceProvenance.resolvedRepoSource.commitSha` or from Cloud Build v2
`source.connectedRepository.revision`, but the v2 path passes only when
`source.connectedRepository.repository` matches the expected resource exactly.
The preflight queries trusted external authority with
`gcloud artifacts docker images describe IMAGE@sha256 --show-provenance --format=json`, extracts the
build identity, then runs `gcloud builds describe BUILD_ID --format=json`. It requires a successful
Cloud Build SLSA provenance and contract step proving prior API base behavior, the exact allowed tree, corrected
manifest/registration writer, actual `zeler_sheets.app:make_app --factory` entrypoint, clean-restart
health, and the full canonical registration fingerprint. An unknown digest or unavailable provenance
fails closed: unknown digest fails closed without a repository fallback. The wrapper prints verification status only. If the compatible image is missing or
unverified, retain a healthy candidate API. If it is also unhealthy, stop it and keep the Sheets API unavailable; never start the unsafe writer. Repeated rollback must reassert the selected safe digest,
stale readiness, timer off, claims unbound, and exact 11/5.

Execute production rollback only through `/opt/zeler-platform/sheets-rollback-execute.sh`. It disables
the timer, invokes topology rollback to stale readiness and unbind claims, restores prior worker/source
images, retains the verified candidate API or starts the externally verified rollback-compatible API,
and checks the running container `RepoDigest`, `/health`, and exact registry fingerprint before healthy.
The old 8/4 writer is prohibited; missing safe evidence stops `sheets-api` and fails closed. Repeated
execution is idempotent.

The startup-installed preflight is parity-bound to the canonical
`infra/gce/docker-deploy-preflight.sh` artifact. CI extracts the exact startup heredoc, compares it
byte-for-byte, and executes that installed copy against forged and unknown digests. A startup change
must not overwrite the operational path with an attestation-free implementation.

Record only sanitized evidence:

```text
candidate/prior/rollback-compatible digests: verified
Cloud Build provenance, digest binding, allowed tree, entrypoint, health, clean restart: verified
registry fingerprint: exact 11/5
focused source calls: P=<count> R=<count> O=<count> T=<count>
campaign: 20 consecutive; every run <180s; nearest-rank p95 <150s
readiness/topology/timer: stale or accepted as appropriate; claims binding explicit; timer last
```

Do not include raw environment values, credentials, tokens, connection strings, source payloads,
or production document identifiers in shared evidence.

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
| `--repair-observed-pause-basis` | Optional repair scope | Plans or runs bounded repair for current paused rows missing `paused_since`. Dry-run mutates nothing and reports sanitized aggregate counters only. Write mode still requires `--write --confirm-approved-runtime --confirm-production-write` plus explicit scoped approval. |

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
- Pilot with `ZELERDATA_ENRICHMENT_ENABLED=1`, `--dry-run`, `--confirm-approved-runtime`, `--max-orders`, `--max-items`, `--max-shipments`, and low `--concurrency` from the approved VM/VPC/runtime only.
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
