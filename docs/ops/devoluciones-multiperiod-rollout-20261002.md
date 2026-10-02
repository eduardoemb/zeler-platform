# DEVOLUCIONES multiperiod release — 2026-10-02

**Scoped rollout complete:** the approved DB contracts, three image targets and
June migration/activation are verified. Two normal renewals preserved June beyond
both original expiry horizons over 31 minutes 40 seconds. Final affected-service
health and observed-load capacity passed. August acquisition, native Google
Sheets proof and other-service acceptance remain outside this completed scope.
The genuine June interval is preserved. August acquisition is outside this release.
Completion rests on the measured runtime evidence below, not build success alone.

## Release identity and approvals

| Item | Evidence / boundary |
|---|---|
| Source | `17c30f46d25e1309b0df0003821b9674915854ef`, feature commit on `main`; local HEAD and `origin/main` independently matched at this report's preparation. |
| Commit scope | 36 feature implementation/test/schema/documentation files. Four unrelated incident/Google files were excluded and preserved. |
| User approval | Commit/push and deployment intent approved; three Cloud Builds explicitly approved, conditioned on exact published source. |
| Exact rollout approval | Received 20:35 UTC: the three verified target digests, two validators, four indexes, HOPEMOB June 1–10 migration/activation if proof validates, and >30-minute observation with two actual renewal checks. No August acquisition, deletion, cleanup or other-service expansion. |
| Target | GCP `zeler-platform-dev`; VM `platform-vm`, `us-central1-a`; Cloud Run Job in `us-central1`. |

Affected runtime scope is **Compose `sheets-api`, Compose `sheets-worker`, and the
image of Cloud Run Job `zeler-bootstrap`**. Updating the Job must not execute a
new acquisition. `bootstrap-dispatcher`, gateway and other product services remain
unchanged. Check for old in-flight bootstrap executions before activation; a Job
image update does not change an execution already running.

## Local verification, not runtime acceptance

| Context | Result |
|---|---|
| Full development worktree | 5,701 passed, 9 skipped in 262.23 s; protected rs0 cases separately 8 passed in 1.82 s (pre-release gate log). Full Ruff/check+format, mypy on 627 files, schema export and direct-Meli lint passed. Includes unrelated local Google diagnostic tests; not the clean-release test count. |
| Clean release archive | 5,660 tests passed; two Git-context checks could not pass in the archive context. Those two passed separately with Git context. **Do not label the whole archive invocation all-green.** |
| Exact-release GitHub CI | Commit `17c30f46d25e1309b0df0003821b9674915854ef`: [tests 37059697859](https://github.com/eduardoemb/zeler-platform/actions/runs/37059697859) and [lint 37059698019](https://github.com/eduardoemb/zeler-platform/actions/runs/37059698019) both SUCCESS, completed 20:24:38Z. Actual CI: **5,662 passed, 9 skipped in 346.01 s**; schema-export step SUCCESS. This independently validates the full clean Git artifact and resolves the release test gate. |
| Supplemental clean-release local checks | Protected rs0 cases separately **8 passed**; full mypy **625 source files** passed. These supplement CI rather than convert its skipped cases into claimed CI execution. |
| Independent SDD diagnostics | Renewal starvation, invalid-certificate status and schema inventory findings resolved; final local diagnostics successful. No production acceptance implied. |

Latest pre-release gate log: `/tmp/zeler-devoluciones-pre-release-gates-20261002.log`.
Historical root failures remain recorded in [apply-progress](../../openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md)
and [verification report](../../openspec/changes/zelerdata-devoluciones-multiperiod-coverage/verify-report.md).
An untouched inventory deadline case once observed one HTTP attempt instead of
zero; its whole file passed 11 tests immediately and an unchanged full-root rerun
passed. Cause remains unconfirmed; no test/code workaround was introduced.

## Predeploy read-only baseline

Observed **20:05–20:08 UTC**, before new images or DB mutations; revalidate before
rollout rather than treating this as continuing health proof.

- 11 containers running, 10 with healthchecks healthy; all restart counts 0 and
  OOM flags false. Gateway `/ready` and Sheets API `/health` returned 200; API
  readiness and Mongo/Rabbit/registry/claims-DLQ checks were true. Worker internal
  `/health` returned 200 and ready true; its host port is not published.
- Root free: **36,342,726,656 bytes**, 6,225,004 inodes. Mongo mount free:
  **48,135,151,616 bytes**, 3,276,297 inodes; dedicated ext4 mount at
  `/var/lib/zeler-mongo`. Available memory: **1,107,092 KiB**. Measure again during
  pulls/restarts; no invented memory threshold or cleanup authorization.
- Docker had 13 images, 11 active, 6.121 GB total; no cleanup performed or needed in
  this observation. Dry-run deployment preflight exited 0 and root exceeded 5 GiB.
  Repeat before every download and afterward; never prune volumes.
- VM/runtime Mongo metadata at 20:07:54 showed PRIMARY. Existing DEVOLUCIONES
  singleton was reconciled for **June 1 → June 11 exclusive**, backed by a completed
  quota run for exactly that interval; revision/proof and authorization existed.
  Marker updated 20:00:08.839, valid until 20:30:08.839. The operation was succeeded
  with an expired lease; no active bootstrap jobs were observed. Certificate
  collection did not yet exist. This is migration input, not proof that new
  migration validation will succeed.
- Cloud Run Job was Ready; 34 returned executions inspected, none incomplete and
  running count 0. Last successful execution completed September 25 at 21:08:45.431338Z.
  Recheck before activation.

No canonical rows, business identifiers, credentials or environment values are
included in this report.

## Fresh authorized preflight — 20:37:07 UTC

Read-only preflight passed before the approved phase 1–4 execution:

- 11 containers running, 10 healthy, all restart counts 0 and OOM flags false.
- Root free **36,328,493,056 bytes**; Mongo free **48,136,740,864 bytes** on the
  existing `/dev/sdb` mount. MemAvailable **1,001,872 KiB**.
- Prior Compose and running API/worker identities matched the recorded rollback
  references exactly. Stop grace is the default 10 seconds; outer deployment
  deadlines must exceed it.
- Mongo PRIMARY, runtime default database identity matched internally; no competing
  operation lease or active bootstrap jobs. June marker remains valid until
  **21:00:09 UTC**. No business identifiers or connection values were printed.
- Cloud Run active executions 0; prior bootstrap image still `c8cad281…` as fully
  identified below.

These are pre-mutation measurements. Subsequent phase evidence is recorded below;
these measurements alone do not prove image replacement, migration/activation or sustained renewal.

## Verified target builds

Submission manifest timestamp: **20:19:08 UTC**. All submissions use connected
repository `projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform`
and the exact source commit above. One deployable image per build, with
`requestedVerifyOption: VERIFIED`. The initial snapshot recorded QUEUED; the
updated ledger verifies SUCCESS, repository/source/build bindings and provenance
for all three (last check 20:20:48.396023 UTC).

| Image | Build ID | Status | Verified immutable target |
|---|---|---|---|
| `sheets-api` | `68f00abf-fb2f-4941-99b5-4dd87685aaa5` | SUCCESS / provenance verified | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:a9d33c3fcb428bb8502feba4b7a05084a08eeb4fa097069c6de40daafae1f72b` |
| `sheets-worker` | `906c1f5c-b41a-4788-8035-53c99348d09e` | SUCCESS / provenance verified | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:b0925d9251d1b34080435caa6f6f2224ce32e5842fbac626fc45224bb1a8bb66` |
| `bootstrap` | `546b5ca2-af97-4a18-b13c-7360f759e9d9` | SUCCESS / provenance verified | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/bootstrap@sha256:d459c9fd089117c925d2599830c9f2882b10d06e96ba39de18537509412a2a5f` |

These are the approved build targets. Running-image verification is recorded in
the phase evidence below; build attestations alone do not establish it.
Exact-release repository CI is now successful, independently resolving the clean
Git-artifact test gate. The exact runtime scope was subsequently approved at 20:35 UTC as recorded below.
Tags and passing CI alone are not deployment authority.

## Attested prior images / conservative rollback

The predeploy audit verified successful builds and provenance for these prior
references. Keep them retrievable and recheck deployment compatibility before any
approved replacement.

| Runtime | Immutable rollback image | Source commit | Build ID |
|---|---|---|---|
| Sheets API | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:210cbbf35dd4643351d243d4b97e5d7d49d9d81c88430fb001fda70de5423f64` | `5ceb3c0ab7828c675d200ee41e172abba3bcfd89` | `b88e9406-1d27-401a-8286-76133ded64b5` |
| Sheets worker | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:689bef61d82c3002b4409f4e65e3ccc507f71cc877d8c187b1ff72fe9e6c2d6e` | `320b373c4afe40b05357897b2e715c59913b4bc5` | `f059c54d-d98a-44ca-a05a-9d75874987e0` |
| Bootstrap Job | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/bootstrap@sha256:c8cad2815cce4429717c75d786c75d5d74da38b865d3da1fef71f889670c638e` | `85235300cfb6cd0661bf96b6bd63b94ba6eceb5b` | `a2637637-c201-4a57-8456-d0f834e0b8b4` |

Before restoring an incompatible writer after activation, withdraw certificate
read authority under the new compatible worker's guarded rollback command.
Preserve facts, receipts, certificates and additive DB contracts. Leave the
existing genuine singleton as-is; it may be narrower or unavailable. Do not
manufacture a legacy union or automatically undo canonical business data.

## Approved DB and activation sequence

The new operation acquisition writes coverage fields even in legacy mode, so
apply the approved additive DB scope **before deploying any new writer**:

1. Update validator `sheets_devoluciones_operations`.
2. Create `sheets_devoluciones_certificates` with complete validator, including
   sibling `$expr` and `$jsonSchema`.
3. Add only four indexes: `uniq_devoluciones_certificate_source` (unique),
   `idx_devoluciones_certificate_coverage`, `idx_devoluciones_certificate_due`,
   `idx_claims_seller_order_membership`. Preserve existing claims indexes.

No drop, TTL eviction, global drift repair or facts backfill is included. Sheets
images contain `infra/operations` but not `infra/mongo`; deliver the corrected
loader and scoped schema/index assets from the exact commit with hashes, using
approved temporary VM/runtime staging. The previous loader loses sibling `$expr`.
Confirm runtime DB identity internally without printing its connection string.

After DB verification, update only the three intended images; keep all other
settings/topology unchanged. Require zero incompatible old jobs. Inspect migration
read-only, then migrate/activate the HOPEMOB pilot's June 1–10 inclusive interval
(June 1 → June 11 exclusive) **only if complete receipts and current joint facts
validate**, and only under the approved scope. Preserve June source evidence; do
not admit or acquire August. Refusal is a stop, not permission to fabricate proof.
Observe independent renewal beyond 30 minutes with **at least two actual renewal
readbacks**, component/consumer health, digests,
capacity, restart/OOM state and runtime June formula-handler behavior. Image/DB phase
evidence and the completed sustained-renewal observations are recorded below. Native Google Sheets interaction is outside this probe scope
and remains unperformed, with no Google writes.

## Exact scope approved at 20:35 UTC

The user explicitly confirmed only: the three digest-bound image targets above; two named validators
and four named new indexes **before any new writer**; proof-validated June pilot
migration/activation; >30-minute observation with two real renewal readbacks; and
the conservative rollback references/order above. No August acquisition, data
erasure, Docker cleanup, broader topology change or other product rollout is
included. This specific confirmation is separate from the earlier commit/push/
deploy intent and build authorization. The bounded rollout and backend acceptance
are complete with the limitations recorded below.

## Phase evidence: DB, images, migration and activation

- Scoped schema inspection, application and verification all passed: exactly the
  two named validators and four new indexes. The certificate validator retained
  sibling `$expr`; no global validator repair, index deletion or data backfill
  is represented by this result.
- Prior DB metadata was backed up at
  `/var/lib/zeler-platform/releases/devoluciones-17c30f4/db-metadata-before.json`,
  file mode 0600. No contents or credentials are reproduced here.
- Cloud Run Job now uses the approved bootstrap target
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/bootstrap@sha256:d459c9fd089117c925d2599830c9f2882b10d06e96ba39de18537509412a2a5f`;
  observed Ready=True, generation 17.
- **Initial stop condition, now resolved:** the Job-spec hash after excluding the
  image changed. Read-only comparison identified only generated client-version
  and nonce metadata changes relative to the recorded preimage. Reconstruction
  matched the exact previously recorded spec hash. Evidence:
  `/tmp/devoluciones-job-spec-diff-17c30f4.json`. No repeated Job update was used
  to bypass the guard; the initial pause remains part of the execution history.
- Sheets API and worker now match their exact approved target digests above.
  Both are healthy/ready with their component checks passing, restart counts 0
  and OOM flags false. At approximately 20:52 UTC, reported root free capacity was
  35.242 GB, Mongo 48.136 GB and MemAvailable 1.871 GB (approximate reported values).
- The first June-gate invocation failed **before DB access** because execution
  from a file under `/tmp` could not import `infra`. Read-only VM import-layout
  checks confirmed that invocation issue; it was not evidence of invalid June
  data. Correct stdin invocation subsequently succeeded without a schema/data
  workaround.
- Corrected read-only gate at **20:57:36.552799 UTC**: eligible 1, unsupported 0,
  legacy mode, canonical count 5, exact June 1 → June 11 exclusive bounds; valid
  until 21:19:17.587 UTC. No competing lease or bootstrap jobs; fence/ack 3563.
- Following the write-only GO, migration completed at **20:58:39 UTC** with
  written 1 and mode legacy. The 20:57:36 before / 20:58:58 after comparison found
  canonical count 5, both canonical fingerprints and interval bounds **exactly
  unchanged**; the genuine legacy marker remained retained. Evidence:
  `/tmp/devoluciones-june-migration-comparison-17c30f4.json`.
- One explicit activation at **21:00:43 UTC** returned mode active, reactivated 1,
  unavailable 0 and unsupported 0. It did not acquire another period.

## Initial active acceptance — 21:01:06.134700 UTC

Read-only runtime acceptance passed (`application_writes=0`, provider calls 0):

| Check | Observed result |
|---|---|
| Certificate control | Active and compatible; invalid 0, expired 0; June 1 → June 11 exclusive quota-backed certificate, revision 2. |
| Preserved June formula | OK; claims 5, orders 5, output 4 rows × 4 columns through the runtime formula handler. |
| Uncertified extension | Crossing into June 11 returned `DATA_UNAVAILABLE`; no recovery read model/enqueue was created. |
| Current proof validity | Validated 21:00:43.394 UTC, valid until 21:30:43.394 UTC. |
| Renewal readiness | Capacity **unknown**, due 1. This is not yet stable/sustainable readiness. |
| Source boundary | Source advancement disabled; no August acquisition, provider call or Google write by the acceptance probe. |
| Native Sheet proof | **False / not performed**. Runtime handler output is not native Google Sheets evidence. |

Evidence: `/tmp/devoluciones-exec-acceptance-t0-17c30f4.json`. This initial
unknown-capacity state is retained as history; the actual later observations below
establish renewal and measured capacity rather than inferring them from t0.

## Completed renewal observation and final health

Readbacks at **21:17:25.770155 UTC** and **21:32:46.333091 UTC** span
**1,900.198391 seconds (31 minutes 40 seconds)** from t0. They observed two normal
worker renewals, not observer-triggered writes:

| Evidence point | Certificate validated at | Valid until | Revision |
|---|---|---|---|
| Activation / t0 | 21:00:43.394 UTC | 21:30:43.394 UTC | 2 |
| First renewal | 21:04:17.899 UTC | 21:34:17.899 UTC | 2 |
| Second renewal | 21:19:18.182 UTC | 21:49:18.182 UTC | 2 |

- Exact June bounds, original acquisition evidence, current facts digest,
  preactivation claim membership/canonical fingerprint and quota-state counters
  remained unchanged. No new period was acquired.
- Final runtime June query remained **OK: claims 5, orders 5, output 4×4**; the
  uncertified June 11 extension remained `DATA_UNAVAILABLE`. June remained readable
  after both the legacy singleton expiry and the t0 certificate expiry.
- Measured renewal interval **900.286665 seconds**, revisit estimate
  **990.286665 seconds**, sustainable batch **20**; capacity reported **sufficient
  for the observed load**. This is not an unlimited-history throughput guarantee.
- Observation scripts made **zero provider calls and zero application writes**.
  Source advancement remained disabled; no August acquisition or Google write.
  Native Google Sheets proof remains false/unperformed.

Comparison evidence:
`/tmp/devoluciones-renewal-final-comparison-17c30f4.json`.

Affected-service final health completed at **21:34:06.169842 UTC**:

- Sheets API and worker retained the exact approved digests, healthy status,
  restart counts 0 and OOM false. Both internal readiness endpoints returned
  HTTP 200 with ready=true and all reported component checks passing.
- Bootstrap Job retained the new target, Ready=true with generation/observed
  generation 17; active executions 0.
- Final capacity readback: root free **35,236,528,128 bytes** and 6,207,560 inodes;
  Mongo free **48,132,902,912 bytes** and 3,276,292 inodes, mount verified;
  MemAvailable **1,504,784 KiB**.

Evidence: `/tmp/devoluciones-exec-final-health-17c30f4.json` and
`/tmp/devoluciones-final-job-ready-17c30f4.json`.

**Broader-probe limitation:** an additional all-11-container probe at approximately
21:35 UTC exited 1 without stdout. It was not repeated; cause is unconfirmed.
Do not claim a successful final all-container inspection. The separate affected
API/worker/Job evidence above remains valid; the earlier 11-container baseline is
historical, not a substitute for this missing final broader check.

## Execution ledger

| Milestone | State |
|---|---|
| Feature commit/push to main | Verified exact source above |
| Three image builds | SUCCESS; exact source/build/provenance/digests verified |
| Repository CI gate | SUCCESS: exact-release tests 5662 / 9 skipped, lint and schema export; completed 20:24:38Z |
| Exact DB/image/migration rollout approval | Received 20:35 UTC for the bounded scope above |
| Fresh preflight | Passed 20:37:07 UTC; Job guard subsequently resolved; post-image health/capacity rechecked around 20:52 UTC |
| Two validators / four indexes | Inspect/apply/verify GREEN; exact scope, sibling `$expr` preserved |
| Bootstrap Job image | Approved digest installed; Ready=True, generation 17; recorded preimage hash reconstructed after only client-version/nonce metadata normalization |
| API / worker images | Exact approved targets running; healthy/ready, component checks passed, restart 0 / OOM false |
| June read-only gate | Correct stdin invocation GREEN 20:57:36.552799 UTC; original pre-DB import failure retained above |
| June migration write | Completed 20:58:39 UTC; one certificate; canonical fingerprints/count/bounds exactly preserved |
| Certificate activation | One activation completed 21:00:43 UTC; active, reactivated 1/unavailable 0/unsupported 0 |
| Runtime June / uncertified-extension probe | Passed 21:01:06 UTC; read-only, no recovery enqueue |
| Two renewal checks / >30-minute stability | Complete: two normal renewals observed over 1,900.198391 s; June survives original expiries; measured capacity sufficient for observed load |
| Final affected-service health | Exact API/worker digests, healthy/ready, all checks passing, restart 0 / OOM false; Job Ready, generation 17, active executions 0 |
| Additional all-container final probe | Exit 1 without stdout around 21:35 UTC; not repeated; no all-11 final-success claim |
| Native Google Sheets proof | Not performed; no Google writes |
| August acquisition | Explicitly outside scope; not performed |

Operator procedure: [multiperiod rollout](../../openspec/changes/zelerdata-devoluciones-multiperiod-coverage/rollout.md),
with the stricter DB-before-new-writer ordering above. Supporting sanitized inputs:
`/tmp/devoluciones-release-plan-20261002.md` and
`/tmp/devoluciones-new-builds-17c30f4.json`. These are snapshots, not live status.
This ledger records the completed authorized scope and its explicit evidence
limits. No broader acquisition, Google interaction, cleanup or service rollout is
implied by completion.

## Source drift at release close

All three affected running images are bound to the intended runtime source
`17c30f46d25e1309b0df0003821b9674915854ef`. The subsequent commit publishing this
report changes documentation only and does not require another image build.
No additional runtime-affecting main change is part of this delivery.
