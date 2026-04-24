# Design: zeler-platform (greenfield)

**Change**: `zeler-platform-greenfield`
**Status**: design complete
**Audience**: senior engineer ready to implement tomorrow

---

## 1. Target architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                               MercadoLibre                                 │
│  api.mercadolibre.com  (OAuth, REST)   +   webhook POSTs (notifications)   │
└───────────────┬─────────────────────────────────┬──────────────────────────┘
                │                                 │
   (OAuth + outbound REST)                 (inbound webhooks)
                │                                 │
┌───────────────▼─────────────────────────────────▼──────────────────────────┐
│                         zeler-meli-gateway  (FastAPI, Cloud Run)           │
│   /oauth/*  /webhooks/meli  /proxy/meli/*  /internal/tokens/issue          │
│   + refresh worker (APScheduler cron)   + rate-limit governor              │
└────┬──────────────────────────┬──────────────────────────┬─────────────────┘
     │                          │                          │
   (reads)                  (publishes AMQP)         (encrypted store)
     │                          │                          │
     │                  ┌───────▼────────────┐   ┌─────────▼────────────┐
     │                  │  RabbitMQ          │   │  MongoDB Atlas       │
     │                  │  exchange:         │   │  cluster:            │
     │                  │  meli.events       │   │  zeler-platform      │
     │                  │  (topic)           │   │  db: zeler_platform  │
     │                  └───────┬────────────┘   └─────────▲────────────┘
     │                          │                          │
     │       ┌──────────────────┼──────────────────┐       │
     │       │                  │                  │       │
┌────▼───────▼────┐   ┌─────────▼────────┐   ┌─────▼───────▼─────┐
│ modules/repricer│   │ modules/sheets   │   │ modules/autoreply │ ... fulldock,
│ (Cloud Run +    │   │ (Cloud Run)      │   │ (Cloud Run +      │     publicador
│  VM consumers)  │   │                  │   │  VM consumers)    │
└─────────────────┘   └──────────────────┘   └───────────────────┘
                            ▲
                            │ (HTTP, REST)
                  ┌─────────┴──────────┐
                  │ zeler-app          │
                  │ Next.js 15         │
                  │ (Vercel / Cloud Run)│
                  └────────────────────┘

bootstrap/  (Cloud Run Jobs, one-shot per account)
  └── reads gateway /proxy/meli/*  →  writes canonical collections via core repo
```

Flow summary:
- **Inbound**: Meli → gateway webhooks → Mongo `webhook_events` (audit/idempotent) → RabbitMQ → modules.
- **Outbound**: module → `/proxy/meli/*` (gateway injects token, enforces scope, records audit) → Meli.
- **UI**: `zeler-app` calls module REST APIs and gateway read APIs over internal JWT.
- **Bootstrap**: Cloud Run Job, per-account, reads from gateway proxy, writes canonical collections.

---

## 2. Tech stack decisions

| Layer | Choice | Version | Rationale |
|-------|--------|---------|-----------|
| Language (backend) | Python | 3.11+ | Team muscle memory (5 legacy repos + zeler-core all Python). |
| Web framework | FastAPI | ≥0.110 | Used by Repricer/PublicadorMeli already; Pydantic v2 native. |
| Models | Pydantic | v2 (≥2.6) | Strict typing, JSON Schema export for Mongo validators. |
| Python deps | `uv` workspaces | ≥0.4 | Already in zeler-core; monorepo-friendly, fast resolver. |
| Data store | MongoDB Atlas | 7.0+ | Existing operational knowledge; canonical model already Mongo. |
| Messaging | RabbitMQ | 3.12+ | Existing stack (`amqp` library / `aio-pika` for async). |
| Token crypto | AES-256-GCM + GCP KMS envelope | — | See Decision D4. |
| Secrets | GCP Secret Manager | — | Team uses GCP; KMS + Secret Manager integrate natively. |
| Containers | Docker + Cloud Run (services + jobs) | — | Gateway, modules' API, bootstrap as Cloud Run Jobs. |
| Long-running consumers | Cloud Run Jobs (for bounded runs) OR GCE VMs w/ Docker for always-on AMQP consumers | — | AMQP consumers pin to VM Docker (consistent with Repricer/SheetSeller pattern); HTTP surfaces go Cloud Run. |
| Frontend | Next.js (existing `zeler-app`) | 15 + App Router | Already in place; no Python UI. |
| Observability | `structlog` JSON + OpenTelemetry SDK for tracing + GCP Cloud Trace + bounded Prometheus text metrics | — | Stdlib `logging` alone lacks structured fields; structlog is cheap; P1.17 uses a lightweight in-process Prometheus collector gated by `OTEL_METRICS_ENABLED`, while external Prometheus/PromQL handles p95/error-rate rollups. |
| CI/CD | GitHub Actions | — | Same as existing repos; per-package matrix build. |

---

## 3. Monorepo layout

```
zeler-platform/
├── pyproject.toml                 # uv workspace root
├── uv.lock
├── .python-version                # 3.11
├── gateway/
│   ├── pyproject.toml
│   └── src/zeler_gateway/
│       ├── app.py                 # FastAPI
│       ├── oauth/                 # /oauth/authorize, /oauth/callback
│       ├── webhooks/              # /webhooks/meli + classifier + AMQP publisher
│       ├── proxy/                 # /proxy/meli/* (scoped outbound)
│       ├── tokens/                # refresh worker, KMS envelope, lock
│       └── internal/              # /internal/tokens/issue (JWT-gated)
├── core/
│   ├── pyproject.toml             # zeler_platform_core
│   └── src/zeler_platform_core/
│       ├── models/                # Pydantic: Item, Order, Question, ...
│       ├── repos/                 # read-only repositories + Mongo client singleton
│       ├── events/                # AMQP envelopes + routing keys enum
│       └── auth/                  # internal JWT mint/verify (KMS-signed)
├── modules/
│   ├── repricer/
│   │   ├── pyproject.toml
│   │   └── src/zeler_repricer/    # FastAPI admin API + AMQP consumer + reprice workers
│   ├── sheets/                    # formerly SheetSeller
│   ├── publicador/
│   ├── autoreply/
│   └── fulldock/
├── bootstrap/
│   ├── pyproject.toml
│   └── src/zeler_bootstrap/       # DAG runner; Cloud Run Job entrypoint
├── infra/
│   ├── atlas/                     # $jsonSchema validators per collection (JSON files)
│   ├── terraform/                 # Atlas project/cluster, GCP KMS, Secret Manager, Cloud Run
│   └── rabbitmq/                  # exchange/queue definitions (rabbitmqctl definitions.json)
├── docs/                          # ADRs + runbooks
├── tests/                         # cross-package integration
└── .github/workflows/             # CI matrix
```

### uv workspaces

Root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["gateway", "core", "modules/*", "bootstrap"]

[tool.uv.sources]
zeler_platform_core = { workspace = true }
```

Each member declares `dependencies = ["zeler_platform_core"]` as a workspace dep. This mirrors the current zeler-core pattern and gives: single lockfile, per-package Docker builds (`uv sync --package gateway`), ruff/mypy configured once at root.

---

## 4. MongoDB schema design

**Global rules** (enforced at DB level):
- ONE database: `zeler_platform`.
- ONE collection per entity. **No `{nickname}_*` collections.** Tenant isolation = `seller_id` field + index.
- `$jsonSchema` validator active on every collection from day 1 (`validationLevel: "strict"`, `validationAction: "error"`).
- No unbounded arrays. 1:many = reference.
- All documents carry `schema_version: int` for future evolution.
- All timestamps are UTC ISO datetimes (BSON Date).

### 4.1 `users`

**Purpose**: platform operators (people who log into `zeler-app`). Decoupled from `meli_accounts`.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | ObjectId | — |
| `email` | string | unique |
| `name` | string | — |
| `auth_provider` | enum `google`, `password` | — |
| `meli_account_ids` | [ObjectId] | bounded (per-user; a user owns ≤ ~20 Meli nicknames) |
| `module_permissions` | object `{ module_id: [scopes] }` | — |
| `created_at`, `updated_at` | Date | — |
| `schema_version` | int | 1 |

**Indexes**:
- `{ email: 1 }` unique
- `{ meli_account_ids: 1 }`

**Growth**: hundreds to low thousands. Negligible.

### 4.2 `meli_accounts`

**Purpose**: OAuth records — one per (Meli seller nickname × platform app). Tokens envelope-encrypted.

> **Delta v2 (P1.3/P1.4 apply, 2026-04-24)**: field names and envelope structure updated to match Python `cryptography.hazmat` AES-GCM API and a per-account (not per-token) DEK strategy. Changes captured in engram `sdd/zeler-platform-greenfield/design-delta-meli-accounts` and reflected below. v1 names preserved in the history section at the end.
>
> **Delta v2.1 (P1.6 apply, 2026-04-24)**: token nonces are now one per ciphertext: `token_nonce` for the access token and `refresh_token_nonce` for the refresh token. AES-GCM forbids nonce reuse under the same DEK, so a single shared nonce field was incorrect.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `_id` | ObjectId | yes | — |
| `seller_id` | long | yes | Meli user_id (int64) — **the tenant key** |
| `nickname` | string | yes | Meli nickname |
| `app_id` | string | yes | always `"zeler-platform"` (single Meli OAuth app) |
| `platform_user_id` | string | yes | Zeler platform user owning this link |
| `access_token_ciphertext` | binData \| string | yes | AES-GCM ciphertext with tag appended (Python `AESGCM.encrypt` output) |
| `access_token_dek_wrapped` | binData \| string | yes | KMS-wrapped DEK used for this token |
| `refresh_token_ciphertext` | binData \| string | yes | same pattern as access |
| `refresh_token_dek_wrapped` | binData \| string | yes | KMS-wrapped DEK for refresh (may equal access DEK; kept per-field for rotation independence) |
| `token_nonce` | binData \| string | yes | 96-bit IV for `access_token_ciphertext` (regenerated every re-encrypt) |
| `refresh_token_nonce` | binData \| string | yes | 96-bit IV for `refresh_token_ciphertext` (regenerated every re-encrypt) |
| `scopes` | array[string] | yes | OAuth scopes granted by user |
| `kms_key_version` | string | yes | e.g. `projects/.../cryptoKeys/meli-tokens/cryptoKeyVersions/3` |
| `status` | enum | yes | `active`, `pending`, `refresh_pending`, `revoked`, `invalid_grant`, `error` |
| `expires_at` | Date | yes | access_token expiry (Meli returns `expires_in`) |
| `refresh_token_expires_at` | Date | no | refresh_token expiry (Meli: ~6 months); null if unknown |
| `lock_held_until` | Date \| null | no | distributed lock — sparse indexed |
| `last_refresh_at` | Date | no | — |
| `last_error` | string | no | — |
| `sync_status` | subdoc `{ oauth: {ok, at}, linkage: {...} }` | no | carried from Repricer pattern |
| `created_at` | Date | yes | — |
| `updated_at` | Date | yes | — |
| `schema_version` | int | no | set on writes once P3 canonical models land |

**Indexes**:
- `{ seller_id: 1, app_id: 1 }` unique
- `{ status: 1, expires_at: 1 }` — refresh worker query (ESR: Equality status, Range expires_at)
- `{ lock_held_until: 1 }` sparse — distributed lock cleanup

**Validator**: see `infra/mongo/schemas/meli_accounts.json` (source of truth — applied via `infra/mongo/apply_validators.py`).

**Envelope encryption semantics** (see §5.2):
- One DEK per account (cached in LRU TTL 5min, max 1000).
- DEK wrapped by KMS `meli-tokens` symmetric key once on first write; re-used for both access and refresh of the same account unless rotation forces re-wrap.
- Nonces (`token_nonce`, `refresh_token_nonce`) regenerated independently every re-encrypt; AES-GCM forbids nonce reuse under the same key.
- Ciphertext fields carry the GCM tag appended by Python's `AESGCM.encrypt` — do NOT store tag separately.
- `account_id` used as Additional Authenticated Data (AAD) to bind ciphertext to the document.

**Growth**: 1 doc per linked Meli account. Thousands total.

**v1 field names (pre-2026-04-24, DO NOT USE)**: `access_token_ct` + `access_token_iv` + `access_token_tag` + `refresh_token_ct` + `refresh_token_iv` + `refresh_token_tag` + `dek_wrapped` (single). Replaced by v2 above.

### 4.3 `items`

**Purpose**: canonical product catalog from Meli.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | string | Meli `item_id` (e.g. `"MLM123"`) |
| `seller_id` | long | tenant |
| `title` | string | — |
| `price`, `base_price` | decimal128 | — |
| `available_quantity` | int | — |
| `status` | string | — |
| `category_id` | string | — |
| `variations` | [subdoc] | bounded at Meli level (~50 max) |
| `attributes` | [subdoc] | bounded |
| `shipping` | subdoc | — |
| `health` | double | — |
| `last_meli_sync_at` | Date | — |
| `date_created`, `last_updated` | Date | — |
| `schema_version` | int | 1 |

**Indexes**:
- `{ seller_id: 1, status: 1, last_updated: -1 }` (ESR: Equality seller_id+status, Range last_updated; covers most module list queries)
- `{ seller_id: 1, category_id: 1 }`
- `{ last_meli_sync_at: 1 }` — backfill/maintenance

**Growth**: up to ~100k items per large seller × N sellers. Size: ~5 KB/doc. Plan for 10M+ docs → monitor, consider sharding key `{ seller_id: 1, _id: 1 }` if > ~200 GB.

### 4.4 `orders`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | long | Meli `order_id` |
| `seller_id` | long | — |
| `buyer_id` | long | — |
| `status` | enum | — |
| `date_created` | Date | — |
| `date_closed` | Date | — |
| `total_amount` | decimal128 | — |
| `items` | [{ item_id, qty, unit_price }] | bounded |
| `shipment_id` | long | reference → `shipments` |
| `tags`, `feedback` | — | — |

**Indexes**:
- `{ seller_id: 1, date_created: -1 }` — primary UI/query shape
- `{ seller_id: 1, status: 1, date_created: -1 }` — filter by state
- `{ shipment_id: 1 }` sparse
- `{ buyer_id: 1 }` (analytics)

**Growth**: hundreds of thousands per active seller/year. ~3 KB/doc.

### 4.5 `questions`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | long | Meli `question_id` |
| `seller_id` | long | — |
| `item_id` | string | reference → `items` |
| `text` | string | — |
| `status` | enum `UNANSWERED`, `ANSWERED`, `DELETED`, `BANNED` | — |
| `answer` | `{ text, date_created, status }` | — |
| `from_user_id` | long | — |
| `date_created` | Date | — |

**Indexes**:
- `{ seller_id: 1, status: 1, date_created: -1 }` — autoreply module's primary query
- `{ item_id: 1, date_created: -1 }`

### 4.6 `messages`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | string | Meli `message_id` |
| `seller_id` | long | — |
| `pack_id` | string | conversation group |
| `order_id` | long | nullable |
| `from_user_id`, `to_user_id` | long | — |
| `text` | string | — |
| `status` | enum | — |
| `date_created` | Date | — |
| `read_at` | Date | — |

**Indexes**:
- `{ seller_id: 1, pack_id: 1, date_created: -1 }`
- `{ seller_id: 1, status: 1, date_created: -1 }`

### 4.7 `shipments`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | long | Meli `shipment_id` |
| `seller_id` | long | — |
| `order_id` | long | — |
| `status`, `substatus` | enum | — |
| `tracking_number` | string | — |
| `logistic_type` | enum `fulfillment`, `cross_docking`, `self_service` | — |
| `date_created`, `last_updated` | Date | — |

**Indexes**:
- `{ seller_id: 1, status: 1, last_updated: -1 }`
- `{ order_id: 1 }`

### 4.8 `claims`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | long | Meli `claim_id` |
| `seller_id`, `buyer_id` | long | — |
| `order_id` | long | — |
| `status`, `stage`, `type` | enum | — |
| `date_created` | Date | — |
| `resolution` | subdoc | — |

**Indexes**:
- `{ seller_id: 1, status: 1, date_created: -1 }`
- `{ order_id: 1 }`

### 4.9 `webhook_events`

**Purpose**: raw Meli webhook audit + idempotency store.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | string | Meli `_id` from notification payload (idempotent upsert) |
| `topic` | string | `orders_v2`, `items`, `questions`, ... |
| `user_id` | long | Meli seller_id |
| `resource` | string | `/orders/123` |
| `received_at` | Date | TTL anchor |
| `published_at` | Date | nullable (when AMQP publish succeeded) |
| `classification` | string | routing key emitted |
| `raw_body` | object | full Meli payload |
| `source_ip` | string | — |

**Indexes**:
- `{ received_at: 1 }` **TTL 45 days** (audit + idempotency window; ≥ Meli's max retry window)
- `{ topic: 1, received_at: -1 }`
- `{ user_id: 1, received_at: -1 }` (debug by seller)

**Growth**: ~10-50 events/sec peak × 45 days. Plan ~100 GB working set; size cluster accordingly.

### 4.10 `bootstrap_jobs`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | ObjectId | — |
| `seller_id` | long | — |
| `state` | enum `pending`, `running`, `succeeded`, `failed`, `cancelled` | — |
| `dag` | `{ step: status }` | e.g. `{ items: "done", orders: "running", ... }` |
| `checkpoints` | `{ items: { scroll_id, offset }, orders: { cursor }, ... }` | resumable |
| `started_at`, `finished_at` | Date | — |
| `error` | string | — |

**Indexes**:
- `{ seller_id: 1, state: 1 }`
- `{ state: 1, started_at: -1 }` — operator dashboard

### 4.11 `module_registry`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | string | module id, e.g. `"repricer"` |
| `version` | semver string | — |
| `allowed_meli_scopes` | [string] | e.g. `["PUT /items/*", "GET /items/*"]` — enforced by gateway proxy |
| `routing_keys` | [string] | AMQP keys module subscribes to |
| `status` | enum `enabled`, `disabled`, `degraded` | — |
| `last_heartbeat_at` | Date | — |
| `health` | subdoc | metrics snapshot |

**Indexes**: `{ status: 1 }`.

### 4.12 Module-owned examples

Naming convention: `<module>_<entity>` to make ownership obvious. Modules write only to their own collections; reads across modules go through `core.repos` (read-only).

**`repricer_rules`**

| Field | Type |
|-------|------|
| `_id` | ObjectId |
| `seller_id` | long |
| `item_id` | string (→ items) |
| `strategy` | enum `min_price`, `competitive`, `maximize` |
| `min_price`, `max_price` | decimal128 |
| `active` | bool |
| `updated_at` | Date |

Indexes: `{ seller_id: 1, active: 1 }`, `{ item_id: 1 }` unique partial (active only).

**`repricer_history`**

| Field | Type |
|-------|------|
| `_id` | ObjectId |
| `seller_id` | long |
| `item_id` | string |
| `old_price`, `new_price` | decimal128 |
| `reason` | string |
| `applied_at` | Date |

Indexes: `{ item_id: 1, applied_at: -1 }`, `{ seller_id: 1, applied_at: -1 }`.
TTL: `{ applied_at: 1 }` TTL 365 days (policy: 1 year of reprice history).

---

## 5. OAuth + token refresh flow

### 5.1 Authorization code flow (sequence)

```
user ── "Link Meli" ─→ zeler-app
zeler-app ── redirect ─→ /oauth/authorize?seller_user_id=<platform_user_id>
gateway  ── 302 ─→ https://auth.mercadolibre.com/authorization?...&state=<signed_jwt>
user ── authorizes ─→ Meli
Meli ── 302 with code ─→ /oauth/callback?code=...&state=<signed_jwt>
gateway  ── verifies state JWT ──
gateway  ── POST /oauth/token {grant_type: authorization_code, code} ─→ Meli
Meli ── {access_token, refresh_token, user_id, expires_in} ─→
gateway  ── envelope-encrypt ──
gateway  ── upsert meli_accounts (seller_id, app_id=zeler-platform) ──
gateway  ── emit AMQP "accounts.linked" ──
gateway  ── 302 ─→ zeler-app success page
```

State is a KMS-signed JWT with 10 min TTL containing `platform_user_id`. CSRF-safe.

### 5.2 Envelope encryption (Decision D4 detail) — v2

> **Delta v2 (P1.4 apply, 2026-04-24)**: GCP KMS keyring is `zeler-platform` (not `zeler`). Envelope record layout updated to match §4.2 v2 field names and Python `cryptography.hazmat` AES-GCM API semantics (tag embedded in ciphertext). Implementation in `gateway/src/zeler_gateway/tokens/encryption.py`.

- **GCP KMS** key (dev): `projects/zeler-platform-dev/locations/us-central1/keyRings/zeler-platform/cryptoKeys/meli-tokens` (HSM-backed, 90-day rotation). Prod path follows the same shape under `zeler-platform-prod` once P3 lands.
- **Runtime auth**: `gateway-sa@zeler-platform-dev.iam.gserviceaccount.com` with `roles/cloudkms.cryptoKeyEncrypterDecrypter` on `meli-tokens` and `roles/cloudkms.signerVerifier` on `platform-jwt`. Local dev uses gcloud ADC.
- **DEK strategy**: one DEK per account (cached in LRU TTLCache, max 1000 entries, TTL 5 min), shared by both access and refresh tokens of that account. `account_id` used as AES-GCM Additional Authenticated Data (AAD) — binds ciphertext to the document and surfaces tampering as `InvalidTag`.
- **Write path**: generate 32-byte random DEK (if not cached) → KMS `encrypt` to wrap → generate an independent 12-byte random nonce per token → `AESGCM(dek).encrypt(nonce, plaintext, aad=account_id)` — the 16-byte GCM tag is **appended to the ciphertext** by the Python API. Store `{ access_token_ciphertext, access_token_dek_wrapped, refresh_token_ciphertext, refresh_token_dek_wrapped, token_nonce, refresh_token_nonce, kms_key_version }` per §4.2.
- **Read path**: if DEK not in cache, KMS `decrypt(dek_wrapped)` → cache → `AESGCM(dek).decrypt(nonce, ciphertext, aad=account_id)`.
- **Rotation**: re-wrap DEKs on KMS key version bump (no plaintext re-encryption needed). `kms_key_version` on each doc tracks the wrap vintage.

Chosen over alternatives because: (a) KMS-only per-field encryption adds latency per read; (b) plaintext-at-rest is non-negotiable reject; (c) envelope gives rotation via re-wrap without re-encrypting all ciphertext.

### 5.3 Refresh worker — v2

> **Delta v2 (P1.4 apply, 2026-04-24)**: distributed lock moved from a `refresh_lock` subdoc to a flat `lock_held_until` Date field per §4.2 v2. Semantically identical (lease-based lock with TTL) but trivially sparse-indexable and cheaper to query.

- Process: APScheduler inside `gateway`, interval `every 5 minutes`.
- Query: `{ status: { $in: ["active", "refresh_pending"] }, expires_at: { $lt: now + 15.min } }` (ESR index `{status: 1, expires_at: 1}` in §4.2).
- **Distributed lock** via Mongo atomic update against `lock_held_until`:
  ```
  findOneAndUpdate(
    { _id, $or: [ { lock_held_until: null },
                  { lock_held_until: { $lt: now } } ] },
    { $set: { lock_held_until: now + 120s } }
  )
  ```
  If null → another worker holds the lock (it's in the future), skip. If doc returned → we own the lease until `lock_held_until`. On completion, `$set: { lock_held_until: null }`. Stale leases (past `lock_held_until`) are automatically re-acquirable by any worker.
- Refresh: `POST /oauth/token grant_type=refresh_token`. On success: re-encrypt new token pair (re-uses account DEK via §5.2), set `lock_held_until: null`, update `last_refreshed_at`, update `sync_status.oauth`.
- Status transitions: `active` → `refresh_pending` (lock acquired) → `active` on success, or `error` on transient failure, or `revoked` on `invalid_grant`.
- **On `invalid_grant`** (HTTP 400 with `error=invalid_grant`): `status=revoked`, emit AMQP `accounts.revoked`, **never retry** — account must re-link via OAuth. This matches Repricer's canonical behavior.
- Every run: emit `structlog` event `refresh.run` with `{ attempted, succeeded, failed, revoked }`.

### 5.4 Outbound proxy

Modules call `gateway` instead of Meli:

```
POST /proxy/meli/items/{item_id}
  Authorization: Bearer <internal-jwt>     # KMS-signed, 60s TTL, claims: { module_id, seller_id }
  X-Idempotency-Key: <uuid>                 # required on writes
  Body: <forwarded>
```

Gateway:
1. Verifies internal JWT (KMS public key cached).
2. Looks up module in `module_registry`. Checks `allowed_meli_scopes` matches the request method+path.
3. Loads `meli_accounts` by `seller_id`; if `status != active`, returns 412 Precondition Failed.
4. Decrypts access_token (DEK cache).
5. Performs Meli call with retry policy (at-most-once for writes when `X-Idempotency-Key` present).
6. Writes one `audit_log` event: `{ module_id, seller_id, method, path, status, duration_ms, trace_id }`.
7. Returns Meli response verbatim (status + body). Streams for large responses.

Metrics emitted by the gateway are intentionally low-cardinality. The proxy records call counts, latency histograms, and rate-limit hits by bounded dimensions such as `module_id`, endpoint, and status; it does **not** emit raw `seller_id`/`account_id` metric labels by default. Account-level investigation uses the `audit_log`, structured logs, and traces, or a future controlled sampling/allowlist mechanism if per-account metrics become operationally necessary.

For **high-frequency Repricer workers**, add `POST /internal/tokens/issue { seller_id, scopes: [...], ttl_s: 300 }` that returns a short-lived access_token directly to the worker. Module can then call Meli directly for 5 minutes without per-call proxy overhead. Audit is lost for that window — acceptable trade because (a) the issuance is logged, (b) scopes are narrow, (c) ttl is short. This is the Repricer "high-throughput escape hatch."

---

## 6. Webhook flow

### 6.1 Receiver

- Endpoint: `POST /webhooks/meli`.
- **Source validation**: IP allowlist (Meli publishes these; updated via infra config). 403 if not in list. (Meli does NOT sign payloads — IP allowlist is the best available verification.)
- Idempotent upsert into `webhook_events` using payload's `_id` as Mongo `_id`. If duplicate → 200 OK, no further action.
- Respond 200 within 500 ms (Meli retries after 5 s otherwise).

### 6.2 Classification + publish

```python
routing_key = f"{topic_to_domain[topic]}.{verb}"
# examples:
# topic="orders_v2"    → "orders.updated"
# topic="questions"    → "questions.new" or "questions.updated"
# topic="items"        → "items.updated"
# topic="items_prices" → "items.price_updated"
# topic="shipments"    → "shipments.updated"
# topic="claims"       → "claims.updated"
# topic="messages"     → "messages.new"
```

Exchange: `meli.events` (type=topic, durable). Envelope:

```json
{
  "event_id": "<mongo_id of webhook_events>",
  "event_type": "orders.updated",
  "occurred_at": "2026-04-23T12:34:56Z",
  "seller_id": 123456,
  "resource": "/orders/987",
  "trace_id": "<otel>"
}
```

Payload does NOT include the full Meli resource body. Modules fetch-on-demand via gateway proxy to keep event size small and avoid stale snapshots.

### 6.3 Module subscriptions

Each module declares its routing keys in `module_registry.routing_keys`. Queue naming: `zeler.<module>.<domain>` (e.g. `zeler.repricer.items`, `zeler.autoreply.questions`). Bind to exchange with the declared routing keys.

### 6.4 DLQ + retries

- Per module queue has a DLX: `zeler.<module>.<domain>.dlq`.
- Consumer policy: `x-delivery-limit: 5`, exponential backoff (1s, 5s, 30s, 2m, 10m) via intermediate delay queues.
- DLQ drained manually by operator (Grafana/Loki alert on depth > 100).

---

## 7. Bootstrap flow

Bootstrap is a **Cloud Run Job** per `meli_account`, driven by a state machine persisted in `bootstrap_jobs`.

### 7.1 DAG

```
          ┌───────────┐
          │ accounts  │  (verify linkage, fetch nickname, shipping prefs, etc.)
          └─────┬─────┘
                │
          ┌─────▼─────┐
          │  items    │  GET /users/{id}/items/search + /items/{ids}:multiget
          └─────┬─────┘
       ┌────────┼─────────┐
       │        │         │
   ┌───▼──┐ ┌───▼──┐  ┌───▼────┐
   │orders│ │ques- │  │shipments│
   │      │ │tions │  │(via    │
   │      │ │      │  │ orders)│
   └───┬──┘ └──┬───┘  └────┬───┘
       │       │           │
       │   ┌───▼────┐      │
       │   │messages│      │
       │   └───┬────┘      │
       │       │           │
       └───────┼───────────┘
               │
          ┌────▼────┐
          │ claims  │  (via orders)
          └─────────┘
```

Ordering rationale:
- `accounts` first: confirms token works.
- `items` before `orders/questions`: orders and questions reference `item_id`; having items present allows FK-style integrity at write time.
- `shipments` depends on `orders` (must know shipment ids from orders).
- `messages` depends on `questions` only tangentially (same pack taxonomy) — can parallelize with orders; design chooses sequential for simpler rate-limit budget.
- `claims` last (cheap in volume, depends on orders).

### 7.2 Checkpointing

Each step writes pagination state (`scroll_id` for items, `date_from/offset` cursors for orders, `pack_id` frontier for messages) to `bootstrap_jobs.checkpoints`. On retry/resume, DAG runner reads state and resumes. Each step is idempotent (upsert by Meli id).

### 7.3 Rate limit

Bootstrap runs under the same gateway proxy. Gateway enforces a per-seller token bucket (e.g. 10 req/s). Bootstrap respects 429s with `Retry-After`.

---

## 8. Module ↔ gateway contracts

### 8.1 Inbound (webhook fan-out)

AMQP JSON envelope defined in §6.2. Consumers acknowledge only after successful idempotent write. Contracts versioned via `envelope.version` field (default 1).

### 8.2 Outbound (Meli writes/reads)

HTTP call to `/proxy/meli/<path>`. Internal JWT (iss=`module:<id>`, aud=`gateway`, exp=60s, signed by module's KMS key). Path + method matched against `module_registry.allowed_meli_scopes` (glob-style).

Example scope entries:
- `repricer`: `["PUT /items/*", "GET /items/*", "GET /items/*/prices"]`
- `publicador`: `["POST /items", "PUT /items/*", "GET /categories/*", "POST /items/validate"]`
- `autoreply`: `["POST /answers", "GET /questions/*", "GET /messages/*"]`
- `sheets`: `["GET /items/*", "GET /orders/*", "GET /shipments/*"]` (read-only)
- `fulldock`: `["GET /items/*", "GET /shipments/*", "PUT /items/*/stock_locations"]`

### 8.3 Core reads

Modules import `zeler_platform_core.repos`:

```python
from zeler_platform_core.repos import ItemsRepo, OrdersRepo

items = ItemsRepo(mongo_client).by_seller(seller_id, status="active", limit=100)
```

All repos are read-only across module boundaries. Modules write only through their own `repricer_repo` etc. Cross-module writes forbidden by convention and enforced in code review (no `core.repos` write methods exported).

---

## 9. Security model

| Concern | Control |
|---------|---------|
| Tokens at rest | AES-256-GCM envelope with GCP KMS; 90-day key rotation; DEK cache ≤ 5 min |
| Tokens in transit | TLS 1.3 between all services; VPC-internal only between gateway ↔ modules |
| Internal s2s auth | JWT signed by KMS asymmetric key (EC P-256); 60-s TTL; aud/iss claims enforced |
| Per-module scope | `module_registry.allowed_meli_scopes` — gateway blocks out-of-scope proxy calls |
| Audit | Every `/proxy/meli/*` call writes one `audit_log` doc (separate collection, TTL 365 d, append-only) |
| Secrets | Only in GCP Secret Manager; injected as env vars at container start; **no** `info_app` Mongo collection |
| Plaintext creds | Forbidden in source; CI scans with `gitleaks` on every PR |
| Rotation | Secrets rotated quarterly via Secret Manager versioned references |
| PII | Only `nickname`, `buyer_id`, basic order info; GDPR/Ley 25.326 compliance: `users` supports hard-delete cascading via a `purge` job |

### `audit_log` collection (referenced above)

| Field | Type |
|-------|------|
| `_id` | ObjectId |
| `at` | Date |
| `module_id` | string |
| `seller_id` | long |
| `method`, `path` | string |
| `status` | int |
| `duration_ms` | int |
| `trace_id` | string |

Indexes: `{ at: 1 }` TTL 365d; `{ module_id: 1, at: -1 }`; `{ seller_id: 1, at: -1 }`.

---

## 10. Cluster & DB provisioning

| Item | Decision |
|------|----------|
| Atlas project | NEW project `zeler-platform` (separate from legacy `zeler-core` project for IAM blast-radius) |
| Cluster name | `zeler-platform-prod` |
| Tier — dev | **M10** (2 GB RAM, shared) — adequate for CI/stage |
| Tier — prod | **M30** (8 GB RAM, 40 GB storage, dedicated) — accommodates item catalog + webhook_events TTL + ~50 RPS read/write mix; upgrade path to M40/M50 based on observed IOPS |
| MongoDB version | 7.0 |
| Region | **GCP us-central1** (same region as Cloud Run services; sub-ms latency) |
| Replication | 3-node replica set (default) |
| Backups | Atlas continuous cloud backup + **PITR enabled** (7-day retention) |
| Network | **Private endpoint** (PrivateLink) from GCP VPC → Atlas; NO public IP exposure; Cloud Run uses Serverless VPC Access connector |
| Auth | SCRAM-SHA-256 with per-service users (`gateway-rw`, `modules-rw`, `analytics-ro`, `bootstrap-rw`); no shared superuser |
| Schema validation | `validationLevel: "strict"`, `validationAction: "error"` on every collection; validators committed in `infra/atlas/*.json` |
| Monitoring | Atlas alerts → PagerDuty for: connection saturation > 80 %, replication lag > 10 s, disk > 75 %, slow query > 1 s |
| Indexes | Applied via `infra/atlas/indexes/` JSON executed in CI/CD on deploy |

Tier sizing justification: M30 clears the 2-vCPU serverless-aware workload (Cloud Run autoscaling will hit ~50-100 concurrent connections peak). M10 is under-provisioned for prod webhook bursts; M30 gives headroom with ≤ 30 % baseline utilization.

---

## 11. Decisions log

### D1. Monorepo over polyrepo

**Context**: 5 legacy repos + `zeler-core` = constant version skew of shared models.
**Options**: (a) keep polyrepo with `zeler_platform_core` as a published wheel; (b) single monorepo with `uv` workspaces.
**Chosen**: (b).
**Rationale**: Lockstep schema changes are frequent during greenfield. Workspace sources avoid publish+bump cycle. CI can run impacted-only builds.
**Consequences**: Larger repo; need path-based CI filters; reviewers must understand cross-package impact.

### D2. Python 3.11 across the backend; no polyglot

**Context**: Team knows Python; Next.js is the only JS surface (frontend).
**Options**: (a) Python gateway + Node modules; (b) All-Python backend.
**Chosen**: (b).
**Rationale**: Muscle memory, shared `zeler_platform_core`, hiring, uv tooling.
**Consequences**: Frontend ↔ backend boundary is hard HTTP; no shared types — mitigated by OpenAPI schema export + typed client generation.

### D3. FastAPI + Pydantic v2

**Context**: Repricer/PublicadorMeli already FastAPI. Pydantic v2 is 5–20× faster than v1.
**Chosen**: FastAPI ≥ 0.110 + Pydantic v2.
**Consequences**: Must port any remaining Pydantic v1 models (negligible — greenfield).

### D4. Envelope encryption with GCP KMS

**Context**: Meli tokens are bearer credentials; breach = full account takeover.
**Options**: (a) plaintext (reject); (b) application-side AES with key in Secret Manager; (c) envelope with KMS; (d) per-field KMS (every read hits KMS).
**Chosen**: (c).
**Rationale**: Rotations without re-encrypting historical ciphertext. Decouples key material from application. Cost-efficient vs (d). Auditable via KMS logs.
**Consequences**: All read paths depend on KMS availability; DEK cache + circuit breaker + KMS regional HA (us-central1) keep SLO intact.

### D5. RabbitMQ topic exchange, not Kafka

**Context**: Need pub/sub fan-out for webhooks.
**Options**: (a) Kafka; (b) RabbitMQ (existing); (c) GCP Pub/Sub.
**Chosen**: (b).
**Rationale**: Team runs RabbitMQ today; volume (~50 msg/s peak) nowhere near Kafka's sweet spot; Pub/Sub would be the alternative but adds vendor coupling.
**Consequences**: Operational ownership of RabbitMQ remains with team; no "managed" fallback.

### D6. Cloud Run for HTTP; VM Docker for AMQP consumers

**Context**: Cloud Run does not support always-on AMQP long polling efficiently (CPU is throttled outside requests).
**Options**: (a) all Cloud Run with "CPU always allocated"; (b) GKE; (c) Cloud Run for HTTP, VM Docker for consumers.
**Chosen**: (c).
**Rationale**: Matches existing pattern (Repricer, SheetSeller). GKE operational overhead unjustified for team size. Cloud Run "always on" is expensive at scale.
**Consequences**: Two deployment targets to automate (Terraform + gcloud); clear ownership boundaries.

### D7. `seller_id`-scoped collections, NOT per-tenant collections

**Context**: Autoreplyia/FullDock's `{nickname}_*` collections are explicit anti-pattern.
**Chosen**: ONE collection per entity; `seller_id` field always indexed first.
**Rationale**: Cross-tenant analytics, queryability, Mongo's index economy, schema validation.
**Consequences**: All queries MUST carry `seller_id` — enforced by repo layer (never exposes raw collection).

### D8. Schema validation ON from day 1

**Context**: Legacy has schema drift — no validators.
**Chosen**: `$jsonSchema` validators in `infra/atlas/*.json`, `strict`/`error`.
**Rationale**: Cheaper to enforce now than to clean drift later.
**Consequences**: Dev friction when iterating schemas → mitigated by auto-generating validators from Pydantic models in CI.

### D9. No legacy migration

**Context**: Proposal mandates greenfield, bootstrap-from-Meli.
**Chosen**: Zero ETL. OAuth re-link + bootstrap job per account.
**Rationale**: Legacy schemas (per-nickname, dual writers) would contaminate greenfield.
**Consequences**: Sellers must re-link (one-time friction); bootstrap API cost (~hours of Meli GETs per large seller) — offset by the `/internal/tokens/issue` fast path for bulk reads and Meli's multiget endpoints.

### D10. Audit log as append-only collection, 365-day TTL

**Context**: Need accountability for every Meli call.
**Chosen**: `audit_log` collection, TTL 365 d. Not external SIEM (yet).
**Rationale**: Cheap, queryable, sufficient for current compliance posture.
**Consequences**: SIEM export is a future evolution, not blocked by this design.

### D11. Single Meli OAuth application

**Context**: Legacy has 5 OAuth apps (one per product).
**Chosen**: ONE Meli OAuth app `zeler-platform`.
**Rationale**: Proposal success criterion: "exactly one webhook receiver." Token scope unified; rate-limit budget unified; operational surface reduced 5×.
**Consequences**: Sellers re-link once; loss of per-product rate-limit isolation is mitigated by gateway per-module quota layer.

### D12. APScheduler for refresh worker, not Celery beat

**Context**: One cron: token refresh every 5 min.
**Chosen**: APScheduler embedded in gateway replica (with Mongo distributed lock).
**Rationale**: No new infra dependency (Celery needs Redis/RabbitMQ broker + beat); lock makes multi-replica safe.
**Consequences**: Lose Celery's task retry infra — fine because refresh has its own retry semantics anyway.

### D13. Bounded Prometheus metrics collector for gateway metrics

**Context**: P1.17 needed gateway call/latency/rate-limit/refresh metrics exposed through `/metrics`, but raw account labels would create high-cardinality series and a full OTel metrics exporter was heavier than the current Cloud Run endpoint needs.
**Chosen**: A lightweight in-process Prometheus text collector gated by `OTEL_METRICS_ENABLED`. External Prometheus/PromQL computes p95 latency and error-rate rollups from counters and histogram buckets.
**Rationale**: Keeps the runtime dependency surface small, preserves the Prometheus scrape contract, and avoids unbounded `account_id`/seller label cardinality.
**Consequences**: Metrics are per-process/per-instance until scraped and aggregated externally, and account-level drilldown must use structured logs/traces or a future controlled sampling/allowlist design rather than default metric labels.

---

## 12. Non-goals (explicitly OUT)

- ❌ **Multi-marketplace** (Amazon, Shopify). Architecture must not preclude but no implementation here.
- ❌ **Multi-tenant SaaS commercialization** (white-label, billing per module, reseller accounts).
- ❌ **Legacy data migration**. Greenfield. Bootstrap only.
- ❌ **Feature flags for dual-write / shadow sync** — greenfield runs canonical from day 1; no `READ_TOKENS_FROM_CORE`-style flags.
- ❌ **Custom admin UI framework**. `zeler-app` (Next.js 15) is the UI; no bespoke Python admin.
- ❌ **Analytics warehouse**. `audit_log` + Mongo is sufficient; BigQuery sink is a future change.
- ❌ **On-prem / self-hosted deployment**. GCP-only.

---

## Open Questions

- [ ] Confirm Meli's published IP allowlist coverage is sufficient for webhook validation (fallback plan: shared-secret query param if Meli offers it).
- [ ] Validate M30 sizing under realistic load test (target: 1k linked accounts, 50 webhook/s peak).
- [ ] Decide policy for `audit_log` export to long-term archive (GCS + Parquet) — out of scope for v1, track as follow-up.
