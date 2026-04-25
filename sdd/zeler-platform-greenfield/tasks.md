# Tasks: zeler-platform-greenfield

**Change**: `zeler-platform-greenfield`
**Mode**: hybrid (Engram + filesystem)
**TDD**: Strict — every non-trivial task must have a failing test written BEFORE the implementation.
**Date**: 2026-04-23

---

## Roadmap Overview

```
Phase 0: Foundations (infra + cluster + monorepo)          → XL  (~2 weeks)
Phase 1: Gateway MVP (OAuth + accounts + proxy)            → XL  (~3 weeks)
Phase 2: Webhooks + Event Bus                              → L   (~1.5 weeks)
Phase 3: Core Models + Repos + Bootstrap                   → L   (~2 weeks)
Phase 4: Module Runtime + Repricer (reference module)      → L   (~2 weeks)
Phase 5: zeler-app integration                             → M   (~1 week)
Phase 6: Remaining modules (Sheets, Publicador, Autoreply, FullDock)  → XL  (~4 weeks, parallel)
Phase 7: Legacy decommission                               → M   (~1 week)
```

**Dependency graph**:
```
P0 ─→ P1 ─→ P2 ─→ P3 ─→ P4 ─→ P5
                   P3 ─→ P6 (parallel: sheets ∥ publicador ∥ autoreply ∥ fulldock)
P4 ─→ P7
P5 ─→ P7
P6 ─→ P7
```

**Critical path**: P0 → P1 → P2 → P3 → P4 → P7

---

## Phase 0: Foundations

**Goal**: Provision infrastructure, create the monorepo skeleton, wire CI/CD. No business logic yet.

**Exit criteria**:
- `zeler-platform/` repo exists, uv workspace resolves, ruff + mypy + pytest green on empty suite.
- Atlas cluster `zeler-platform-prod` (M30) and `zeler-platform-dev` (M10) reachable from CI.
- GCP KMS keyring + `meli-tokens` key created.
- GitHub Actions pipeline passes on every push to `main`.

**Dependencies**: none

**Parallelizable**: P0.3–P0.6 can run in parallel after P0.1; P0.7–P0.9 after P0.3.

**Risks**:
- Atlas private endpoint + Serverless VPC Access setup is error-prone; allocate extra time.
- KMS IAM permissions scope can block P1 token encryption.

---

### Checklist

- [x] **P0.1** — Create `zeler-platform` GitHub repo
  Bootstrap empty repo (MIT or private), add `.gitignore` (Python, uv), initial `README.md` with architecture diagram from design §1. Enable branch protection on `main`.
  *Ref*: design §3. *TDD*: N/A (infra). *Effort*: XS

- [x] **P0.2** — Scaffold uv workspace root
  Create root `pyproject.toml` (`[tool.uv.workspace] members = ["gateway","core","modules/*","bootstrap"]`), `.python-version` = `3.11`, `uv.lock`. Add ruff, mypy, pytest, pre-commit at root. Run `uv sync` and commit lockfile.
  *Ref*: design §3, §2 (D1). *TDD*: `pytest --collect-only` exits 0. *Effort*: S

- [x] **P0.3** — Create per-package skeletons (`gateway`, `core`, `bootstrap`)
  Each has `pyproject.toml` declaring `zeler_platform_core` as workspace dep, `src/<pkg>/` layout, `__init__.py`, minimal `conftest.py`. Run `uv sync --package gateway` and verify import works.
  *Ref*: design §3. *TDD*: `import zeler_gateway` in a test, must pass. *Effort*: S

- [x] **P0.4** — Create module skeletons (`repricer`, `sheets`, `publicador`, `autoreply`, `fulldock`)
  Same pattern as P0.3. Each `modules/<name>/pyproject.toml` depends on `zeler_platform_core`. Placeholder `manifest.yaml` (name, version, subscribed_events: [], owned_collections: []).
  *Ref*: design §3, spec §5. *TDD*: `import zeler_repricer` et al. pass. *Effort*: S

- [x] **P0.5** — Configure ruff + mypy + pre-commit at workspace root
  Root `pyproject.toml`: `[tool.ruff]` line-length=120, select=["E","W","F","I","UP","B"], `[tool.mypy]` strict=true, per-member overrides. Pre-commit hooks: ruff-format, mypy, trailing-whitespace, end-of-file-fixer. Add `gitleaks` hook (secret scanning, design §9).
  *Ref*: design §2, §9. *TDD*: `pre-commit run --all-files` exits 0 on empty skeletons. *Effort*: S

- [x] **P0.6** — ~~Provision Atlas clusters~~ **SUPERSEDED by P0.6.1-P0.6.6 (Docker-local Mongo, decision D8 v3)**
  Atlas was replaced by Docker-local Mongo for dev + on-prem Mongo for prod. Implemented as P0.6.1-P0.6.6 (Batch A): `infra/docker/mongo-dev.yml`, `infra/mongo/apply_validators.py`, 17 placeholder schemas. Delta canon: engram `sdd/zeler-platform-greenfield/tasks` #2164.
  *Ref*: design §10 v2. *Effort*: L — DONE

- [x] **P0.7** — ~~Atlas network + DB users~~ **REMAPPED to GCP project + APIs**
  GCP project `zeler-platform-dev` (#721178147108) + 12 APIs enabled (Cloud Run, KMS, Secret Manager, Artifact Registry, etc.). Mongo auth via root credentials env vars (dev) + on-prem user creds (prod, later).
  *Ref*: design §10 v2. *Effort*: M — DONE

- [x] **P0.8** — Provision GCP KMS keyring + keys
  Terraform: `infra/terraform/gcp/kms.tf` — keyring `zeler` in `us-central1`, key `meli-tokens` (AES-256, HSM-backed, 90-day rotation), key `platform-jwt` (EC P-256, asymmetric signing). Grant `cloudkms.cryptoKeyEncrypterDecrypter` to gateway service account.
  *Ref*: design §5.2, §9. *TDD*: `gcloud kms encrypt --test` smoke test in CI. *Effort*: M

- [x] **P0.9** — Wire GitHub Actions CI matrix
  `.github/workflows/ci.yml`: matrix over `[gateway, core, bootstrap, modules/repricer]`. Each job: `uv sync --package <pkg>`, `ruff check`, `mypy`, `pytest tests/`. Separate job: `terraform validate` + `tflint` on `infra/`. Add `gitleaks` scan job. Cache uv deps.
  *Ref*: design §2. *TDD*: CI passes on empty test suites (0 collected, exit 0). *Effort*: M

- [x] **P0.10** — Write `CONTRIBUTING.md` with TDD mandate (+ Meli OAuth app + GCS bucket + SA `mongo-backup-writer`, remapped from Atlas-era scope)
  Document: TDD workflow (RED→GREEN→REFACTOR), branch naming (`feat/<pkg>/<slug>`), PR checklist (mypy clean, ruff clean, all tests green, new tests required for every PR), how to run local pytest, how to update uv.lock. Reference gitleaks and the "no direct Meli call" AST rule (explained in P4).
  *Ref*: proposal §3. *TDD*: N/A (doc). *Effort*: XS

- [x] **P0.11** — Create `infra/mongo/schemas/` JSON Schema placeholders + apply script
  17 placeholder JSON files (14 from design + `stock_locations` + `events` + `competition_snapshots` added for FullDock topic coverage). Script `infra/mongo/apply_validators.py` applies `$jsonSchema` via pymongo `collMod` — targets Docker-local Mongo (dev) and on-prem Mongo (prod). Smoke test e2e: 17 collections aplicadas contra Mongo Docker real.
  *Ref*: design §4, §10 v2, spec §4 R4.2. *Effort*: S — DONE

- [x] **P0.12.1-P0.12.3** — Mongo backup cron + restore runbook (added in delta)
  `infra/mongo/backup/mongodump_cron.sh` (+x, portable date cutoff for GNU/BSD), operator README, restore runbook. GCS bucket `zeler-platform-backups` (US-CENTRAL1, 35-day retention). SA `mongo-backup-writer`. Contract tests green.
  *Ref*: design §13. *Effort*: M — DONE

---

## Phase 1: Gateway MVP

**Goal**: Working OAuth flow, account storage with encrypted tokens, refresh worker, outbound proxy, structured logging. The core Meli integration surface.

**Exit criteria**:
- `GET /oauth/authorize` redirects to Meli with correct scopes + CSRF state.
- `GET /oauth/callback` exchanges code, encrypts tokens, upserts `meli_accounts`, returns 302.
- `POST /proxy/meli/*` with valid internal JWT proxies to mock Meli and returns response.
- Refresh worker correctly handles success, concurrent lock, and `invalid_grant`.
- All integration tests pass against `httpx`/`respx` mock Meli.

**Dependencies**: P0 complete

**Parallelizable**: P1.4–P1.6 (OAuth flow) and P1.7–P1.9 (encryption + refresh) can parallelize after P1.1–P1.3.

**Risks**:
- KMS DEK cache invalidation across multiple replicas — design §5.2 covers this but implementation detail matters.
- Meli OAuth flow requires a real registered app ID; use a test app in dev.
- Distributed lock stale-lock cleanup logic is subtle.

---

### Checklist

- [x] **P1.1** — [RED] Write failing integration tests for OAuth happy path
  Tests: `test_oauth_authorize_redirects_to_meli`, `test_oauth_callback_upserts_meli_account`, `test_oauth_callback_invalid_grant_returns_400`. Use `respx` to mock `https://auth.mercadolibre.com` and `https://api.mercadolibre.com/oauth/token`. Assert DB state after callback.
  *Ref*: spec §1 R1.1, §2 R2.1. *TDD*: tests must FAIL (no implementation). *Effort*: M

- [x] **P1.2** — Scaffold `gateway` FastAPI app
  `gateway/src/zeler_gateway/app.py`: FastAPI instance, lifespan handler (startup: connect Mongo, init APScheduler, warm DEK cache; shutdown: stop scheduler). Add `gateway/Dockerfile` (uv-based, non-root user). Wire settings via `pydantic-settings` + GCP Secret Manager loader.
  *Ref*: design §3, §5. *TDD*: `GET /health` returns 200. *Effort*: S

- [x] **P1.3** — Create `meli_accounts` collection + Atlas validator
  `infra/atlas/meli_accounts.json`: full `$jsonSchema` (required fields per design §4.2). Apply to dev cluster. Create unique index `{seller_id:1, app_id:1}`, status+expires index, sparse lock index.
  *Ref*: design §4.2, spec §2 R2.1–R2.2. *TDD*: Raw insert missing required field raises Atlas validation error. *Effort*: S

- [x] **P1.4** — Implement KMS envelope encryption module
  `gateway/src/zeler_gateway/tokens/encryption.py`: `encrypt_token(plaintext) → EncryptedToken`, `decrypt_token(EncryptedToken) → str`. AES-256-GCM; DEK generated per account on first write; DEK wrapped by KMS `meli-tokens` key. LRU DEK cache (max 1000, TTL 5 min).
  *Ref*: design §5.2. *TDD*: `test_encrypt_decrypt_roundtrip`, `test_dek_cache_hit_no_kms_call` (spy on KMS client). *Effort*: M

- [x] **P1.5** — Implement OAuth `/oauth/authorize` endpoint
  `gateway/src/zeler_gateway/oauth/router.py`: `GET /oauth/authorize?platform_user_id=<id>` → build KMS-signed state JWT (10 min TTL) → redirect to `https://auth.mercadolibre.com/authorization` with `client_id`, `redirect_uri`, `response_type=code`, `state`. Config: `MELI_CLIENT_ID`, `MELI_REDIRECT_URI`.
  *Ref*: design §5.1, spec §1 R1.1. *TDD*: P1.1 test `test_oauth_authorize_redirects_to_meli` now GREEN. *Effort*: S

- [x] **P1.6** — Implement OAuth `/oauth/callback` endpoint
  `GET /oauth/callback?code=&state=`: verify state JWT → exchange code via Meli `POST /oauth/token` → construct `MeliAccount` Pydantic model (seller_id as string→long coercion) → `encrypt_token()` both tokens → upsert to `meli_accounts` with `updateOne({seller_id, app_id}, $set, upsert=true)` → emit AMQP `accounts.linked` (stub queue for now) → 302 to success page.
  *Ref*: design §5.1, spec §1 R1.1 scenarios, §2 R2.1–R2.3. *TDD*: P1.1 remaining tests now GREEN. *Effort*: M

- [x] **P1.7** — [RED] Write failing tests for refresh worker
  Tests: `test_refresh_acquires_lock_and_updates_tokens`, `test_concurrent_refresh_second_worker_skips`, `test_invalid_grant_sets_status_revoked`. Use `mongomock` or test Atlas dev cluster + `respx` for Meli refresh endpoint.
  *Ref*: spec §1 R1.2 scenarios. *TDD*: all FAIL. *Effort*: S

- [x] **P1.8** — Implement distributed lock + refresh worker
  `gateway/src/zeler_gateway/tokens/refresh_worker.py`: APScheduler interval 5 min. Query `{status: {$in:["active","refresh_pending"]}, access_token_expires_at: {$lt: now+15min}}`. Attempt `findOneAndUpdate` lock (design §5.3 exact query). On lock acquired: decrypt → call Meli refresh → re-encrypt → unset lock → update `last_refresh_at`. On `invalid_grant`: `status=revoked`, emit `accounts.revoked` AMQP event, no retry. Structlog event `refresh.run` with stats.
  *Ref*: design §5.3, spec §1 R1.2 + §2 R2.3. *TDD*: P1.7 tests now GREEN. *Effort*: L

- [x] **P1.9** — [RED] Write failing tests for outbound proxy
  Tests: `test_proxy_call_injects_token_and_forwards`, `test_proxy_call_during_refresh_waits_or_503`, `test_proxy_unknown_module_returns_401`, `test_proxy_out_of_scope_path_returns_403`, `test_rate_limit_exceeded_returns_429`.
  *Ref*: spec §1 R1.3–R1.4. *TDD*: all FAIL. *Effort*: S

- [x] **P1.10** — Implement internal JWT mint/verify
  `core/src/zeler_platform_core/auth/jwt.py`: `mint_module_jwt(module_id, seller_id, ttl_s=60) → str`, `verify_module_jwt(token) → Claims`. Uses KMS asymmetric key `platform-jwt` (EC P-256). `iss=f"module:{module_id}"`, `aud="gateway"`. Cached public key (5 min).
  *Ref*: design §8.2, spec §5 R5.2. *TDD*: `test_mint_verify_roundtrip`, `test_expired_jwt_raises`, `test_wrong_aud_raises`. *Effort*: S

- [x] **P1.11** — Implement `/proxy/meli/*` endpoint
  `gateway/src/zeler_gateway/proxy/router.py`: verify internal JWT (P1.10) → load `module_registry` entry → check `allowed_meli_scopes` glob match → load `meli_accounts` for `seller_id` (status must be `active` else 412) → decrypt access_token (DEK cache) → forward HTTP call to Meli with retry policy (P1.12) → write `audit_log` doc → return Meli response verbatim.
  *Ref*: design §5.4, spec §1 R1.3. *TDD*: P1.9 tests now GREEN. *Effort*: L

- [x] **P1.12** — Implement retry policy for Meli calls
  `gateway/src/zeler_gateway/proxy/retry.py`: exponential backoff + jitter, max 3 attempts. Retry on 5xx + network timeout; never retry 4xx except 429 (respect `Retry-After`). Log each attempt (`structlog`).
  *Ref*: spec §1 R1.5. *TDD*: `test_502_then_200_surfaces_200`, `test_404_not_retried`. *Effort*: S

- [x] **P1.13** — Implement per-(module, account) rate-limit budget middleware
  `gateway/src/zeler_gateway/proxy/rate_limit.py`: sliding-window counter stored in Mongo `rate_limit_counters` (or in-memory with replica caveats — document trade-off). Default 60 req/min per (module, seller_id). On exceed: 429 + `Retry-After`. Emit metric `rate_limit_exceeded` labeled by module + seller_id.
  *Ref*: spec §1 R1.4. *TDD*: P1.9 `test_rate_limit_exceeded_returns_429` now GREEN. *Effort*: M

- [x] **P1.14** — Wire structured logging + OpenTelemetry hooks in gateway
  Configure `structlog` JSON renderer for production. Add `opentelemetry-sdk` + GCP Cloud Trace exporter. Instrument: every request gets `trace_id`, every Meli call logged with `{module_id, seller_id, path, status, duration_ms}`.
  *Ref*: spec §1 R1.6, design §2. *TDD*: `test_log_output_is_valid_json`, `test_trace_id_propagated`. *Effort*: S

- [x] **P1.15** — Create `users` collection + Atlas validator
  `infra/atlas/users.json`: $jsonSchema (design §4.1). Unique index `{email:1}`, index `{meli_account_ids:1}`. Stub `POST /auth/register` (gateway internal) accepting `email`, `name`, `auth_provider`, returns created user doc. (Full auth integration is P5.)
  *Ref*: design §4.1. *TDD*: validator rejects doc missing `email`. *Effort*: S

- [x] **P1.16** — Create `audit_log` collection + Atlas validator + TTL index
  `infra/atlas/audit_log.json`. TTL index `{at:1}` 365 days. Indexes `{module_id:1, at:-1}`, `{seller_id:1, at:-1}`. Verify gateway proxy writes one doc per proxied call (integration test).
  *Ref*: design §9, §10. *TDD*: Integration test asserts `audit_log` doc written after proxied call. *Effort*: XS

- [x] **P1.17** — Implement bounded Prometheus metrics collector + `/metrics` endpoint for spec R1.6
  `gateway/src/zeler_gateway/observability/metrics.py`: lightweight in-process Prometheus text collector gated by `OTEL_METRICS_ENABLED`. Expose counters (call_count, rate_limit_hits, refresh_success, refresh_failure, invalid_grant), histograms (latency_ms), and middleware timings by bounded labels such as `module_id`, `endpoint`, and status where applicable. External Prometheus/PromQL derives p95 latency and error-rate rollups over windows such as 5m. Raw `account_id`/seller labels are intentionally omitted by default to avoid high-cardinality series; account drilldown uses logs/traces or a future controlled sampling/allowlist design. Update proxy/router.py and refresh_worker.py to emit counter increments.
  *Ref*: spec §1 R1.6 (metrics clause + operator-query scenario). *TDD*: `test_metrics_endpoint_returns_prometheus_format`, `test_rate_limit_hit_increments_counter`, `test_latency_histogram_records_request_duration`. *Effort*: M
  *Note*: deferred from P1.14 (which only implemented logs + traces), then implemented in commit `8d5f3cd` and reconciled here as the accepted bounded Prometheus design.

#### P1.17 — Archive/Reconciliation Marker

**Archive type**: Deferred Phase 1 task reconciliation (change remains open for Phase 7)
**Archive date**: 2026-04-24
**Verified commit**: `8d5f3cd` (`feat(gateway): add Prometheus metrics endpoint`)
**Verify report reference**: Engram #2363 `sdd/zeler-platform-greenfield/verify-report-p1-17-metrics` (`PASS_WITH_WARNINGS`, CRITICAL=0)
**Accepted design**: bounded in-process Prometheus text collector gated by `OTEL_METRICS_ENABLED`; external Prometheus/PromQL computes p95/error-rate rollups; no raw `account_id` metric label by default.
**Quality gates cited**: `uv run pytest` ✅ (`261 passed`) · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · `uv run python -m infra.lint.check_direct_meli .` ✅
**Carry-forward warnings**:
- Add focused proxy/refresh-worker behavioral metric integration tests when expanding observability coverage; current archive accepts static implementation evidence plus endpoint/helper tests.
- Metrics are per-process/per-instance until scraped and aggregated externally; account-level drilldown remains logs/traces or a future controlled sampling/allowlist mechanism.

---

### Phase 1 — Archive Markers

**Archive type**: Phase milestone (change remains open for Phase 2+)
**Archive date**: 2026-04-24
**Final HEAD SHA**: `6d3590f`
**Total Phase 1 commits**: 23 (ca78051 → 6d3590f)
**Test count**: 84 passed / 0 failed / 0 skipped
**Quality gates**: `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅
**Verify report reference**: Engram #2249 (PASS WITH WARNINGS, CRITICAL=0, WARNING=6, SUGGESTION=3)
**Tasks completed**: P1.1–P1.16 at original Phase 1 archive; P1.17 later completed/reconciled via the P1.17 archive marker above.
**Tasks deferred**: none after P1.17 reconciliation; original deferral was resolved by commit `8d5f3cd` and Engram verify #2363.

---

## Phase 2: Webhooks + Event Bus

**Goal**: Receive Meli webhooks, validate them, persist idempotently, publish to RabbitMQ. Full DLQ topology.

**Exit criteria**:
- `POST /webhooks/meli` from allowed IP: 200 within 500ms, event in `webhook_events`, event in RabbitMQ.
- Duplicate notification: 200, no duplicate in `webhook_events`, no re-publish.
- Invalid IP: 401, nothing persisted.
- Poison message reaches DLQ after 5 retries.
- Replay CLI tool re-publishes events from `webhook_events`.

**Dependencies**: P1 complete (gateway app exists, Mongo connected)

**Parallelizable**: P2.3 (AMQP topology) can start in parallel with P2.1–P2.2.

**Risks**:
- Meli's IP allowlist changes without notice; needs operational runbook.
- RabbitMQ topology changes in prod require coordination across modules.

---

### Checklist

- [x] **P2.1** — [RED] Write failing tests for webhook receiver
  Tests: `test_valid_ip_webhook_returns_200_within_500ms`, `test_invalid_ip_returns_401`, `test_duplicate_notification_returns_200_no_publish`, `test_payload_persisted_to_webhook_events`.
  *Ref*: spec §3 R3.1–R3.2. *TDD*: all FAIL. *Effort*: S

- [x] **P2.2** — Implement `POST /webhooks/meli` receiver
  `gateway/src/zeler_gateway/webhooks/router.py`: parse source IP → check against `MELI_ALLOWED_IPS` env list (infra config) → 401 if not matched (log IP) → idempotent upsert `webhook_events` using payload `_id` as Mongo `_id` (`updateOne({_id}, $setOnInsert, upsert=true)`, if matched → 200 early return, no publish) → respond 200 immediately after upsert (before classify/publish to meet 500ms SLA) → fire-and-forget classify+publish task.
  *Ref*: design §6.1, spec §3 R3.1–R3.2. *TDD*: P2.1 tests now GREEN. *Effort*: M

- [x] **P2.3** — Create `webhook_events` collection + Atlas validator + TTL/indexes
  `infra/atlas/webhook_events.json`: $jsonSchema (design §4.9). TTL index `{received_at:1}` 45 days. Indexes `{topic:1, received_at:-1}`, `{user_id:1, received_at:-1}`. Apply to dev cluster.
  *Ref*: design §4.9. *TDD*: Validator rejects doc missing `topic`. *Effort*: S

- [x] **P2.4** — Declare RabbitMQ exchange + queue topology
  `infra/rabbitmq/definitions.json`: topic exchange `meli.events` (durable). Per-module queues: `zeler.<module>.<domain>` with DLX → `zeler.<module>.<domain>.dlq`. Intermediate delay queues for exponential backoff (1s, 5s, 30s, 2m, 10m). Apply via `rabbitmqadmin import`.
  *Ref*: design §6.3–§6.4, spec §3 R3.3–R3.5. *TDD*: Exchange + queues exist after apply (rabbitmqctl list_exchanges/queues assertion in CI). *Effort*: M

- [x] **P2.5** — Implement webhook classifier + AMQP publisher
  `gateway/src/zeler_gateway/webhooks/classifier.py`: `topic_to_routing_key` mapping (design §6.2). Build envelope JSON (event_id, event_type, occurred_at, seller_id, resource, trace_id — NO full Meli body). Publish via `aio-pika` to `meli.events` with routing key and `idempotency_key` header (derived from `(topic, resource, meli_notification_id)`).
  *Ref*: design §6.2, spec §3 R3.3–R3.4. *TDD*: `test_items_topic_classifies_to_items_updated`, `test_orders_v2_classifies_correctly`, `test_idempotency_key_stable_for_same_notification`. *Effort*: M

- [x] **P2.6** — Implement consumer idempotency de-duplication in core library
  `core/src/zeler_platform_core/events/idempotency.py`: `IdempotencyStore` backed by Mongo `processed_events` collection (TTL 48h). `is_duplicate(idempotency_key) → bool`, `mark_processed(idempotency_key)`. Modules import this from core.
  *Ref*: spec §3 R3.4. *TDD*: `test_first_key_not_duplicate`, `test_second_key_is_duplicate`, `test_expired_key_not_duplicate`. *Effort*: S

- [x] **P2.7** — Implement DLQ alert + monitoring hook
  `infra/rabbitmq/dlq_monitor.py`: script that polls DLQ depth via RabbitMQ management API; emits structured log alert + Prometheus gauge when depth > 100. Wire to Cloud Run Job on 5-min schedule (or GCE cron).
  *Ref*: design §6.4, spec §3 R3.5. *TDD*: `test_alert_emitted_when_dlq_depth_exceeds_threshold`. *Effort*: S

- [x] **P2.8** — Implement event replay CLI tool
  `gateway/src/zeler_gateway/cli/replay.py` (Click CLI): `python -m zeler_gateway.cli.replay --seller-id <id> --topic <topic> --since <ISO date>`. Queries `webhook_events`, re-publishes each matching doc to `meli.events` with same routing key + `replay=true` header.
  *Ref*: spec §3 (implied by R3.4 design). *TDD*: `test_replay_queries_and_republishes`, `test_replay_respects_seller_filter`. *Effort*: S

---

### Phase 2 — Archive Markers

**Archive type**: Phase milestone (change remains open for Phase 3+)
**Archive date**: 2026-04-24
**Final HEAD SHA**: `4ddc7a74c006322c72f8970979effe09e9f26d25`
**Commit**: `feat(gateway): add webhook event bus`
**Test count**: 104 passed / 0 failed / 0 skipped
**Quality gates**: `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅
**Verify report reference**: Engram #2258 (PASS WITH WARNINGS, CRITICAL=0, WARNING=5, SUGGESTION=4)
**Tasks completed**: P2.1–P2.8 (8/8)
**Canonical exchange**: `meli.events` (older prefixed exchange-name references reconciled in Phase 2 archive)
**Carry-forward warnings**: live RabbitMQ topology not applied during verify; publish-failure recovery is manual; P2.7 task text names a monitor script but implementation verified routing/config/runbook alert policy; optional HMAC lacks direct behavioral test.
**Tasks deferred**: none for P2; historical P1.17 deferral was resolved later by commit `8d5f3cd` and the P1.17 archive/reconciliation marker.

---

## Phase 3: Core Models + Repositories + Bootstrap

**Goal**: All canonical Pydantic v2 models, JSON Schema export, read-only repo library, bootstrap state machine + runner.

**Exit criteria**:
- All 12 canonical entities have Pydantic v2 models with validators.
- `python -m zeler_platform_core.cli.export_schemas` generates `infra/atlas/*.json` (full, not stub).
- `ItemsRepo(mongo_client).by_seller(seller_id)` returns typed list.
- Bootstrap job runs end-to-end on a test seller (empty cluster → all stages complete, all docs upserted idempotently, `BootstrapCompleted` event emitted).
- Crash + resume test: job interrupted mid-items, resumed, continues from cursor.

**Dependencies**: P0, P1 (gateway proxy needed by bootstrap runner), P2 (AMQP needed for BootstrapCompleted event)

**Parallelizable**: P3.1–P3.3 (models) can be done in parallel with P3.4–P3.5 (repos); bootstrap (P3.6+) is sequential after both.

**Risks**:
- Bootstrap API cost per large seller — mitigate with test seller account.
- Schema export must stay in sync with Pydantic models; automate in CI.

---

### Checklist

- [x] **P3.1** — [RED] Write failing model tests for all canonical entities
  Tests for each model: valid construction, invalid enum rejected, naive datetime rejected, meli_id numeric coerced to string. Cover: `MeliAccount`, `User`, `Item`, `Order`, `Question`, `Message`, `Shipment`, `Claim`, `Event`, `BootstrapJob`, `ModuleRegistry`, `WebhookEvent`.
  *Ref*: spec §4 R4.1–R4.4. *TDD*: all FAIL. *Effort*: M

- [x] **P3.2** — Implement Pydantic v2 canonical models
  `core/src/zeler_platform_core/models/`: one file per entity. Each model: `schema_version: int = 1`, UTC datetime validators (`model_validator` that checks `tzinfo is not None`), `meli_id` fields coerced to `str` via `field_validator`. Status fields as `Literal` or `StrEnum`. Reexport all from `core.models.__init__`.
  *Ref*: design §4, spec §4 R4.1–R4.4. *TDD*: P3.1 tests now GREEN. *Effort*: L

- [x] **P3.3** — Implement JSON Schema export + CI integration
  `core/src/zeler_platform_core/cli/export_schemas.py`: for each model, `model.model_json_schema()` → write to `infra/atlas/<collection>.json`. Add `$jsonSchema` wrapper with `validationLevel: "strict"`, `validationAction: "error"`. Wire to CI: schema export runs, output compared to committed files (diff fails build if models changed but schemas not regenerated).
  *Ref*: spec §4 R4.2, design §8 D8. *TDD*: Schema for `MeliAccount` rejects raw insert missing `seller_id` via Atlas validator. *Effort*: M

- [x] **P3.4** — Implement event contracts (domain event models)
  `core/src/zeler_platform_core/events/contracts.py`: Pydantic v2 models for `ItemUpdated`, `ItemPriceChanged`, `OrderCreated`, `QuestionReceived`, `MessageReceived`, `MeliAccountRevoked`, `MeliAccountReconnected`, `BootstrapCompleted`. Each carries `event_id: UUID`, `account_id`, `occurred_at: datetime`, `schema_version: int`.
  *Ref*: spec §4 R4.5. *TDD*: `test_event_serializes_deserializes_stably` (producer/consumer roundtrip via model_dump/model_validate). *Effort*: S

- [x] **P3.5** — Implement Core read-only repository library
  `core/src/zeler_platform_core/repos/`: `ItemsRepo`, `OrdersRepo`, `QuestionsRepo`, `MessagesRepo`, `ShipmentsRepo`, `ClaimsRepo`. Each: `by_seller(seller_id, **filters) → list[Model]`, typed return. Mongo client injected. `seller_id` filter ALWAYS applied (never exposes raw collection). No write methods exported from core repos.
  *Ref*: design §8.3, spec §5 R5.4. *TDD*: `test_items_repo_by_seller_applies_seller_filter`, `test_items_repo_no_write_methods_exported`. *Effort*: M

- [x] **P3.6** — Create `bootstrap_jobs` collection + Atlas validator + indexes
  `infra/atlas/bootstrap_jobs.json`: full $jsonSchema (design §4.10). Indexes `{seller_id:1, state:1}`, `{state:1, started_at:-1}`. Apply to dev.
  *Ref*: design §4.10, spec §7 R7.1. *TDD*: Validator rejects doc missing `state`. *Effort*: XS

- [x] **P3.7** — [RED] Write failing bootstrap state machine tests
  Tests: `test_pending_to_running_transition`, `test_running_to_succeeded`, `test_invalid_state_transition_rejected`, `test_pause_mid_stage_records_cursor`, `test_resume_continues_from_cursor`, `test_completed_stage_not_re-run`.
  *Ref*: spec §7 R7.1–R7.4. *TDD*: all FAIL. *Effort*: S

- [x] **P3.8** — Implement `bootstrap_jobs` state machine
  `bootstrap/src/zeler_bootstrap/state_machine.py`: `BootstrapStateMachine(job_id)` with `transition(new_state)` (atomic `findOneAndUpdate` with allowed-transition guard), `update_cursor(stage, cursor_data)`, `mark_stage_done(stage)`. Forbidden transitions raise `InvalidTransitionError`.
  *Ref*: spec §7 R7.1. *TDD*: P3.7 state machine tests now GREEN. *Effort*: M

- [x] **P3.9** — [RED] Write failing bootstrap runner tests (integration)
  Tests against test seller + mock gateway proxy: `test_accounts_stage_fetches_metadata`, `test_items_stage_paginates_and_upserts`, `test_orders_stage_respects_90_day_window`, `test_crash_mid_items_resume_from_cursor`, `test_resync_produces_no_duplicates`, `test_bootstrap_completed_event_emitted`.
  *Ref*: spec §7 R7.2–R7.5. *TDD*: all FAIL. *Effort*: M

- [x] **P3.10** — Implement bootstrap runner — accounts + items stages
  `bootstrap/src/zeler_bootstrap/runner.py` + `stages/accounts.py`, `stages/items.py`. DAG runner reads `bootstrap_jobs.dag` and `checkpoints`. Accounts stage: `GET /users/{seller_id}` via gateway proxy. Items stage: paginated `GET /users/{seller_id}/items/search` + `/items/{ids}:multiget` via gateway proxy; upsert `Item` models; persist `scroll_id` cursor after each page. Backpressure on 429 (Retry-After).
  *Ref*: design §7, spec §7 R7.2–R7.4. *TDD*: P3.9 accounts + items tests GREEN. *Effort*: L

- [x] **P3.11** — Implement bootstrap runner — orders, questions, messages, shipments, claims stages
  `stages/orders.py`, `stages/questions.py`, `stages/messages.py`, `stages/shipments.py`, `stages/claims.py`. Orders: date-bounded last 90 days, paginated, upsert `Order`. Questions: open first (all), then closed (last 30 days). Messages: per pack_id from orders. Shipments: from `shipment_id` in each order. Claims: from `order_id`. All upsert by canonical Meli id.
  *Ref*: design §7.1, spec §7 R7.2–R7.3. *TDD*: P3.9 remaining stage tests GREEN. *Effort*: L

- [x] **P3.12** — Implement Cloud Run Job entrypoint + deploy config
  `bootstrap/src/zeler_bootstrap/__main__.py`: CLI accepting `--seller-id` + `--job-id`. Dockerfile for bootstrap. `infra/terraform/cloudrun_jobs.tf`: Cloud Run Job definition with VPC connector, Secret Manager env injection, `max-retries=3`. On completion: emit `BootstrapCompleted` event.
  *Ref*: design §7, spec §7 R7.5. *TDD*: P3.9 `test_bootstrap_completed_event_emitted` GREEN. *Effort*: M

- [x] **P3.13** — Apply all canonical collection validators (P3.2 schemas) to Atlas
  Run `infra/atlas/apply_validators.py` with the generated full schemas from P3.3 for `items`, `orders`, `questions`, `messages`, `shipments`, `claims`, `webhook_events`, `bootstrap_jobs`. Verify strict rejection of invalid docs.
  *Ref*: design §10, spec §4 R4.2. *TDD*: Atlas rejects raw `insertOne` missing required field for each collection. *Effort*: S

---

### Phase 3 — Archive Markers

**Archive type**: Phase milestone (change remains open for Phase 4+)
**Archive date**: 2026-04-24
**Final HEAD SHA**: `b9d121c5df3a968a6f985862bddfa4c8d8f69aa7`
**Commits**: `e0c3127` (`feat(core): add phase 3 platform foundation`) · `f94e69a` (`docs(sdd): add phase 3 verification report`) · `b9d121c` (`feat(core): complete phase 3 platform bootstrap`)
**Test count**: 152 passed / 0 failed / 0 skipped
**Quality gates**: `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · schema export drift check ✅
**Verify report reference**: Engram #2281 (PASS WITH WARNINGS, CRITICAL=0, WARNING=5, SUGGESTION=4)
**Tasks completed**: P3.1–P3.13 (13/13)
**Carry-forward warnings**: manual schema registry may drift from Pydantic models; production Cloud Run bootstrap needs real runtime client construction; Gateway 429/Retry-After backpressure is not directly tested in bootstrap stages; progress semantics are checkpoint/cursor oriented, not explicit `stage_progress`; live/prod validator application remains an ops deployment step.
**Tasks deferred**: none for P3; historical P1.17 deferral was resolved later by commit `8d5f3cd` and the P1.17 archive/reconciliation marker.

---

## Phase 4: Module Runtime + Repricer

**Goal**: Module lifecycle conventions, manifest validation, ownership enforcement, CI AST linter. Repricer as the reference module — fully working against new stack.

**Exit criteria**:
- A module with invalid manifest fails to start with clear error.
- Gateway rejects proxy call from unregistered module.
- Repricer subscribes to `items.*` and `items.price_updated`, evaluates rules, calls gateway proxy, writes history.
- E2E test: webhook → AMQP → repricer → gateway proxy → mock Meli.
- CI AST check rejects any module file containing `api.mercadolibre.com`.

**Dependencies**: P1 (gateway proxy), P2 (AMQP topology), P3 (core repos + models)

**Parallelizable**: P4.4–P4.9 (repricer) can be done in parallel after P4.1–P4.3 (runtime) are done.

**Risks**:
- AST linter must cover all module packages but not gateway (gateway IS the one that calls Meli).
- High-throughput escape hatch (`/internal/tokens/issue`) has nuanced security posture — document clearly.

---

### Checklist

- [x] **P4.1** — Implement module manifest spec + validation
  `core/src/zeler_platform_core/runtime/manifest.py`: `ModuleManifest` Pydantic v2 model (name, version, subscribed_events: list[str], owned_collections: list[str], health_endpoint: str). `validate_manifest(path) → ModuleManifest` (raises on missing fields). Load at module startup.
  *Ref*: spec §5 R5.1, design §4.11. *TDD*: `test_valid_manifest_loads`, `test_missing_name_raises`, `test_manifest_rejects_gateway_owned_collection`. *Effort*: S

- [x] **P4.2** — Implement `module_registry` registration + `module_registry` collection
  `core/src/zeler_platform_core/runtime/registration.py`: `register_module(manifest, mongo_client)` — upsert `module_registry` doc (`_id=module_id`). `infra/atlas/module_registry.json`: validator + `{status:1}` index. On startup, module calls `register_module`; on collision with gateway-owned collection → raises `CollectionOwnershipError` and aborts startup.
  *Ref*: spec §5 R5.1, design §4.11. *TDD*: `test_registration_upserts_doc`, `test_gateway_owned_collection_raises`. *Effort*: S

- [x] **P4.3** — Implement module health endpoint base
  `core/src/zeler_platform_core/runtime/health.py`: `build_health_router(module_id, checks: list[HealthCheck])`. Returns FastAPI router with `GET /health` that runs each check (RabbitMQ consumer alive, DB reachable, last event timestamp within threshold). Response: `{ready: bool, checks: {name: {ok, detail}}}`.
  *Ref*: spec §5 R5.3. *TDD*: `test_all_checks_pass_returns_ready_true`, `test_consumer_stalled_returns_ready_false`. *Effort*: S

- [x] **P4.4** — Implement AST linter: forbid direct Meli calls in module packages
  `infra/lint/check_direct_meli.py`: AST walker that finds string literals or URL constants containing `api.mercadolibre.com` or `auth.mercadolibre.com` in any Python file under `modules/`. Wire as a separate CI job (runs after ruff, before tests). Fails build with file+line reference.
  *Ref*: spec §6 R6.3. *TDD*: `test_linter_flags_mercadolibre_url`, `test_linter_passes_on_clean_module`. *Effort*: S

- [x] **P4.5** — Implement `/internal/tokens/issue` endpoint (high-throughput escape hatch)
  `gateway/src/zeler_gateway/internal/router.py`: `POST /internal/tokens/issue {seller_id, scopes: list[str], ttl_s: int ≤ 300}`. Authenticated by valid internal module JWT. Decrypts access_token → returns plaintext for short-lived window. Writes one `audit_log` doc (issuance event). Documents scope narrowness + TTL in `CONTRIBUTING.md`.
  *Ref*: design §5.4 (escape hatch). *TDD*: `test_issue_returns_token`, `test_issue_requires_valid_jwt`, `test_issue_scope_narrowed_to_allowed_scopes`. *Effort*: M

- [x] **P4.6** — Create `repricer_rules` + `repricer_history` collections + Atlas validators
  `infra/atlas/repricer_rules.json`, `infra/atlas/repricer_history.json`. Rules indexes: `{seller_id:1, active:1}`, `{item_id:1}` unique partial (active). History indexes: `{item_id:1, applied_at:-1}`, `{seller_id:1, applied_at:-1}`. TTL on history `{applied_at:1}` 365 days. Apply to dev.
  *Ref*: design §4.12. *TDD*: Validators reject docs missing required fields. *Effort*: S

- [x] **P4.7** — [RED] Write failing rules engine tests
  Tests (pure, no I/O): `test_track_buybox_sets_price_to_buybox_bounded_by_ceiling`, `test_below_floor_returns_no_action`, `test_maximize_returns_ceiling`, `test_min_price_returns_floor_when_below`, `test_engine_is_deterministic`.
  *Ref*: spec §6 R6.2 scenarios. *TDD*: all FAIL. *Effort*: S

- [x] **P4.8** — Implement repricer rules engine (pure, no I/O)
  `modules/repricer/src/zeler_repricer/engine.py`: `evaluate_rule(rule: RepricerRule, current_price: Decimal, buybox_price: Decimal | None) → Decision`. `Decision` = `SetPrice(new_price)` or `NoAction(reason)`. Fully pure — no DB, no HTTP. Strategies: `min_price`, `competitive` (track_buybox), `maximize`.
  *Ref*: spec §6 R6.2. *TDD*: P4.7 tests now GREEN. *Effort*: M

- [x] **P4.9** — Implement repricer AMQP consumer + event handler
  `modules/repricer/src/zeler_repricer/consumer.py`: `aio-pika` consumer binding to `zeler.repricer.items` queue. Routing keys: `items.*`, `items.price_updated`. Handler: check idempotency → load item from `ItemsRepo` → load rules for item from `repricer_rules` → run engine → on `SetPrice`: call gateway proxy `PUT /proxy/meli/items/{item_id}` → write `repricer_history` doc. Ack after successful write.
  *Ref*: spec §6 R6.1–R6.4. *TDD*: `test_price_changed_event_triggers_rule_eval`, `test_idempotent_event_skipped`, `test_set_price_calls_gateway_proxy`, `test_history_written_for_every_decision`. *Effort*: L

- [x] **P4.10** — Implement repricer FastAPI admin API
  `modules/repricer/src/zeler_repricer/api.py`: `GET /repricer/rules?seller_id=`, `POST /repricer/rules`, `PATCH /repricer/rules/{id}`, `DELETE /repricer/rules/{id}`. Internal JWT auth. `POST` validates rule fields via `RepricerRule` Pydantic model, upserts with unique partial index check.
  *Ref*: spec §6 R6.4. *TDD*: `test_create_rule_returns_201`, `test_below_floor_validation_error`, `test_only_module_jwt_accepted`. *Effort*: M

- [x] **P4.11** — Repricer manifest + registration + health
  `modules/repricer/manifest.yaml`: name=repricer, version=0.1.0, subscribed_events=[items.*, items.price_updated], owned_collections=[repricer_rules, repricer_history], health_endpoint=/health. Wire `register_module(manifest)` on startup and `build_health_router` with RabbitMQ + Mongo checks.
  *Ref*: spec §5 R5.1–R5.3. *TDD*: Startup registers doc in `module_registry`; health returns ready=true. *Effort*: S

- [x] **P4.12** — [RED + GREEN] E2E test: webhook → AMQP → repricer → gateway proxy → mock Meli
  `tests/e2e/test_repricer_flow.py`: POST to `/webhooks/meli` with `items_prices` topic emitted as `items.price_updated` → verify AMQP message in repricer queue → repricer handler fires → verify gateway proxy called (mock Meli) → verify `repricer_history` doc written. Runs against local Docker Compose (gateway + repricer + RabbitMQ + mongo). Must be GREEN.
  *Ref*: spec §6 R6.1–R6.4, design §8.1. *TDD*: Write test (RED), implement glue (GREEN). *Effort*: L

---

### Phase 4 — Archive Markers

**Archive type**: Phase milestone (change remains open for Phase 5+)
**Archive date**: 2026-04-24
**Final HEAD SHA**: `f0f256c15a1b1ed03c56e7fbcc1c6e58852caaec`
**Commits**: `38e8c90` (`feat(core): add module runtime foundation`) · `f0f256c` (`feat(repricer): complete phase 4 runtime flow`)
**Test count**: 180 passed / 0 failed / 0 skipped
**Quality gates**: `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · `uv run python -m infra.lint.check_direct_meli .` ✅
**Verify report reference**: Engram #2291 (PASS WITH WARNINGS, CRITICAL=0, WARNING=4, SUGGESTION=3)
**Tasks completed**: P4.1–P4.12 (12/12)
**Carry-forward warnings**: ~~no concrete repricer `aio-pika` consumer loop/binding yet~~ resolved by hardening commit adding `RepricerAmqpConsumerRunner` with fake-broker tests; P4.12 E2E is deterministic in-process rather than live Docker Compose RabbitMQ/Mongo; live Mongo validator/index application remains an ops release task.
**Tasks deferred**: none for P4; historical P1.17 deferral was resolved later by commit `8d5f3cd` and the P1.17 archive/reconciliation marker.

---

## Phase 5: zeler-app Integration

**Goal**: Wire existing Next.js 15 app to the new platform gateway for auth + data. Deprecate any legacy-wired screens.

**Exit criteria**:
- Seller can click "Connect MercadoLibre" in zeler-app, complete OAuth, see their account listed.
- Accounts management screen shows linked accounts + status.
- Bootstrap progress screen reads `bootstrap_jobs` (via gateway read API).
- Repricer rules screen uses repricer admin API.
- No screen still calls legacy endpoints.

**Dependencies**: P1 (OAuth + accounts API), P3 (bootstrap_jobs readable), P4 (repricer admin API)

**Parallelizable**: UI screens (P5.2–P5.5) can be built in parallel once auth (P5.1) is done.

**Risks**:
- zeler-app may have tightly coupled legacy API calls; audit needed before starting P5.

---

### Checklist

- [x] **P5.1** — Audit zeler-app for all legacy API call sites
  Grep for any calls to legacy domain names / endpoints. Produce a list of screens + API calls to migrate. Create migration checklist as a GitHub issue. No code yet.
  *Result*: Audit completed against `/Users/eduardoramirez/Documents/repositorios/zeler-app`; migration checklist issue created: https://github.com/eduardoemb/zeler-app/issues/1. App implementation work is blocked until the pre-existing app lint/test-runner gap is resolved.
  *Baseline update 2026-04-24*: zeler-app lint/test-runner blocker resolved on `staging`; `npm run lint` and `npm test` are green. P5.2-P5.6 remain incomplete and should now proceed strict-TDD.
  *Ref*: proposal §4. *TDD*: N/A (discovery). *Effort*: S

- [x] **P5.2** — Implement platform auth flow in zeler-app
  Add "Connect MercadoLibre" button → `GET /oauth/authorize?platform_user_id=<id>`. Handle callback redirect → show success toast. Store platform session (JWT cookie or server session). Auth provider: gateway `/internal/tokens/issue` (platform user context, not Meli token — gate behind platform user login).
  *Result*: zeler-app dashboard now renders a Connect MercadoLibre CTA backed by `ZELER_GATEWAY_URL` / `NEXT_PUBLIC_ZELER_GATEWAY_URL`, uses the NextAuth session user id as `platform_user_id`, and adds `/accounts/linked` success/error callback messaging. Existing gateway `/oauth/authorize` and `/internal/tokens/issue` contracts are used. Follow-up verify #2307 added minimal Playwright runner coverage for the OAuth CTA/authorize route contract.
  *Ref*: design §5.1. *TDD*: Playwright E2E: button → mock OAuth → success redirect. *Effort*: M

- [x] **P5.3** — Accounts management screen
  zeler-app page `/accounts`: list linked Meli accounts (status, nickname, connected_at, last_refreshed_at). Call gateway `GET /api/accounts?user_id=<id>`. Add gateway `GET /api/accounts` endpoint returning account list (read-only, no tokens). Show status badge (active/revoked/error). "Re-link" CTA for revoked.
  *Result*: Added gateway read-only `GET /api/accounts` with token-field projection and zeler-app `/accounts` page with account list, empty state, status badges, and revoked re-link CTA. Tests cover URL contracts, no-token API projection, status rendering, and empty state.
  *Ref*: spec §2, design §5.1. *TDD*: Component test: shows account list, shows revoked badge. *Effort*: M

- [x] **P5.4** — Bootstrap progress screen
  zeler-app page `/bootstrap/:jobId`: poll `GET /api/bootstrap-jobs/:jobId` every 5s. Show per-stage progress bar (stage_progress). Show current_stage, state, errors[]. Add gateway `GET /api/bootstrap-jobs/:jobId` endpoint (read from `bootstrap_jobs` collection, no sensitive data). On `BootstrapCompleted`: show success + redirect to dashboard.
  *Result*: Added gateway read-only `GET /api/bootstrap-jobs/{job_id}` with `checkpoints` projection, 404 contract, datetime serialization, and zeler-app `/bootstrap/[jobId]` progress page with 5-second refresh, per-stage progress bars, errors, and dashboard return CTA on success.
  *Ref*: spec §7 R7.5. *TDD*: Component test: shows progress per stage, updates on poll. *Effort*: M

- [x] **P5.5** — Repricer rules screen
  zeler-app page `/repricer/rules`: list rules (call repricer `GET /repricer/rules?seller_id=`), create/edit/delete via repricer API. Show last repricer_history entries per item. Wire through gateway internal JWT (zeler-app requests JWTs from gateway on behalf of user session).
  *Result*: Added zeler-app `/repricer/rules` page, API contract helpers for rules/create/update/delete/history, server actions wired to form submissions, edit and deactivate controls, mutation error representation, and recent history. Repricer module already exposes `POST /repricer/rules`, `PATCH /repricer/rules/{rule_id}`, `DELETE /repricer/rules/{rule_id}`, and `GET /repricer/history?seller_id=` admin endpoints. Current server wiring uses `REPRICER_API_URL` + `REPRICER_API_TOKEN` while the gateway user-session token exchange remains a follow-up hardening item.
  *Ref*: spec §6 R6.4. *TDD*: Component test: renders rules list, create rule submits POST. *Effort*: M

- [x] **P5.6** — Remove / deprecate legacy-wired screens
  From audit in P5.1: for each legacy endpoint call, either wire to new platform API or remove the screen. Add deprecation notice to removed screens. Ensure no 5xx from removed endpoints in staging.
  *Result*: Removed legacy product-domain links from the module catalog; EasyReprice routes to `/repricer/rules`, while SheetSeller/FullDock/AutoReply/Publicador route to in-app deprecation notices until their P6 platform modules exist. Added unit tests and minimal Playwright coverage that guard against legacy product-domain URLs and external-link affordances on internal modules.
  *Ref*: proposal §4. *TDD*: Playwright smoke: all screens load without 5xx. *Effort*: M

---

### Phase 5 — Archive Markers

**Archive type**: Phase milestone (change remains open for Phase 6+; historical P1.17 deferral resolved later by commit `8d5f3cd`)
**Archive date**: 2026-04-24
**Final zeler-platform HEAD SHA**: `3d968bf324fcb222831ee7a5a55ffce683713fee`
**Final zeler-app HEAD SHA**: `d9a841e786a306357f69e31ba947176428fbbc00`
**Platform commits**: `915fa35` (`docs(sdd): complete phase 5 app audit`) · `71d0d79` (`docs(sdd): record zeler-app baseline unblock`) · `7c3cb24` (`feat(gateway): add accounts read endpoint`) · `7849c1e` (`feat(platform): add bootstrap and repricer read screens support`) · `3d968bf` (`docs(sdd): record phase 5 verify fixes`)
**App commits**: `82e7eb8` (`test: add app test harness`) · `ad104ef` (`feat(accounts): add platform MercadoLibre account flow`) · `4a0f6cb` (`feat(app): add bootstrap and repricer platform screens`) · `d9a841e` (`fix(repricer): wire rule mutations`)
**Test count**: zeler-platform `184 passed` · zeler-app `19 passed` · zeler-app e2e runner `2 passed`
**Quality gates**: zeler-platform `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · zeler-app `npm test` ✅ · `npm run lint` ✅ · `npm run e2e` ✅
**Verify report reference**: Engram #2312 (PASS WITH WARNINGS, CRITICAL=0, WARNING=2, SUGGESTION=2)
**Tasks completed**: P5.1–P5.6 (6/6)
**Carry-forward warnings**: Playwright coverage is static/browser-free contract coverage, not true browser E2E; ~~repricer mutations use `REPRICER_API_URL` + `REPRICER_API_TOKEN`, not gateway user-session token exchange~~ resolved by hardening marker below; live RabbitMQ/Mongo validation and repricer routing-key follow-up remain.
**Tasks deferred**: none for P5; historical P1.17 deferral was resolved later by commit `8d5f3cd` and the P1.17 archive/reconciliation marker.

#### Phase 5 hardening marker — Repricer admin token exchange

**Archive type**: Phase 5 hardening follow-up
**Archive date**: 2026-04-24
**Result**: Replaced zeler-app repricer mutation dependence on `REPRICER_API_TOKEN` with a server-side `getPlatformAdminToken()` abstraction that exchanges a gateway credential through `/internal/tokens/issue` for a short-lived `module_admin` JWT scoped as `admin:repricer`. Gateway token issuance now supports the `module_admin` token kind while preserving the existing `meli_access` behavior for high-throughput Meli-token escape hatch callers.
**TDD evidence**: Added focused RED-first platform tests for `module_admin` issuance/validation and app tests proving no `REPRICER_API_TOKEN` fallback.
**Design note**: This remains a safe abstraction until real zeler-app session auth is bound to the exchange; the public/static repricer token is no longer required by mutations.

#### Phase 5 hardening marker — zeler-app admin client seed

**Archive type**: Deployment contract hardening follow-up
**Archive date**: 2026-04-24
**Result**: Added deterministic local module-registry seed `infra/mongo/seeds/module_registry.admin_clients.json` containing admin client `zeler-app` with only `admin:repricer` in `allowed_meli_scopes`, so live/bootstrap operators have a concrete registry fixture for `/internal/tokens/issue` `module_admin` exchanges.
**TDD evidence**: Added RED-first gateway contract tests proving the seed exists, allows `zeler-app` to request a repricer admin token, and rejects a non-repricer admin scope via the existing `out_of_scope` path.

---

## Phase 6: Remaining Modules

**Goal**: Implement Sheets, Publicador, Autoreply, FullDock as platform modules. Can be built in parallel by different team members.

**Exit criteria per module**:
- Valid manifest registered in `module_registry`.
- Event subscriptions wired and consuming correctly.
- Outbound calls via gateway proxy only (AST linter passes).
- Module-owned collections with Atlas validators.
- Health endpoint returns ready.
- Playwright or integration test for primary workflow.

**Dependencies**: P4 (module runtime + repricer as reference)

**Parallelizable**: All 4 modules fully parallel.

**Risks**:
- Publicador uses LLM/Perplexity — external API dependency; mock in tests.
- Autoreply has answer templates (port the LOGIC not the data — design §9 D9 — no migration).
- FullDock stock location calls require `PUT /items/*/stock_locations` scope; verify Meli grant.

---

### Per-Module Checklist

#### 6A: sheets-module (ex-SheetSeller)

- [x] **P6A.1** — Define sheets manifest + owned collections (`sheets_exports`, `sheets_sync_jobs`)
  *Events subscribed*: `items.*`, `orders.*`, `shipments.*`. *Scope*: read-only Meli (`GET /items/*`, `GET /orders/*`, `GET /shipments/*`).
  *Result*: Added `modules/sheets/manifest.yaml` with read-only gateway scopes, module-owned collections, startup registration, and `/health` readiness wiring.
  *TDD*: Manifest validates, no gateway-owned collections declared. *Effort*: S

- [x] **P6A.2** — Create `sheets_exports` + `sheets_sync_jobs` collections + validators
  *Result*: Added strict Mongo validators plus indexes for seller-enabled export lookup, spreadsheet lookup, and sync-job state listing.
  *TDD*: Validators reject missing required fields. *Effort*: S

- [x] **P6A.3** — Implement AMQP consumers for items/orders/shipments events
  Handler: receive event → fetch full resource via gateway proxy → format Google Sheets row → append to configured spreadsheet (Google Sheets API). Idempotent by event `event_id`.
  *Result*: Added deterministic `SheetsEventHandler` contract: de-dupes by idempotency key, loads seller export config, fetches the full resource through an injected gateway client, formats a row, and appends through an injected Google Sheets client. Real Google Sheets credentials/API and live AMQP loop remain deployment wiring for later validation; tests use mocks/contracts only.
  *TDD*: `test_item_event_triggers_sheets_append`, `test_duplicate_event_skipped`. *Effort*: L

- [x] **P6A.4** — Admin API + zeler-app screen for sheets configuration
  Configure spreadsheet ID per seller. Trigger manual sync. View last sync status.
  *Result*: Added Sheets module admin API for listing/upserting export configuration, creating manual sync jobs, and surfacing last sync state; added zeler-app SheetSeller configuration route with API helpers, server actions, form, sync trigger, and module catalog route.
  *TDD*: Component test: configure form submits, sync job created. *Effort*: M

##### 6A — Archive Marker

**Archive type**: Phase 6 subphase milestone (change remains open for Phase 6B–6D and Phase 7)
**Archive date**: 2026-04-24
**Verified HEADs**: zeler-platform `7a0ed4f85d649f2a7a3875e811a8fe34bc565a2f`; zeler-app `b64948149a4ea8ec6d4c8a613556a57a573cee25`
**Verify report reference**: Engram #2321 + `sdd/zeler-platform-greenfield/verify-report-phase-6a-sheets.md` (`PASS_WITH_WARNINGS`, CRITICAL=0)
**Tasks completed**: P6A.1–P6A.4 (4/4)
**Warnings carried forward**:
- Live Google Sheets credentials/API append execution was not locally verified; validate with sandbox spreadsheet/credentials during deployment or integration.
- Live AMQP worker/consumer loop was not locally executed; manifest subscriptions and deterministic handler contract were verified only through local tests.
- P6A.3 covers item append and duplicate skip; add explicit order/shipment event variant coverage when expanding integration/triangulation.

#### 6B: publicador-module (ex-PublicadorMeli)

- [x] **P6B.1** — Define publicador manifest + owned collections (`publicador_drafts`, `publicador_history`)
  *Events subscribed*: none (user-triggered). *Scope*: `POST /items`, `PUT /items/*`, `GET /categories/*`, `POST /items/validate`.
  *Result*: Added `modules/publicador/manifest.yaml` with empty user-triggered subscriptions, gateway write/validation/category scopes, owned collections, startup registration, and `/health` readiness wiring. Runtime manifests now allow empty `subscribed_events` for modules that do not consume AMQP.
  *TDD*: Manifest validates. *Effort*: S

- [x] **P6B.2** — Create `publicador_drafts` + `publicador_history` collections + validators
  *Result*: Added strict Mongo validators and indexes for seller/status draft listing and seller/draft history lookup.
  *TDD*: Validators strict. *Effort*: S

- [x] **P6B.3** — Implement LLM/Perplexity listing generation
  Port the LLM generation pattern from legacy PublicadorMeli. Input: product info. Output: title + description + attributes. Use env-injected API key from Secret Manager. No direct Meli calls (AST linter enforces).
  *Result*: Added deterministic `ListingGenerator` behind an injected LLM protocol. Tests mock the LLM response and validate generated listing shape; no real LLM/Perplexity call is made.
  *TDD*: `test_generates_listing_from_product_info` (mock LLM API). *Effort*: M

- [x] **P6B.4** — Implement listing publish flow via gateway proxy
  Draft saved → validated → `POST /proxy/meli/items` via gateway. Result persisted in `publicador_history`.
  *Result*: Added `PublicadorPublisher` that loads a draft, validates through the injected gateway client (`/items/validate`), publishes through the injected gateway client (`/items`), updates draft status, and records success/validation failure in `publicador_history`. Tests use a fake gateway client only; no Meli/RabbitMQ calls.
  *TDD*: `test_publish_calls_gateway_proxy`, `test_history_records_outcome`. *Effort*: M

- [x] **P6B.5** — Admin API + zeler-app screen for publicador
  Create draft, generate with LLM, preview, publish. View history.
  *Result*: Added Publicador admin API endpoints for listing drafts with history, creating drafts, generating LLM listings, and publishing via the gateway flow. Added zeler-app Publicador route `/publicador/drafts`, API helpers, server actions, and a create/generate/preview/publish/history panel; module catalog now routes Publicador in-app.
  *TDD*: Component test: create draft → LLM generate → publish button. *Effort*: M

##### 6B — Archive Marker

**Archive type**: Phase 6 subphase milestone (change remains open for Phase 6C–6D and Phase 7)
**Archive date**: 2026-04-24
**Verified HEADs**: zeler-platform `31248eda9e80b50365c590f7035a3be27c965d42`; zeler-app `25734613d090651d765746e75a8812ebc48610be`
**Verify report reference**: Engram #2329 + `sdd/zeler-platform-greenfield/verify-report-phase-6b-publicador` (`PASS_WITH_WARNINGS`, CRITICAL=0)
**Tasks completed**: P6B.1–P6B.5 (5/5)
**Warnings carried forward**:
- Live LLM/Perplexity, live Meli publish, live Secret Manager API key injection, and live RabbitMQ were not locally exercised; validate them in deployment/integration environments.
- No Publicador-specific browser smoke was run; app coverage is unit/RSC/API-helper plus broader app smoke tests, not a browser-level create/generate/publish flow.

#### 6C: autoreply-module (ex-Autoreplyia)

- [x] **P6C.1** — Define autoreply manifest + owned collections (`autoreply_templates`, `autoreply_history`)
  *Events subscribed*: `questions.new`, `messages.new`. *Scope*: `POST /answers`, `GET /questions/*`, `GET /messages/*`.
  *Result*: Added `modules/autoreply/manifest.yaml` with question/message subscriptions, gateway answer/question/message scopes, owned collections, startup registration, and `/health` readiness wiring.
  *TDD*: Manifest validates. *Effort*: S

- [x] **P6C.2** — Create `autoreply_templates` + `autoreply_history` collections + validators
  No per-nickname collections (enforced by design). `seller_id` field on all docs.
  *Result*: Added strict Mongo validators and indexes, including unique `(seller_id, template_name)` and idempotent history by `idempotency_key`; schema inventory now treats Autoreply schemas as active non-placeholder validators.
  *TDD*: Validators strict, unique index on (seller_id, template_name). *Effort*: S

- [x] **P6C.3** — Implement question auto-reply consumer
  `questions.new` event → fetch question via gateway proxy `GET /questions/{id}` → match template → if match: `POST /answers` via gateway proxy → write `autoreply_history`. Idempotent by event `idempotency_key`.
  *Result*: Added deterministic `AutoreplyEventHandler` using injected gateway and idempotency contracts. It fetches questions/messages through the gateway, supports keyword/regex template matching, posts answers via the gateway only, records history, and suppresses duplicate events. Tests use fakes only; no live Meli/RabbitMQ calls.
  *TDD*: `test_matched_template_triggers_answer`, `test_no_match_skips`, `test_duplicate_event_skipped`. *Effort*: L

- [x] **P6C.4** — Template management API + zeler-app screen
  CRUD for templates per seller. Pattern matching (keyword or regex). Preview.
  *Result*: Added Autoreply admin API for listing/creating/updating/deleting templates and previewing match decisions; added zeler-app `/autoreply/templates` route, API helpers, server actions, template management panel, visible delete flow, preview form, and module catalog route. Follow-up verify gap fixed with explicit backend delete success/not-found/auth coverage plus app delete helper/action/button coverage.
  *TDD*: Component/helper tests: create, update, delete, preview; backend API delete behavior. *Effort*: M

##### 6C — Archive Marker

**Archive type**: Phase 6 subphase milestone (change remains open for Phase 6D and Phase 7)
**Archive date**: 2026-04-24
**Verified HEADs**: zeler-platform `9a9adb66a3c363acb2cdde5f2846e860ac8e9d18`; zeler-app `f9983f6a081c44199470e5cfaf2f50006a3e40c9`
**Verify report reference**: Engram #2342 + `sdd/zeler-platform-greenfield/verify-report-phase-6c-autoreply-final` (`PASS_WITH_WARNINGS`, CRITICAL=0)
**Tasks completed**: P6C.1–P6C.4 (4/4)
**Quality gates**: zeler-platform `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · `uv run python -m infra.lint.check_direct_meli .` ✅ · zeler-app `npm test` ✅ · `npm run lint` ✅ · `npm run e2e` ✅
**Warnings carried forward**:
- Live RabbitMQ consumer loop and live Meli question/message/answer calls were not locally exercised; verification used deterministic handler/API contract coverage with gateway fakes and the direct-Meli linter.
- No Autoreply-specific Playwright CRUD flow exists yet; app e2e remains broader P5 smoke coverage rather than browser-level Autoreply create/update/delete/preview coverage.
- Preview backend returns the match decision, but the zeler-app UI currently revalidates without displaying that match result.
- Invalid seller-authored regex handling still needs hardening before broad exposure.

#### 6D: fulldock-module (ex-FullDock)

- [x] **P6D.1** — Define fulldock manifest + owned collections (`fulldock_inventory_rules`, `fulldock_history`)
  *Events subscribed*: `items.*`, `shipments.*`. *Scope*: `GET /items/*`, `GET /shipments/*`, `PUT /items/*/stock_locations`.
  *Result*: Added `modules/fulldock/manifest.yaml`, module startup registration, `/health`, and scope contract coverage. Confirmed the stock-location grant is represented in design §8.2 and enforced in the manifest.
  *TDD*: Manifest validates. Confirm `PUT /items/*/stock_locations` in Meli grant before implementing P6D.3. *Effort*: S

- [x] **P6D.2** — Create `fulldock_inventory_rules` + `fulldock_history` collections + validators
  *Result*: Added strict Mongo validators and indexes for FullDock rules/history; included both files in canonical validator contracts and placeholder inventory tests.
  *TDD*: Validators strict. *Effort*: S

- [x] **P6D.3** — Implement stock location update consumer
  `items.*` + `shipments.*` events → evaluate inventory rules → update stock locations via gateway proxy `PUT /items/{id}/stock_locations`. Write `fulldock_history`.
  *Result*: Added deterministic `FulldockEventHandler` using injected gateway/idempotency fakes. It fetches item/shipment resources through the gateway, resolves item IDs, applies enabled seller/item rules, sends stock-location updates via gateway proxy only, writes history, and skips duplicate events.
  *TDD*: `test_shipment_triggers_stock_update`, `test_no_rule_skips_update`. *Effort*: L

- [x] **P6D.4** — Admin API + zeler-app screen
  Configure inventory rules per seller/item. View history.
  *Result*: Added Fulldock admin API for listing/creating/updating inventory rules with history context; added zeler-app `/fulldock/rules` route, API helpers, server actions, rule management panel, and module catalog routing.
  *TDD*: Component test: create rule, view history. *Effort*: M

##### 6D — Archive Marker

**Archive type**: Phase 6 subphase milestone (completes Phase 6; change remains open for Phase 7)
**Archive date**: 2026-04-24
**Verified HEADs**: zeler-platform `c3e4f17`; zeler-app `db5033d`
**Verify report reference**: Engram #2349 + `sdd/zeler-platform-greenfield/verify-report-phase-6d-fulldock` (`PASS_WITH_WARNINGS`, CRITICAL=0)
**Tasks completed**: P6D.1–P6D.4 (4/4)
**Quality gates**: zeler-platform `uv run pytest` ✅ · `uv run ruff check .` ✅ · `uv run ruff format --check .` ✅ · `uv run mypy .` ✅ · `uv run python -m infra.lint.check_direct_meli .` ✅ · zeler-app `npm test` ✅ · `npm run lint` ✅ · `npm run e2e` ✅
**Warnings carried forward**:
- `spec.md` has no explicit FullDock module requirement/scenario section; verification used P6D tasks plus global module/gateway/design rules.
- Live RabbitMQ consumer loop and live Meli `PUT /items/*/stock_locations` behavior were not locally executed; local verification used deterministic handler/API contracts and direct-Meli linting.
- zeler-app e2e remains broad platform smoke coverage, not a FullDock-specific CRUD browser flow.
- Sandbox/live validation of RabbitMQ + gateway proxy + Meli stock-location grant is required before production rollout.

##### Phase 6 — Completion Marker

**Archive type**: Phase milestone (Sheets, Publicador, Autoreply, and FullDock modules complete; change remains open for Phase 7)
**Archive date**: 2026-04-24
**Verified subphases**: P6A Sheets ✅ · P6B Publicador ✅ · P6C Autoreply ✅ · P6D FullDock ✅
**Tasks completed**: P6A.1–P6A.4, P6B.1–P6B.5, P6C.1–P6C.4, P6D.1–P6D.4 (17/17)
**Verify reports**: P6A Engram #2321 · P6B Engram #2329 · P6C Engram #2342 · P6D Engram #2349 — all `PASS_WITH_WARNINGS`, CRITICAL=0
**Phase 7 readiness**: Phase 6 parity prerequisite satisfied locally; proceed to legacy decommission planning/execution while carrying subphase live-environment warnings into sandbox/deployment validation.

---

## Cross-Phase Hardening: Live Readiness Validation

**Goal**: Give operators non-destructive tooling and a runbook to validate RabbitMQ topology plus Mongo validator/index readiness in sandbox/live environments before Phase 7 production decommission actions.

### Checklist

- [x] **H1** — Add RabbitMQ topology readiness CLI
  `infra/rabbitmq/readiness.py` validates `infra/rabbitmq/definitions.json` offline and can compare against a RabbitMQ management export JSON without importing definitions or mutating the broker. Output includes `safe_to_execute`, `read_only`, and `mutations_attempted`.
  *TDD*: `tests/test_live_readiness_validation.py::test_rabbitmq_readiness_*` RED → GREEN.

- [x] **H2** — Add Mongo schema/index readiness CLI
  `infra/mongo/readiness.py` validates local schema/index JSON offline and can optionally check a target `MONGO_URI` using read-only metadata calls only (`listCollections`, `listIndexes`). It never calls `collMod`, `createIndex`, `drop`, or import operations.
  *TDD*: `tests/test_live_readiness_validation.py::test_mongo_readiness_*` RED → GREEN.

- [x] **H3** — Add sandbox/live validation runbook
  `docs/live-readiness-validation.md` documents the sandbox sequence, optional env vars (`RabbitMQ_MANAGEMENT_EXPORT`, `MONGO_URI`), safety model, and explicitly forbids `apply_validators.py` / RabbitMQ import during readiness validation.
  *TDD*: `tests/test_live_readiness_validation.py::test_live_readiness_runbook_documents_sandbox_sequence_and_env_vars` RED → GREEN.

- [x] **H4** — Validate module registry admin-client seed readiness
  `infra/mongo/readiness.py` validates local `infra/mongo/seeds/module_registry.admin_clients.json` as a read-only JSON contract and can compare expected admin clients against a separately exported `module_registry` JSON file via `--module-registry-export`. `docs/live-readiness-validation.md` separates readiness validation from the explicit manual/deployment seed apply step.
  *TDD*: `tests/test_live_readiness_validation.py::test_mongo_readiness_validates_zeler_app_admin_seed_scope`, `test_mongo_readiness_reports_wrong_zeler_app_admin_seed_scope`, and `test_mongo_readiness_reports_missing_zeler_app_admin_seed_from_export` RED → GREEN.

- [x] **H5** — Add deployment preflight checklist/tooling
  `infra/deploy/preflight.py` checks gcloud project/account/access-token availability non-interactively, required env-var groups for Mongo/RabbitMQ/GCP/Cloud Run deploy readiness, and required repo files (Cloud Build config, Dockerfile, readiness tools, topology, schemas/indexes, seeds). Output renders only present/missing or sanitized status, never secret values, and exits non-zero while required prerequisites are missing.
  *TDD*: `tests/test_deployment_preflight.py` RED → GREEN for no-secret output, gcloud non-interactive behavior, repo-file remediation, and runbook command documentation.

---

## Phase 7: Legacy Decommission

**Goal**: Freeze legacy repos, archive zeler-core, drop legacy databases, revoke legacy OAuth apps, shut down legacy services.

**Exit criteria**:
- All 5 legacy repos are read-only on GitHub.
- `zeler-core` has a final commit with deprecation notice.
- Legacy databases deleted after 30-day recovery window.
- Legacy OAuth apps revoked in Meli developer portal.
- All legacy VMs + Cloud Run services stopped.
- Post-mortem doc committed to `zeler-platform/docs/`.

**Dependencies**: P4 (repricer parity), P5 (zeler-app migrated), P6 (all modules at parity — per module)

**Parallelizable**: Legacy DB drop (P7.4) must be last; everything else can parallelize.

**Risks**:
- Sellers who haven't re-linked lose access — need seller migration communication plan.
- Legacy VM billing continues until explicitly stopped; set a calendar reminder.

---

### Checklist

> **Phase 7 safety note (2026-04-24)**: Destructive operations are intentionally not automated.
> Added non-destructive planning artifacts in `docs/legacy-decommission-runbook.md`,
> `docs/migration-postmortem.md`, and `infra/decommission/*`, covered by
> `tests/test_decommission_audit.py`. P7.1-P7.5 remain unchecked until an operator gives
> explicit approval and executes each irreversible action with verified credentials/environment.
> P7.6 remains a draft until real execution evidence is recorded.

- [ ] **P7.1** — Freeze 5 legacy repos on GitHub
  Set each repo to read-only (archive) via GitHub settings. Add `README.md` deprecation notice at top: "This repo is archived. The capability is now part of [zeler-platform](link). Re-link your account at [URL]."
  *Ref*: proposal §3, §9. *TDD*: N/A. *Effort*: XS

- [ ] **P7.2** — Archive zeler-core repo
  Final commit: update `README.md` with deprecation notice + migration guide. Tag `v-final`. Archive via GitHub settings. Document which shadow-sync patterns are now canonical platform patterns.
  *Ref*: proposal §3. *TDD*: N/A. *Effort*: XS

- [ ] **P7.3** — Remove legacy Cloud Run services + VMs
  Terraform destroy for legacy Cloud Run services. Stop and delete legacy VMs (GCE). Confirm no traffic via Cloud Monitoring before deleting. Log decommission date in post-mortem.
  *Ref*: proposal §3. *TDD*: N/A (ops). *Effort*: S

- [ ] **P7.4** — Drop legacy databases (post 30-day recovery window)
  Schedule 30-day freeze from P7.1. After window: drop legacy Mongo databases (Atlas cluster `zeler-core`, per-product DBs). Take final Atlas snapshot before drop. Log in post-mortem.
  *Ref*: proposal §3. *TDD*: N/A (ops). *Effort*: XS

- [ ] **P7.5** — Revoke legacy Meli OAuth apps
  In Meli developer portal: revoke/delete the 4 legacy OAuth app credentials (one per legacy product). Ensure `zeler-platform` is the only remaining OAuth app.
  *Ref*: proposal §3, design D11. *TDD*: Verify `meli_accounts` has only `app_id="zeler-platform"` docs. *Effort*: XS

- [ ] **P7.6** — Write migration post-mortem doc
  `zeler-platform/docs/migration-postmortem.md`: timeline, what was decommissioned and when, problems encountered, lessons learned, final state (repos archived, DBs dropped, OAuth apps revoked, VMs stopped). Commit and merge.
  *Ref*: proposal §3. *TDD*: N/A (doc). *Effort*: S

---

## Cross-Phase Dependencies

```
P0.6 → P0.7 → P1.3 (Atlas cluster needed before creating collections)
P0.8 → P1.4 (KMS key needed before encryption impl)
P0.9 → all phases (CI required)
P1.10 → P1.11 (JWT mint/verify before proxy)
P1.11 → P2.5 (proxy before AMQP publisher can be tested E2E)
P2.4 → P2.5 (RabbitMQ topology before publisher)
P2.6 → P4.9 (idempotency store before repricer consumer)
P3.2 → P3.3 → P3.13 (models before schema export before Atlas validators)
P3.5 → P4.9 (repos before repricer consumer)
P3.8 → P3.10 → P3.11 (state machine before runner stages)
P4.1 → P4.2 → P4.11 (manifest before registration before repricer wires up)
P4.8 → P4.9 (engine before consumer)
P4.12 → P7.1 (E2E test green before decommission)
P5.1 → P5.2 (audit before migration)
P5.2 → P5.3–P5.6 (auth before screens)
P6A–P6D → P7.1–P7.6 (all modules at parity before decommission)
```

---

## Critical-Path Tasks (Blockers)

These tasks block the most downstream work. Prioritize if team is small:

1. **P0.6** — Atlas cluster (blocks all DB work)
2. **P0.8** — KMS keys (blocks all token encryption)
3. **P1.4** — Envelope encryption (blocks OAuth, refresh, proxy)
4. **P1.8** — Refresh worker (blocks proxy reliability + account lifecycle)
5. **P1.11** — Outbound proxy (blocks ALL module Meli calls)
6. **P2.5** — Webhook classifier + AMQP publish (blocks all module event consumption)
7. **P3.2** — Canonical models (blocks repos, bootstrap, schema export)
8. **P3.10/P3.11** — Bootstrap runner (blocks cluster population)
9. **P4.8** — Rules engine (blocks repricer consumer)
10. **P4.12** — E2E test GREEN (confidence gate before decommission)

---

## Risks Register

| Phase | Risk | Likelihood | Mitigation |
|-------|------|-----------|------------|
| P0 | Atlas private endpoint setup fails / slow | Medium | Allocate 2 days; follow Atlas PrivateLink docs exactly; test from CI before P1 |
| P0 | KMS IAM misconfiguration blocks encryption | Medium | Test `encrypt`/`decrypt` smoke in P0 CI before P1 starts |
| P1 | Meli OAuth test app unavailable | Medium | Register dev OAuth app early; use ngrok or Cloud Run URL for callback in dev |
| P1 | DEK cache causes stale-key reads across replicas | Low | Each replica has its own LRU; on KMS rotation, stale DEKs naturally expire in 5 min |
| P1 | Distributed lock stale-lock cleanup races | Low | Lock TTL 120s → stale after 2 min; tested in P1.7 concurrent tests |
| P2 | Meli IP allowlist changes without notice | Medium | Operational runbook: periodic re-check of published IPs; configurable via env var (no redeploy needed) |
| P3 | Bootstrap API cost for large sellers in dev/staging | Medium | Use a test seller with < 100 items for CI; real sellers run in staging only |
| P3 | Schema export drift (models ≠ committed JSONs) | Medium | CI diff check in P3.3; blocks merge on schema mismatch |
| P4 | AST linter false positive on gateway code | Low | Scope linter to `modules/` only; exclude `gateway/` explicitly |
| P4 | E2E test flaky due to AMQP timing | Medium | Use explicit ack + bounded polling with timeout (10s); mark flaky in CI and retry once |
| P6D | FullDock `stock_locations` Meli scope not in grant | Medium | Verify with Meli OAuth app scopes before implementing P6D.3; adjust if needed |
| P7 | Sellers not re-linked before decommission | High | Communication plan: email sellers 30 days before freeze; show in-app banner |

---

## Decommission Plan Summary

| Action | Trigger | Timeline |
|--------|---------|----------|
| Repricer reads from new cluster only | P4 E2E green | After P4 |
| zeler-app no longer calls legacy APIs | P5.6 done | After P5 |
| Each module reaches parity | Per P6A–P6D checklist | After each P6 sub-phase |
| Legacy repos set to read-only | All modules at parity | After P6 |
| zeler-core archived | After legacy repos frozen | Day of P7.2 |
| Legacy Cloud Run + VMs stopped | After P7.1 | Within 1 week of P7.1 |
| Legacy DBs dropped | 30 days after P7.1 | T+30 days |
| Legacy OAuth apps revoked | After DB drop confirmed | T+30 days |

---

## Startup Plan (First Production Spin-Up)

Order of operations to spin up production environment for the first time:

1. Apply Terraform (Atlas cluster, KMS keys, Secret Manager entries, VPC connector) — P0.6–P0.8
2. Create DB users + test connectivity — P0.7
3. Apply Atlas schema validators (placeholder schemas) — P0.11
4. Deploy `gateway` to Cloud Run (no traffic yet) — after P1
5. Apply full Atlas schema validators (from P3.3) — P3.13
6. Register Meli production OAuth app; update `MELI_CLIENT_ID`, `MELI_REDIRECT_URI` in Secret Manager
7. Declare RabbitMQ topology in production vhost — P2.4
8. Deploy gateway with full config; run health check
9. Link one test seller account (full OAuth flow)
10. Trigger bootstrap job for test seller; verify all stages complete
11. Deploy repricer module (Cloud Run API + VM consumer); verify registration in `module_registry`
12. Run E2E test against production gateway with test seller
13. Migrate production sellers (re-link via OAuth) — batch, seller by seller
14. Deploy remaining modules (P6A–P6D) one by one; verify health after each
15. Begin decommission sequence (P7) after all modules verified in prod

---

## Task Summary

| Phase | Tasks | Effort | Critical Path? |
|-------|-------|--------|---------------|
| P0: Foundations | 11 | XL | Yes (P0.6, P0.8, P0.9) |
| P1: Gateway MVP | 16 | XL | Yes (P1.4, P1.8, P1.11) |
| P2: Webhooks + Event Bus | 8 | L | Yes (P2.5) |
| P3: Core Models + Bootstrap | 13 | L | Yes (P3.2, P3.10, P3.11) |
| P4: Module Runtime + Repricer | 12 | L | Yes (P4.8, P4.12) |
| P5: zeler-app Integration | 6 | M | No (parallel with P6) |
| P6A: sheets-module | 4 | M-L | No |
| P6B: publicador-module | 5 | M-L | No |
| P6C: autoreply-module | 4 | M-L | No |
| P6D: fulldock-module | 4 | M-L | No |
| P7: Decommission | 6 | M | No (terminal) |
| **Total** | **89** | | |

---

*Generated by `sdd-tasks` skill — 2026-04-23*
*Strict TDD: every non-trivial task has a [RED] test-first step or explicit test requirement.*
*Next recommended: `sdd-apply-claudeopenmix` — pick tasks from Phase 0 and begin implementation.*
