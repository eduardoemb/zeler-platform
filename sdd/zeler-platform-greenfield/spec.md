# Specification: zeler-platform-greenfield

**Change**: `zeler-platform-greenfield`
**Type**: Greenfield — all 7 capabilities are NEW
**Date**: 2026-04-23

---

## Bounded Contexts (global)

| Context | Capabilities | Owns | Writes to Meli? | Consumes Meli Events? |
|---|---|---|---|---|
| **Gateway** | `meli-gateway`, `meli-account-registry`, `webhook-event-bus` | OAuth app, tokens, webhook ingress, outbound proxy | YES (only context allowed) | Receives from Meli |
| **Core** | `platform-core-models` | Canonical schemas, event contracts, repository library | No | No |
| **Modules** | `repricer-module` (and future one folder per module) | Module-internal state + rules | No (must proxy via gateway) | Yes (via event bus) |
| **Bootstrap** | `platform-bootstrap` | Bootstrap job orchestration | No (reads only) | No |

**Global ownership rules**:
- A collection has **exactly one writer service** (the "owner").
- Cross-module reads go through the **Core repository library** — no direct collection access from another module.
- Gateway is the **ONLY writer** for Meli-sourced data (`items`, `orders`, `questions`, `messages`, `shipments`, `claims`, `meli_accounts`).
- Modules write only to their own collections (prefix `{module}_*`).
- If module A needs data from module B, it subscribes to an event — never reads B's collections directly.
- Core/Module separation: Core owns Meli-sourced or shared-by-≥2-modules data; Module owns single-capability state (rules, configs, internal history).

## Source of Truth — Entity Table

| Entity | Canonical Collection | Writer | Readers |
|---|---|---|---|
| `meli_accounts` | `zeler_platform.meli_accounts` | gateway only | all modules (read via core repo) |
| `users` (platform operators) | `zeler_platform.users` | gateway (registration) | zeler-app, all modules |
| `items` | `zeler_platform.items` | gateway (webhook + bootstrap) | all modules |
| `orders` | `zeler_platform.orders` | gateway (webhook + bootstrap) | all modules |
| `questions` | `zeler_platform.questions` | gateway (webhook + bootstrap) | all modules |
| `messages` | `zeler_platform.messages` | gateway (webhook + bootstrap) | all modules |
| `shipments` | `zeler_platform.shipments` | gateway (webhook + bootstrap) | all modules |
| `claims` | `zeler_platform.claims` | gateway (webhook + bootstrap) | all modules |
| `events` (domain event log) | `zeler_platform.events` | gateway (emitter) | modules (subscribers), ops |
| `bootstrap_jobs` | `zeler_platform.bootstrap_jobs` | platform-bootstrap | ops |
| `module_registry` | `zeler_platform.module_registry` | module-runtime | all modules |
| `repricer_rules` | `zeler_platform.repricer_rules` | repricer-module | repricer-module only |
| `repricer_history` | `zeler_platform.repricer_history` | repricer-module | repricer-module, ops |

---

## 1. `meli-gateway`

**Context**: Gateway. Single Meli API boundary. Owns OAuth, token refresh, outbound proxy, rate-limit governance.

### Requirements

#### Requirement 1.1: OAuth Authorization Code Flow
The gateway MUST implement the Meli OAuth 2.0 authorization-code flow. It MUST be the ONLY service in the platform registered with Meli as an OAuth client. Modules MUST NOT hold or request Meli tokens directly.

##### Scenario: Seller connects a Meli account (happy path)
- GIVEN an unauthenticated seller at `zeler-app`
- WHEN they click "Connect MercadoLibre" and complete Meli's consent screen
- THEN Meli redirects to the gateway's `/oauth/callback` with an authorization code
- AND the gateway exchanges the code via `POST /oauth/token` against Meli
- AND the gateway upserts a `meli_accounts` document atomically with `status=active`, `connected_at=now`, `last_refreshed_at=now`, `scopes`, `user_id`, `nickname`
- AND the gateway enqueues a bootstrap job for the new account

##### Scenario: Authorization code exchange fails
- GIVEN Meli returns 4xx on `POST /oauth/token` (invalid_grant / expired code)
- WHEN the gateway handles the callback
- THEN it records a structured error (code, correlation id) in logs
- AND it responds 400 to the user with a re-link CTA
- AND no `meli_accounts` document is created or modified

##### Scenario: Duplicate connect by the same seller
- GIVEN a `meli_accounts` document already exists for `user_id` (Meli seller id)
- WHEN the seller completes OAuth again
- THEN the gateway upserts by `user_id` (not insert)
- AND `connected_at` is preserved, `last_refreshed_at` and `scopes` are updated
- AND no duplicate document is created

#### Requirement 1.2: Token Refresh with Distributed Lock
The gateway MUST refresh access tokens before expiry using a **distributed lock per `meli_accounts._id`** so that concurrent refreshes cannot race. Only one refresh attempt per account MAY be in flight at any time.

##### Scenario: Scheduled refresh acquires lock and succeeds
- GIVEN a `meli_accounts` document with `expires_at` within the refresh window (e.g. < 1h)
- WHEN the refresh worker ticks
- THEN it acquires a lock keyed by `meli_accounts._id` with a TTL greater than the worker deadline
- AND it calls Meli `POST /oauth/token` with `grant_type=refresh_token`
- AND it atomically updates `access_token`, `refresh_token`, `expires_at`, `last_refreshed_at`
- AND it releases the lock

##### Scenario: Two workers attempt the same refresh concurrently
- GIVEN two refresh-worker instances pick up the same account in the same tick
- WHEN worker A acquires the lock first
- THEN worker B MUST observe the lock and skip the refresh for that tick
- AND only ONE `POST /oauth/token` call reaches Meli for that account

##### Scenario: `invalid_grant` on refresh
- GIVEN Meli returns `invalid_grant` on refresh
- WHEN the gateway handles the response
- THEN the account's `status` MUST be set to `revoked`
- AND a `MeliAccountRevoked` domain event MUST be emitted on the event bus
- AND no further refreshes MAY be attempted until the seller re-links

#### Requirement 1.3: Outbound Meli Proxy
All outbound Meli API calls from modules MUST pass through the gateway's outbound-proxy endpoint. Modules receive NO raw token material.

##### Scenario: Module calls Meli via proxy (happy path)
- GIVEN a module authenticated with its internal credential (see 5.2) targeting account `A`
- WHEN it POSTs `/gateway/proxy/meli` with `method`, `path`, `body`, `account_id=A`
- THEN the gateway injects the current `access_token` for `A`, forwards the call, returns Meli's response verbatim
- AND the call is counted against `A`'s rate-limit budget for that module

##### Scenario: Proxy call during refresh
- GIVEN account `A` is currently being refreshed (lock held)
- WHEN a module issues a proxy call for `A`
- THEN the gateway MUST wait for the lock up to a bounded timeout (e.g. 5s) and use the new token
- AND if the timeout is exceeded, the gateway returns 503 with a retry hint

#### Requirement 1.4: Rate-Limit Budget per Module
The gateway MUST enforce a per-(account, module) rate-limit budget with a configurable default. On budget exhaustion the gateway MUST return 429 with `Retry-After`. Modules MUST respect backpressure.

##### Scenario: Module exceeds its budget
- GIVEN module `repricer` has budget 60/min against account `A`
- WHEN the 61st request in a minute arrives
- THEN the gateway returns 429 with `Retry-After` seconds
- AND the gateway emits a `RateLimitExceeded` metric labeled by module + account

#### Requirement 1.5: Retry Policy
For transient Meli failures (5xx, network timeout), the gateway MUST retry with exponential backoff and jitter up to a configured max attempts. `4xx` other than `429` MUST NOT be retried.

##### Scenario: Meli returns 502 then 200
- GIVEN a proxy call
- WHEN Meli returns 502 on attempt 1 and 200 on attempt 2
- THEN the gateway surfaces a single 200 response to the module
- AND records both attempts in the gateway call log

#### Requirement 1.6: Structured Logging & Metrics
The gateway MUST emit structured logs (JSON) and metrics for: call count, latency p50/p95, error rate, rate-limit exhaustion, refresh success/failure, `invalid_grant` events — each labeled by `account_id`, `module`, `endpoint`.

##### Scenario: Operator queries metrics for a module
- GIVEN a running gateway
- WHEN an operator queries the metrics endpoint for `module=repricer`
- THEN they see call count, latency p95, error rate, rate-limit hits, all over the last 5m window

---

## 2. `meli-account-registry`

**Context**: Gateway. Canonical store for every Meli seller account linked to the platform.

### Requirements

#### Requirement 2.1: One Record Per Meli Seller
There MUST be exactly one `meli_accounts` document per Meli `user_id`. The collection MUST have a unique index on `user_id`.

##### Scenario: Upsert on (re-)connect
- GIVEN OAuth callback completes successfully
- WHEN the gateway writes to `meli_accounts`
- THEN the write MUST be `updateOne({ user_id }, { $set: {...} }, { upsert: true })`
- AND on a subsequent re-connect, the document is updated, not duplicated

##### Scenario: Two concurrent connects for the same seller
- GIVEN two OAuth callbacks arriving at the same instant for the same `user_id`
- WHEN both upserts execute
- THEN exactly one document exists afterward (guarded by the unique index)
- AND one of the two writes returns a duplicate-key conflict and is retried as an update

#### Requirement 2.2: Canonical Fields
Each document MUST include: `user_id` (string — Meli seller id), `nickname` (string), `status` (enum: `active | revoked | invalid`), `scopes` (array of strings), `connected_at` (ISO UTC), `last_refreshed_at` (ISO UTC), `access_token`, `refresh_token`, `expires_at` (ISO UTC), `created_at`, `updated_at`. `meli_id`-like fields MUST always be stored as string.

##### Scenario: Meli numeric id written
- GIVEN Meli returns `user_id` as a JSON number
- WHEN the gateway persists it
- THEN the value stored in Mongo MUST be a string
- AND the Pydantic model MUST coerce it to string

#### Requirement 2.3: Lifecycle Transitions
Status transitions MUST be: `active → revoked` on `invalid_grant`, `active → invalid` on Meli 401 + failed refresh, `revoked → active` on re-link, `invalid → active` on re-link. Any other transition is forbidden.

##### Scenario: Invalid-grant on scheduled refresh
- GIVEN account status = `active`
- WHEN refresh returns `invalid_grant`
- THEN status becomes `revoked` and a `MeliAccountRevoked` event is emitted

##### Scenario: Seller re-links a revoked account
- GIVEN account status = `revoked`
- WHEN OAuth completes again for the same `user_id`
- THEN status becomes `active`, `connected_at` is updated
- AND a `MeliAccountReconnected` event is emitted

---

## 3. `webhook-event-bus`

**Context**: Gateway. Webhook ingress + internal fan-out over RabbitMQ.

### Requirements

#### Requirement 3.1: Single Webhook Endpoint
Exactly **one** HTTPS endpoint MUST be registered with Meli across the platform. It MUST accept all supported Meli topics: `items`, `orders_v2`, `shipments`, `questions`, `messages`, `claims`, `post_purchase`, `items_prices`, `catalog_item_competition_status`.

##### Scenario: Meli delivers an `items` notification
- GIVEN a seller has an active account
- WHEN Meli POSTs `/webhooks/meli` with topic=`items`, `resource`, `user_id`
- THEN the gateway responds 200 within 500ms
- AND publishes to the internal event bus (see 3.3)

#### Requirement 3.2: Authenticity Verification
The gateway MUST verify each inbound webhook. If Meli provides an HMAC signature header, it MUST validate it; otherwise the gateway MUST apply an **IP allowlist** per Meli's documented source ranges. Invalid requests MUST be rejected with 401 and logged.

##### Scenario: Missing signature / wrong source IP
- GIVEN a POST arrives at `/webhooks/meli` not from a Meli IP range and without valid signature
- WHEN the gateway handles it
- THEN it returns 401 and logs the source IP + path
- AND no event is published

#### Requirement 3.3: At-Least-Once Fan-Out via RabbitMQ Topic Exchange
The gateway MUST publish each valid webhook to a **topic exchange** `meli.events` with a routing key shaped as `{topic}.{action}` (e.g. `items.updated`, `orders_v2.created`). Modules bind their own queues with routing patterns. Delivery MUST be at-least-once; consumers MUST be idempotent (see 3.4).

##### Scenario: Module consumes events it subscribed to
- GIVEN `repricer-module` declares subscription to `items.*` and `items_prices.*`
- WHEN an `items.updated` event is published
- THEN repricer-module's queue receives it
- AND a non-subscribing module's queue does not

#### Requirement 3.4: Idempotency Key
Every published event MUST carry a stable `idempotency_key` derived from `(topic, resource, meli_notification_id)`. Consumers MUST de-duplicate by this key with a retention window of at least 48h.

##### Scenario: Meli redelivers the same notification
- GIVEN the gateway already published event `K`
- WHEN Meli redelivers the same notification (same `notification_id`)
- THEN the gateway publishes again with the same `idempotency_key`
- AND the consuming module processes it exactly once (subsequent deliveries skipped)

#### Requirement 3.5: Dead-Letter Queue
Every consumer queue MUST have a bound dead-letter queue. After N retries (configurable, default 5) a message MUST be routed to the DLQ and an alert emitted.

##### Scenario: Poison message
- GIVEN a consumer handler throws on every attempt for a specific message
- WHEN retries are exhausted
- THEN the message lands on the DLQ
- AND an alert is produced labeled by module + routing key

---

## 4. `platform-core-models`

**Context**: Core. Canonical domain entities, schemas, event contracts. No runtime service — a library.

### Requirements

#### Requirement 4.1: Pydantic v2 Models for Every Canonical Entity
Every canonical entity (`MeliAccount`, `User`, `Item`, `Order`, `Question`, `Message`, `Shipment`, `Claim`, `Event`, `BootstrapJob`) MUST be defined as a Pydantic v2 model in the core package. Any write to `zeler_platform` by any service MUST go through these models.

##### Scenario: Gateway writes an item
- GIVEN the gateway receives an item payload from Meli
- WHEN it writes to `zeler_platform.items`
- THEN it MUST construct an `Item` Pydantic model and call `.model_dump(mode="json")`
- AND any field violating the model raises before the DB write

##### Scenario: Model rejects invalid enum
- GIVEN `MeliAccount.status` is declared as `Literal["active", "revoked", "invalid"]`
- WHEN a caller attempts to set `status="deleted"`
- THEN Pydantic raises a `ValidationError` at construction time

#### Requirement 4.2: JSON Schema Export for MongoDB Validation
The core package MUST export JSON Schema for each canonical entity, and the deployment tooling MUST apply them as MongoDB `$jsonSchema` validators on each collection from day 1.

##### Scenario: Direct DB write bypassing models
- GIVEN an operator runs a raw `insertOne` against `zeler_platform.items` with a missing required field
- WHEN the write executes
- THEN MongoDB rejects it due to schema validation
- AND the operator sees a validation error

#### Requirement 4.3: Versioned Schemas from Day 1
Every canonical entity document MUST include a `schema_version` field (integer). The initial version is `1`. Core MUST export a helper `current_schema_version(entity)` and repositories MUST set it on write.

##### Scenario: New schema version ships
- GIVEN `Item` schema evolves from v1 to v2 adding field `foo`
- WHEN core publishes `v2` with a migration note
- THEN new documents are written with `schema_version=2`
- AND legacy v1 documents continue to be readable (loaders SHOULD upcast, fields absent stay absent)

#### Requirement 4.4: Enumerated Statuses, UTC Timestamps, `meli_id` as String
All status-like fields MUST be typed enums (`Literal` or `Enum`). All timestamps MUST be stored in UTC as ISO-8601 or Mongo `Date`. All Meli identifier fields (`user_id`, `item_id`, `order_id`, `shipment_id`, `question_id`, `message_id`) MUST be stored as **string** regardless of Meli's on-the-wire type.

##### Scenario: Naive datetime rejected
- GIVEN a caller passes a naive (no-tz) `datetime` for `connected_at`
- WHEN the Pydantic model is constructed
- THEN it raises a `ValidationError`

#### Requirement 4.5: Event Contracts
Core MUST define versioned event contracts for all emitted domain events: `ItemUpdated`, `ItemPriceChanged`, `OrderCreated`, `QuestionReceived`, `MessageReceived`, `MeliAccountRevoked`, `MeliAccountReconnected`, `BootstrapCompleted`. Each event carries `event_id`, `account_id`, `occurred_at`, `schema_version`, and payload.

##### Scenario: Producer and consumer agree on shape
- GIVEN the gateway emits `ItemPriceChanged v1`
- WHEN repricer-module deserializes the message
- THEN both sides use the same Pydantic model from core
- AND breaking a field causes test failure at module-level contract tests

---

## 5. `module-runtime`

**Context**: Modules. Loading, lifecycle, event subscription contract. One folder per module.

### Requirements

#### Requirement 5.1: Module Manifest
Every module MUST ship a manifest declaring: `name`, `version`, `subscribed_events` (routing patterns), `owned_collections` (exclusive write set), `health_endpoint`. The runtime MUST refuse to start a module whose manifest is missing or invalid.

##### Scenario: Module registers on startup
- GIVEN `repricer-module` has a valid manifest
- WHEN it boots
- THEN it writes a `module_registry` document with its name, version, subscriptions, owned collections, and `status=online`
- AND it binds RabbitMQ queues matching its subscriptions

##### Scenario: Collision on owned collections
- GIVEN module A declares `owned_collections=[items]`
- WHEN it starts
- THEN the runtime MUST refuse startup (items is gateway-owned) and log the ownership violation

#### Requirement 5.2: Module → Gateway Authentication
Modules MUST authenticate to the gateway using **internal JWT signed by a platform secret** (or mTLS; JWT is default). Credentials MUST NOT be shared between modules. The gateway MUST reject proxy/API calls without valid module credentials.

##### Scenario: Forged module token
- GIVEN an attacker presents a JWT not signed by the platform secret
- WHEN they call the gateway proxy
- THEN the gateway returns 401 and logs the attempt

#### Requirement 5.3: Module Health Endpoint
Each module MUST expose `/health` returning liveness and readiness (RabbitMQ consumer status, last event processed, DB reachable). The platform's monitoring MUST scrape it.

##### Scenario: Module RabbitMQ consumer stalls
- GIVEN `/health` observes no events processed for 10 minutes on a live queue
- WHEN the health endpoint is queried
- THEN it returns `ready=false` with reason `consumer_stalled`
- AND an alert is produced

#### Requirement 5.4: Cross-Module Isolation
A module MUST NOT read or write another module's collections. Shared reads MUST go through the core repository library, which exposes read-only accessors for canonical entities.

##### Scenario: Forbidden direct read attempt
- GIVEN repricer-module tries to query `autoreply_history` directly
- WHEN a lint/contract test runs
- THEN it fails with a clear ownership violation
- AND the correct pattern (subscribe to an event) is suggested

---

## 6. `repricer-module`

**Context**: Module. Reference module built on the new stack. **NEW — redesigned rules engine; no migration from legacy Repricer.**

### Requirements

#### Requirement 6.1: Event Subscriptions
Repricer-module MUST subscribe to `items.*` and `items_prices.*` routing keys on the `meli.events` exchange. It MUST be idempotent by `idempotency_key`.

##### Scenario: Price-changed event arrives
- GIVEN a rule exists for SKU `X` on account `A`
- WHEN `items_prices.updated` arrives for item `X`
- THEN repricer-module evaluates the rule and, if applicable, schedules a price update

#### Requirement 6.2: Rules Engine (Greenfield)
Repricer-module MUST provide a rules engine whose inputs are: current Meli price, rule parameters (floor, ceiling, step, mode), competition data (if available). The engine MUST be deterministic and fully unit-testable with no I/O.

##### Scenario: Rule triggers a price increase
- GIVEN rule `R` is mode=`track_buybox` with `floor=100`, `ceiling=200`
- WHEN current price is 150 and buybox is 180
- THEN the engine emits a decision `set_price=180` (bounded by ceiling)

##### Scenario: Rule refuses a below-floor price
- GIVEN rule `R` has `floor=100`
- WHEN the engine computes a candidate price of 90
- THEN it emits `no_action` with reason `below_floor`
- AND `repricer_history` records the no-op

#### Requirement 6.3: Writes Go Through Gateway Proxy
Repricer-module MUST send all Meli price updates via the gateway's outbound proxy (see 1.3). It MUST NOT call `api.mercadolibre.com` directly.

##### Scenario: Module attempts direct Meli call
- GIVEN a network-policy / lint check
- WHEN repricer-module code contains a direct Meli URL
- THEN the check fails before merge

#### Requirement 6.4: Module-Owned State
Repricer-module MUST own exactly two collections: `repricer_rules` (canonical rule definitions) and `repricer_history` (per-decision log). No other module MUST write to these. Shared data (items, prices) MUST be read via core repository.

##### Scenario: History is recorded for every decision
- GIVEN any rule evaluation completes
- WHEN it produces a `set_price` or `no_action` decision
- THEN a `repricer_history` document is written with inputs, decision, outcome of the gateway proxy call (status + latency)

---

## 7. `platform-bootstrap`

**Context**: Bootstrap job. Standalone runner, triggered on newly-connected account or manual resync. Idempotent.

### Requirements

#### Requirement 7.1: Job Lifecycle
Every bootstrap run MUST be represented by a `bootstrap_jobs` document with state machine: `pending → running → (paused|completed|failed)`; `paused → running`; `failed → pending` (on retry). State transitions MUST be atomic.

##### Scenario: Account connect enqueues a job
- GIVEN the gateway completes OAuth for a new account `A`
- WHEN the account is persisted
- THEN a `bootstrap_jobs` document is created with `account_id=A`, `state=pending`, `cursor={}`

#### Requirement 7.2: Ingestion Stages (Ordered)
A bootstrap MUST execute the following stages in order, per account:
1. account metadata refresh
2. items (paginated, all active)
3. orders (date-bounded: last **90 days** default, configurable per run)
4. questions — open first, then closed from the last 30 days
5. messages (per order pack)
6. shipments (from orders)
7. claims (if any)

Stages MUST be resumable and MUST NOT restart completed stages on resume.

##### Scenario: Large seller with 200k items
- GIVEN account `A` has 200k items
- WHEN the items stage runs
- THEN it paginates with Meli's search/scan API
- AND it persists a cursor in `bootstrap_jobs.cursor.items` after each page
- AND it respects gateway rate limits (backpressure on 429)

#### Requirement 7.3: Idempotent Writes
All bootstrap writes MUST upsert by the canonical key (`item_id` for items, `order_id` for orders, etc.). Re-running a completed bootstrap MUST produce no duplicates.

##### Scenario: Resync of an already-bootstrapped account
- GIVEN account `A` previously completed bootstrap
- WHEN an operator triggers a resync
- THEN the job re-runs all stages
- AND every write is an upsert; no duplicates are created in any canonical collection

#### Requirement 7.4: Resumable from Last Cursor
If a bootstrap job is interrupted (`paused` or `failed`), on resume it MUST continue from the last persisted cursor within the last in-progress stage. Completed stages MUST be skipped.

##### Scenario: Crash mid-items stage
- GIVEN a bootstrap job crashes after persisting 150 pages of items (cursor `p151`)
- WHEN the job is resumed
- THEN it resumes the items stage at `p151`
- AND it does NOT re-run account-metadata or restart items from page 1

#### Requirement 7.5: Progress Observability
The `bootstrap_jobs` document MUST expose: `state`, `current_stage`, `cursor`, `stage_progress` (pages done / pages total when available), `started_at`, `updated_at`, `finished_at`, `errors[]`. Operators MUST be able to query progress for any account.

##### Scenario: Operator queries job status
- GIVEN a running job for account `A`
- WHEN an operator reads the `bootstrap_jobs` document
- THEN they see current stage, cursor, last update timestamp, error count
- AND on completion, a `BootstrapCompleted` event is emitted on the event bus

---

## Core-vs-Module Separation Rules (summary)

- **Core owns**: any Meli-sourced entity OR any entity shared by ≥ 2 modules. Gateway is the sole writer for all of these.
- **Module owns**: rules, configurations, module-internal state, module-internal history. Prefix collection names with module id.
- **Cross-module data exchange**: events only. Never direct collection access. Enforced by lint/contract tests and by ownership declarations in the module manifest.
- **No module** carries legacy debt: no per-nickname collections, no legacy token fallback, no shadow-sync, no `info_app` DB-stored OAuth credentials. All OAuth credentials live in Secret Manager.

---

## Coverage Summary

| Capability | Requirements | Scenarios | Happy Path | Failure Modes |
|---|---|---|---|---|
| `meli-gateway` | 6 | 11 | ✅ | ✅ (code exchange fail, concurrent refresh, invalid_grant, 502 retry, rate-limit exceeded, proxy during refresh) |
| `meli-account-registry` | 3 | 5 | ✅ | ✅ (concurrent connect, invalid-grant transition) |
| `webhook-event-bus` | 5 | 5 | ✅ | ✅ (bad signature/IP, poison message, redelivery) |
| `platform-core-models` | 5 | 6 | ✅ | ✅ (invalid enum, raw insert, naive datetime) |
| `module-runtime` | 4 | 5 | ✅ | ✅ (ownership collision, forged token, stalled consumer, forbidden read) |
| `repricer-module` | 4 | 5 | ✅ | ✅ (below-floor, direct-call lint, history recording) |
| `platform-bootstrap` | 5 | 6 | ✅ | ✅ (large seller backpressure, resync idempotency, crash/resume) |

**Total**: 32 requirements, 43 scenarios.
