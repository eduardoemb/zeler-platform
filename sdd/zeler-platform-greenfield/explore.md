# Exploration: Zeler Platform Greenfield

**Change**: `zeler-platform-greenfield`  
**Date**: 2026-04-23  
**Status**: completed  
**Model**: anthropic/claude-sonnet-4-6  

---

## 1. Current-State Mapping (evidence from code)

### SheetSeller (`sheetsellerappindividual`)

**Product DNA**: Google Sheets add-on SaaS for MercadoLibre sellers. The seller never leaves their spreadsheet — they call `=SHEETSELLER_ORDENES(...)`, `=SHEETSELLER_VENTASYSTOCK(...)` etc. and get data directly in cells. The API is the backend; the frontend (`app.sheetseller.com`) is a subscription/account management dashboard only.

**OAuth/Token flow**:
- **Vinculación**: `vinculacion/src/app.py` — Flask app that receives Meli OAuth callback at `/auth/redirect`. Parses `user_id` from the authorization code, exchanges for token via `POST /oauth/token`, then does an **immediate refresh** of that token. Writes to both legacy `users` collection AND to `zeler_core.meli_account_apps` (via `write_token_to_core()`). Collection: `zeler_core.meli_account_apps` (canonical), legacy `users` (still written to).
- **Token refresh**: `refrescar_tokens/src/renovar_tokens.py` — reads from legacy `users.access_token.refresh_token` and writes ONLY to legacy. **Does NOT write to zeler_core.** This is a critical gap: refresh cycle is legacy-only.
- **Token reads**: `adapters/meli_credentials.py` — feature-flagged. `READ_TOKENS_FROM_CORE=true` in prod: resolves `nickname → user_id` from local `users`, then reads from `zeler_core.meli_account_apps`. Falls back to local on core miss. App_id = `"sheetseller"`.

**Direct Meli API calls**:
- `utils/meli_api.py`: `/items/{item_id}`, `/items/{item_id}/prices`, `/sites/MLM/listing_prices`, `/users/{seller_id}/shipping_options/free`
- `notificaciones/producer/src/main.py`: fetches items, orders, shipments, questions, messages, claims, items_prices from Meli API on webhook trigger
- SheetSeller makes **on-demand** live calls to Meli for shipping cost & listing price in item views — data NOT cached

**Webhook handlers**:
- `notificaciones/producer` (Flask, VM) — receives Meli webhooks, resolves access_token from `zeler_core` by user_id, fetches full resource from Meli API, enqueues to RabbitMQ
- `notificaciones/consumer` — drains queue, writes to `meli_orders`, `meli_items`, `meli_shipments`, `meli_questions`, `meli_messages` in `zeler_core`
- Topics handled: `items`, `orders_v2`, `shipments`, `questions`, `messages`, `claims`, `items_prices`, `catalog_item_competition_status`
- `router_notifications.py` in the API handles **MercadoPago** webhooks (payment, subscription_preapproval, subscription_authorized_payment) — completely separate from Meli product webhooks

**Data entities owned**:
- **Primary writer for**: `meli_orders`, `meli_items`, `meli_shipments`, `meli_questions`, `meli_messages`, `meli_claims` via webhook pipeline (in `zeler_core`)
- **Exclusive owner**: `subscriptions` (MercadoPago billing), `platform_users` (Zeler user accounts), `item_history_projection` (in `sheetseller_app`), `competition_snapshots`, `item_enrichments`, `withdrawal_records`, `return_details`
- **Reads**: all of the above + `meli_categories`

**Storage backends**:
- `zeler_core`: `meli_items`, `meli_orders`, `meli_shipments`, `meli_questions`, `meli_messages`, `meli_claims`, `meli_accounts`, `meli_account_apps`, `platform_users`, `subscriptions`, `meli_categories`, `backfill_jobs`
- `sheetseller_app`: `item_history_projection`, `competition_snapshots`, `return_details`, `withdrawal_records`, `item_enrichments`
- Legacy (still used for token fallback): `sheetsellerapp.users`
- CouchDB (GCP VM): `map_code_ml` — legacy SKU mapping

**Shared/duplicated code**: `shared_resolvers/meli_accounts.py` — AccountResolver class shared between sheetsellerapi and some notebooks. This is the only real "shared library" attempt.

---

### PublicadorMeli (`publicadormeli`)

**Product DNA**: Publish products to MercadoLibre with AI-assisted content (LLM via Perplexity). Manages MeLi catalog, categories, and GTIN validation. The core business value is reducing the friction of listing creation.

**OAuth/Token flow**:
- **Vinculación**: `backend/src/routes/meli.py` (FastAPI, NOT a separate service) — `/meli/auth` redirects to Meli OAuth, `/meli/auth/callback` exchanges code for token via `MeliService.exchange_code_for_token()`. Writes to LOCAL `meli_users` collection. **Calls `/users/me` to get nickname**. Immediately fetches shipping preferences and publication preferences.
- **Token refresh**: `backend/src/routes/scheduler.py` — `/scheduler/refresh-tokens` endpoint triggered by external scheduler. NOT a separate VM worker. Manages refresh in local `meli_users`.
- **Token reads**: `adapters/meli_credentials.py` — feature-flagged (`READ_TOKENS_FROM_CORE` in settings). Core path: resolves from `zeler_core.meli_accounts` → `zeler_core.meli_account_apps` with `app_id="publicador"` (from settings). App_id value comes from `MELI_APP_ID` env var.

**Direct Meli API calls** (via `meli_service.py`):
- `POST /oauth/token` — token exchange + immediate refresh
- `GET /users/me` — get user profile/nickname
- `GET /users/{user_id}/shipping_preferences` 
- `GET /users/{user_id}/following/search?type=brands&status=eligible`
- `GET /items/{item_id}` — fetch existing publication
- `POST /items` — CREATE new publication (THIS is the platform's core value)
- `PUT /items/{item_id}` — update publication
- `GET /sites/MLM/categories/search`
- `GET /categories/{id}`
- `GET /categories/{id}/attributes`
- `GET /catalog/products/{catalog_product_id}`
- `GET /catalog/products/search`
- Catalog suggestion handling via webhook `catalog_suggestions`

**Webhook handlers**:
- `POST /meli/notifications` — only handles `catalog_suggestions` topic. Minimal implementation.
- NO RabbitMQ pipeline. No consumer/producer architecture. Webhooks handled directly in the API.

**Data entities owned**:
- **Primary writer for**: `products` (Zeler product catalog before publishing), `meli_users` (local token store), `operators`, `account_products` (which products belong to which Meli account)
- **Reads**: `meli_users`, `meli_accounts` (core), `platform_apps` (meli app config), `categories`

**Storage backends**:
- Local `publicadormeli` DB: `products`, `operators`, `meli_users`, `account_products`, `categories`, `batch_logs`
- `zeler_core`: `meli_accounts`, `meli_account_apps` (read-only for tokens in core mode)

---

### Repricer MeLi (`repricer-meli`)

**Product DNA**: Automated repricing engine for MercadoLibre (AND Amazon via a separate codebase). Sets pricing rules per SKU, monitors competition, adjusts prices automatically. Most sophisticated architectural product — has full RabbitMQ pipeline, batch workers, and Amazon integration.

**OAuth/Token flow**:
- **Vinculación**: `vinculacion/src/app.py` — MOST ADVANCED vinculación. Reads OAuth config from ENV VARS (not DB). Writes ONLY to `zeler_core.meli_account_apps` (no legacy write at all, legacy decommissioned). Writes to `meli_accounts` AND `meli_account_apps`. App_id = `"repricer"` (hardcoded). Includes `sync_status_writer` — records OAuth linkage/success events in structured `sync_status.*` subdocument.
- **Token refresh**: `refrescar_tokens/src/renovar_tokens.py` — MOST ADVANCED refresh. Reads directly from `zeler_core.meli_account_apps` (NOT legacy). Has structured logging, heartbeat writes to `repricer_app.worker_heartbeats`, handles `invalid_grant` (marks account `disconnected`), `sync_status` updates, full RabbitMQ-free batch loop.
- **Token reads**: `adapters/meli_credentials.py` — reads ONLY from `zeler_core`, no local fallback. Uses `sync_status_reader.resolve_domain(doc, "oauth")` to check readiness. App_id = `"repricer"`.

**Direct Meli API calls**:
- Worker `subirPrecio`: `PUT /items/{item_id}` — price updates, reads current price, competes
- Worker `maximizarPrecio`: `PUT /items/{item_id}` — maximize prices within limits
- Worker `automaticPrices`: automated loop with pricing strategies
- `notificaciones/producer`: resolves token, fetches full resource from Meli on webhook
- Backend: `GET /items/{item_id}`, reads item data for reprice validation
- `GET /items/{item_id}/prices` — check current prices before repricing

**Webhook handlers**:
- `notificaciones/producer` (Flask, VM) — receives Meli webhooks, enqueues to RabbitMQ. Resolves token from `zeler_core`.
- `notificaciones/consumer` (VM) — processes queue, writes to `zeler_core.meli_items`, `repricer_app.item_pricing_state`, triggers price change logic
- Topics: `items`, `orders_v2`, `shipments`, `catalog_item_competition_status`, `items_prices`, `questions`, `messages`, `claims`

**Data entities owned**:
- **Primary writer for**: `repricer_app.item_pricing_state` (pricing rules + history), `repricer_app.reprice_reports`, `repricer_app.pricing_limits`, `repricer_app.automatic_strategies`
- **Secondary writer for**: `zeler_core.meli_items` (price sync updates post-reprice via workers)
- **Reads**: `zeler_core.meli_items`, `zeler_core.meli_account_apps`, `zeler_core.meli_accounts`

**Storage backends**:
- `repricer_app`: `item_pricing_state`, `reprice_reports`, `pricing_limits`, `automatic_strategies`, `automatic_limits`, `worker_heartbeats`, `webhook_idempotency`
- `zeler_core`: `meli_items`, `meli_accounts`, `meli_account_apps` (canonical sources)
- Amazon: `FullDock_Amaz` DB (entirely separate, via fulldockamazon repo)

---

### Autoreplyia (`Autoreplyia`)

**Product DNA**: AI auto-reply system for MercadoLibre questions and messages. Uses OpenAI + Chroma vector store. Sellers define their catalog context, AI generates replies for incoming questions.

**OAuth/Token flow**:
- **Vinculación**: `vinculacion/src/app.py` — same pattern as SheetSeller/FullDock. Exchanges code, does immediate refresh, writes to both legacy AND `zeler_core.meli_account_apps`. App_id from `APP_ID` env var (= `"autoreply"`).
- **Token refresh**: `refrescar_tokens/src/renovar_tokens.py` — reads from legacy `users.refresh_token`, writes to both legacy AND `zeler_core.meli_account_apps` (app_id = `"autoreply"`). Intermediate sophistication.
- **Token reads**: `adapters/meli_token_adapter.py` — reads ONLY from `zeler_core` (no local fallback, legacy decommissioned per comment in code). Resolves `nickname → account_id` via `meli_accounts`, then fetches from `meli_account_apps` where `app_id = "autoreply"`.

**Direct Meli API calls**:
- `notificaciones/producer/main.py`: fetches items, orders, shipments, questions, messages, claims, items_prices from Meli API on webhook
- `AnswersService` / `QuestionService`: queries local `{nickname}_questions` and `{nickname}_listados` (still legacy per-nickname collections!)
- When sending a reply: `POST https://api.mercadolibre.com/answers` — this is Autoreplyia's core value
- `read_status_sync` component: marks questions/messages as read in Meli

**Webhook handlers**:
- Full RabbitMQ pipeline: producer → RabbitMQ → consumer
- producer handles: `questions`, `messages`, `post_purchase`, `orders_v2`, `claims`, `items`, `shipments`, `items_prices`
- consumer writes to: `{nickname}_questions`, `{nickname}_messages`, `{nickname}_post_purchase` (PER-NICKNAME collections — still legacy architecture!)
- `read_status_sync` — reconciles read status with Meli API

**Data entities owned**:
- **Primary writer for**: `{nickname}_questions` (per-nickname!), `{nickname}_messages`, `{nickname}_post_purchase`, `autoreply_preferencia`, `predefined_answers`, `tokens` (user auth)
- CRITICAL: Autoreplyia's data model is STILL per-nickname, not account_id-based

**Storage backends**:
- `autoreply` DB: `{nickname}_questions`, `{nickname}_messages`, `{nickname}_post_purchase`, `autoreply_preferencia`, `predefined_answers`, `tokens`, `users`, `info_app`
- `zeler_core`: `meli_accounts`, `meli_account_apps` (for token reads)

---

### FullDockManager (`fulldockmanager`)

**Product DNA**: Fulfillment and cross-docking logistics management. Monitors stock in fulfillment centers, generates cross-dock operations, manages catalog for fulfillment-eligible items.

**OAuth/Token flow**:
- **Vinculación**: `vinculacion/src/app.py` — IDENTICAL to Autoreplyia (byte-for-byte same code). App_id from `APP_ID` env var (= `"fulldock"`).
- **Token refresh**: `refrescar_tokens/src/renovar_tokens.py` — reads from legacy `users.refresh_token`, writes to legacy ONLY. **No core write!** Most outdated of all 5 products.
- **Token reads**: `adapters/meli_credentials.py` — reads ONLY from `zeler_core` (no local fallback). App_id = `"fulldock"`.

**Direct Meli API calls**:
- `ItemsService.py` calls Meli API for item details, stock updates, fulfillment operations
- `CatalogService.py`: `GET /items/{id}/variations`, `GET /categories/{id}`
- `notificaciones/producer/main.py`: fetches full resource from Meli on webhook

**Webhook handlers**:
- Full RabbitMQ pipeline: producer → RabbitMQ → consumer
- Topics: `items`, `orders_v2`, `shipments`, `items_prices`, `catalog_item_competition_status`
- Consumer writes to `{nickname}_listados` (per-nickname — same legacy pattern as Autoreplyia)

**Data entities owned**:
- **Primary writer for**: `{nickname}_listados`, fulfillment-specific item enrichments, cross-dock operation records
- **Reads**: `zeler_core.meli_items`, `zeler_core.meli_accounts`, `zeler_core.meli_account_apps`

**Storage backends**:
- Local `fulldock` DB: `{nickname}_listados`, `users`, `info_app`
- `zeler_core`: `meli_items`, `meli_accounts`, `meli_account_apps`

---

### `zeler-core` (current repo — TO BE DISCARDED)

**Role**: Canonical shared MongoDB store + sync pipeline + token refresh microservice. NOT a product. A data platform.

**Key components**:
- `packages/sync-pipeline`: webhook ingress (FastAPI), RabbitMQ-based sync workers, backfill jobs, token refresher
- `packages/core-models`: shared Pydantic entities — `MeliItem`, `MeliOrder`, `MeliShipment`, `MeliQuestion`, `MeliMessage`, `MeliClaim`, `MeliAccount`, `MeliAccountApp`, `PlatformUser`, `BackfillJob`
- Supported webhook topics: `items`, `orders_v2`, `shipments`, `questions`, `messages`, `claims`, `post_purchase`, `items_prices`, `catalog_item_competition_status`, `users`, `categories`
- The sync pipeline is the CORRECT design: centralized webhook ingress, queue-based processing, canonical writes
- **BUT**: SheetSeller and Repricer have their OWN webhook pipelines that bypass this and write directly. There are COMPETING webhook pipelines.

### `zeler-app` (companion app)

- Minimal Next.js 15 + Prisma shell. Appears to be a nascent unified Zeler frontend (dashboard + auth pages). Not yet functional as a cross-product portal. No direct Meli integration.

---

## 2. Data Ownership Map

| Entity | Canonical Write | Read By | Physical Location | Canonical Source? |
|--------|----------------|---------|-------------------|-------------------|
| MeLi OAuth tokens (initial) | vinculacion (per product) | All products | `zeler_core.meli_account_apps` | YES (post-Phase10c) |
| MeLi OAuth tokens (refresh) | refrescar_tokens (per product) | All products | `zeler_core.meli_account_apps` (Repricer ONLY) / legacy (others) | PARTIAL — only Repricer is fully canonical |
| MeLi accounts (nickname registry) | vinculacion | All products | `zeler_core.meli_accounts` | YES |
| Items/Publications | SheetSeller notif-pipeline + Repricer consumer | SheetSeller, Repricer, FullDock | `zeler_core.meli_items` | YES but DUAL WRITERS |
| Orders | SheetSeller notif-pipeline | SheetSeller | `zeler_core.meli_orders` | YES |
| Shipments | SheetSeller notif-pipeline | SheetSeller | `zeler_core.meli_shipments` | YES |
| Questions | SheetSeller notif-pipeline + Autoreplyia consumer | SheetSeller, Autoreplyia | `zeler_core.meli_questions` (SheetSeller) / `{nick}_questions` (Autoreplyia) | DUPLICATED — two different stores |
| Messages | SheetSeller notif-pipeline + Autoreplyia consumer | SheetSeller, Autoreplyia | `zeler_core.meli_messages` (SheetSeller) / `{nick}_messages` (Autoreplyia) | DUPLICATED |
| Claims/Post-purchase | SheetSeller notif-pipeline + Autoreplyia consumer | SheetSeller, Autoreplyia | `zeler_core.meli_claims` (SheetSeller) / `{nick}_post_purchase` (Autoreplyia) | DUPLICATED |
| Pricing rules | Repricer backend | Repricer workers | `repricer_app.item_pricing_state` | YES (Repricer owns) |
| Reprice history | Repricer workers | Repricer dashboard | `repricer_app.reprice_reports` | YES |
| Product catalog (pre-publish) | PublicadorMeli | PublicadorMeli | `publicadormeli.products` | YES (PublicadorMeli owns) |
| Fulfillment items | FullDock consumer | FullDock | `{nick}_listados` (local) | NO — per-nickname legacy |
| Platform users (auth) | SheetSeller (canonical) | SheetSeller | `zeler_core.platform_users` | YES |
| Subscriptions (billing) | SheetSeller | SheetSeller | `zeler_core.subscriptions` | YES |
| Item history projection | SheetSeller | SheetSeller | `sheetseller_app.item_history_projection` | YES (SheetSeller-specific) |
| Competition snapshots | SheetSeller | SheetSeller, Repricer | `sheetseller_app.competition_snapshots` | Partial |
| Categories | SheetSeller (`categorias/` script), PublicadorMeli | All | `zeler_core.meli_categories` | YES |
| Autoreply preferences | Autoreplyia | Autoreplyia | `autoreply.autoreply_preferencia` | YES (Autoreplyia owns) |
| Pricing strategies | Repricer | Repricer workers | `repricer_app.automatic_strategies` | YES |

---

## 3. Duplications & Coupling

### Copy-pasted Meli client code (confirmed by direct comparison)

**Vinculación files — near-identical across 5 products**:
- `fulldockmanager/vinculacion/src/app.py` and `Autoreplyia/vinculacion/src/app.py` are **byte-for-byte identical** (same comments, same structure, only `APP_ID` env var differs)
- `sheetsellerappindividual/vinculacion/src/app.py` is a slightly older version (missing `CORE_MONGODB_URL` integration in the refresh flow)
- `repricer-meli/vinculacion/src/app.py` is the most evolved (reads OAuth config from env, no legacy write, full sync_status_writer)
- `publicadormeli` handles OAuth inline in the FastAPI backend (different pattern — no standalone service)

**Token refresh files — structurally identical**:
- `sheetsellerappindividual`, `fulldockmanager`, `Autoreplyia`, `repricer-meli` all have `refrescar_tokens/src/renovar_tokens.py` with `class TokenManager` pattern, `refresh_tokens()`, `renew_tokens()` methods
- FullDock refresh is the oldest (writes only to legacy, no core write)
- SheetSeller refresh is also legacy-only (no core write)
- Autoreplyia refresh writes to BOTH legacy and core
- Repricer refresh is the canonical reference: reads FROM core, writes TO core, no legacy

**Webhook producer pattern**:
- SheetSeller, Autoreplyia, FullDock, Repricer all have `notificaciones/producer/src/main.py` with identical structure: Flask app, gets `user_id` from notification, resolves token, fetches resource from Meli API, publishes to RabbitMQ
- The resource-fetching logic (fetch item, fetch order, fetch shipment, etc.) is copy-pasted across all 4 producers

**`meli_credentials.py` pattern**:
- SheetSeller, PublicadorMeli, Repricer, FullDock each have their own `adapters/meli_credentials.py`
- All 4 implement the same logic: resolve nickname → account_id → fetch from `zeler_core.meli_account_apps` filtered by `app_id`
- The only difference is the `app_id` value

**Estimated % of each product that is "Meli integration plumbing" vs "actual product logic"**:

| Product | Integration Plumbing | Actual Product Logic |
|---------|---------------------|---------------------|
| SheetSeller | ~35% (vinculacion, refrescar, notificaciones pipeline, credentials adapter) | ~65% (Google Sheets queries, subscription billing, analytics) |
| PublicadorMeli | ~45% (OAuth inline, categories sync, Meli publish API calls) | ~55% (product catalog, LLM content generation, GTIN validation) |
| Repricer MeLi | ~50% (vinculacion, refrescar, notificaciones pipeline, credentials, price PUT calls) | ~50% (pricing rules, competition logic, Amazon integration) |
| Autoreplyia | ~40% (vinculacion, refrescar, notificaciones pipeline, read_status_sync) | ~60% (OpenAI integration, Chroma vector store, predefined answers) |
| FullDock | ~45% (vinculacion, refrescar, notificaciones pipeline) | ~55% (cross-dock logic, fulfillment monitoring, catalog) |

**Shared secrets scattered**:
- Each product has its own `MELI_CLIENT_ID`, `MELI_CLIENT_SECRET`, `MELI_REDIRECT_URI` (or reads from `info_app` collection in DB)
- SheetSeller has an `API_KEY_MP` (MercadoPago) only it needs
- All share `CORE_MONGODB_URL` pointing to `zeler_core`
- Credentials scattered across: Cloud Run env vars (5 products × 3-5 secrets = ~15-25 secrets) + VM `.env` files + DB (`info_app` collections in SheetSeller legacy)

---

## 4. Risk Assessment of Current State

### TOKEN REFRESH RACES (CRITICAL 🔴)

This is the most dangerous current-state problem. For a given MeLi seller account linked to multiple products:

- **SheetSeller `refrescar_tokens`** refreshes every 5h30m from legacy `users.access_token.refresh_token`
- **Autoreplyia `refrescar_tokens`** refreshes every 5h30m from legacy `users.refresh_token` for the SAME physical account
- **FullDock `refrescar_tokens`** refreshes every 5h30m from legacy `users.refresh_token` for the SAME account
- **Repricer `refrescar_tokens`** refreshes every 5h30m from `zeler_core.meli_account_apps` (per `app_id=repricer` — SEPARATE token, separate `meli_account_app` document)

**The race condition**: Meli tokens are PER-APPLICATION. Each app_id has its own token. When SheetSeller, Autoreplyia, and FullDock all hold separate access tokens for the same seller's Meli account, EACH refreshes independently. The Meli OAuth spec says: when you refresh a token, the old access_token is invalidated. If SheetSeller refreshes first, the token Autoreplyia is currently using for a webhook payload fetch is now INVALID. This creates:
1. HTTP 401 mid-operation
2. Silent failures when the refresh race is lost
3. The `invalid_grant` handling (Repricer has this; others don't) is absent in SheetSeller and FullDock

Actually: since Meli assigns tokens per `client_id` (per app), if ALL products use the SAME `client_id` (same Meli app), then refreshing in one service invalidates the token in all others. **If they use different `client_id`s, they're fully independent.** The code shows each has its own `info_app` collection with `client_id` — but multiple products may share the SAME Meli application. This needs validation but the risk is real.

### RATE-LIMIT RISK (HIGH 🟠)

- 5 products independently hitting Meli API
- Webhook events can trigger simultaneous fetches across all 5 producers for the same seller
- No shared rate-limit tracker
- Meli rate limits are per `client_id` — if products share app credentials, they share rate limit budget

### DATA DRIFT (HIGH 🟠)

- Questions live in TWO places: `zeler_core.meli_questions` (SheetSeller) and `{nick}_questions` (Autoreplyia)
- Messages live in TWO places: `zeler_core.meli_messages` (SheetSeller) and `{nick}_messages` (Autoreplyia)
- Items are written by BOTH SheetSeller's consumer AND Repricer's consumer — different field sets, potential overwrites
- Autoreplyia consumer writes to per-nickname collections; SheetSeller consumer writes to canonical `zeler_core.meli_*` — they're not the same data

### OPERATIONAL BLAST RADIUS (HIGH 🟠)

- If `zeler_core.meli_account_apps` is unavailable, ALL products lose token read access (post-Phase10c)
- If any one vinculacion service has a bug during linking, it may store a bad token in core that affects all products reading it
- No central observability: 5 products have 5 separate Cloud Run services + ~20 VM Docker containers. No unified alerting.

### SECURITY RISK (CRITICAL 🔴)

- `alertasDocker@outlook.es` / password `"Genesis1:1"` hardcoded in SheetSeller's `renovar_tokens.py` (plaintext credentials in source code)
- Token material flows through 5 different services and is stored in potentially 10+ locations simultaneously (5 legacy + 5 per-app core records)
- SheetSeller has MercadoPago API key hardcoded as `API_KEY_MP` — if rotated, all services using this must be updated

---

## 5. Hypothesis Evaluation: "SheetSeller as the Sole Meli Integration Boundary"

### Evidence FOR (from code)

1. **SheetSeller already owns the most canonical Meli data**: `meli_orders`, `meli_shipments`, `meli_messages`, `meli_claims` are written EXCLUSIVELY by SheetSeller's webhook pipeline. No other product consumes these for their own data needs.

2. **SheetSeller has the most complete data model**: Its `core-models` package defines `MeliItem`, `MeliOrder`, `MeliShipment`, `MeliQuestion`, `MeliMessage`, `MeliClaim` — the most complete schema set. It's the de-facto data schema authority.

3. **SheetSeller already has a working webhook ingress + sync pipeline** (`notificaciones/producer` → RabbitMQ → `consumer`) that normalizes Meli data into canonical collections. This is the architecture that SHOULD be the platform's ingestion layer.

4. **SheetSeller `zeler-core` package (`sync-pipeline`) already looks like a platform service**: `webhook_ingress.py` in `zeler-core` is a standalone FastAPI app that receives Meli webhooks, resolves accounts from ANY app, resolves auth from `meli_account_apps`, and routes to queues. This is NOT product-specific — it's designed to be a shared ingestion service.

5. **SheetSeller already writes to the canonical store that ALL other products read from**: `zeler_core` is the shared data layer that Repricer, FullDock, and Autoreplyia all already depend on for token reads.

6. **SheetSeller manages platform-level entities**: `platform_users` (all operator accounts), `subscriptions` (billing for all products eventually), `meli_accounts` (all linked accounts, not just SheetSeller users).

### Evidence AGAINST (from code)

1. **SheetSeller is deeply coupled to its Sheets product use case**. `router_ordenes.py` has 1763 lines of Google Sheets–specific query logic. The addon has 39 custom functions with `SHEETSELLER_*` prefix. This is not a platform — it's a Sheets data feed service.

2. **SheetSeller has no publish/write capability to Meli**. SheetSeller's Meli calls are READ-ONLY (GET `/items`, GET `/orders`, GET prices, GET shipping cost). It cannot CREATE or UPDATE publications. PublicadorMeli and Repricer are the write-capable products.

3. **SheetSeller's `refrescar_tokens` is OUTDATED and legacy-only**. It does NOT write to `zeler_core.meli_account_apps` on refresh. If SheetSeller becomes the "only token holder," its token refresh pipeline would immediately be a single point of failure — and the most primitive one at that.

4. **SheetSeller uses CouchDB for `map_code_ml` SKU mapping**. This is a product-specific dependency that has no place in a platform core.

5. **SheetSeller's `sheetseller_app` database** (`item_history_projection`, `competition_snapshots`) is product-specific state that should NOT be part of a platform layer.

6. **Naming is brutally problematic**: calling the Meli integration platform "SheetSeller" permanently couples "spreadsheet UI for Sheets add-on" to "Meli API gateway." These are ORTHOGONAL concerns. If the platform is built on SheetSeller, every new product team will see "SheetSeller" as the dependency, which is confusing and wrong.

### Naming/Branding Coupling

**This is the strongest argument against the hypothesis as-stated.** "SheetSeller" is a PRODUCT brand tied to the Google Sheets use case. "Sheet" refers to spreadsheets, not a platform concept. If other products (Repricer, Autoreplyia, FullDock, PublicadorMeli) are told "you depend on SheetSeller," the mental model breaks:
- "Why does my repricing engine depend on a Google Sheets tool?"
- Developers will incorrectly assume SheetSeller-specific code is safe to modify
- The product roadmap for SheetSeller (Sheets features, subscription billing) will conflict with platform stability requirements

The hypothesis is technically partially valid but architecturally unsound as stated.

---

## 6. Alternative Framings (with tradeoffs)

### Option A: SheetSeller becomes the platform core (rename or absorb)

**Approach**: Extract the webhook pipeline, `zeler_core` schema, account management, and token store out of SheetSeller into a "platform layer." SheetSeller the product becomes just another module consuming it. The "platform" is renamed (e.g., `zeler-platform` or `zeler-meli-core`).

**Pros**:
- SheetSeller already has the most complete implementation
- Minimal net-new code
- Proven in production (notificaciones pipeline works)

**Cons**:
- SheetSeller's webhook pipeline has SheetSeller-specific logic (MercadoPago billing webhooks, `sheetseller_app` writes) tangled in
- `refrescar_tokens` must be rebuilt to be canonical (it currently lags Repricer by 2 generations)
- Organizational confusion: SheetSeller team owns platform stability
- The Sheets-specific auth (JWT 364-day addon tokens, `platform_users` for Sheets operators) leaks into platform API contracts

**Effort**: Medium (disentangle product from platform logic)

---

### Option B: Extract a dedicated "Meli Integration Platform Service" independent of SheetSeller

**Approach**: New standalone service `zeler-meli-gateway` (or `zeler-meli-hub`) that is the ONLY MercadoLibre integration point. Owns:
- Single Meli OAuth application (one `client_id`)
- Single webhook receiver for ALL topics
- Single token store (`meli_account_apps`)
- Single token refresh cycle
- Publishes events to queues consumed by product modules

Products become consumers of events (orders received, items updated, questions asked) instead of direct Meli integrators.

**Pros**:
- Clean separation of concerns
- Single rate-limit budget
- Eliminates token race conditions at the architectural level
- Extensible: new products just subscribe to events
- Naming is clean: "Meli Gateway" is unambiguous

**Cons**:
- Products that WRITE to Meli (PublicadorMeli: publish items; Repricer: change prices) still need outbound Meli API calls — they can't be fully mediated without major latency
- Additional network hop for every Meli read
- Requires defining clean event contracts (what does an "item updated" event look like for ALL consumers?)
- PublicadorMeli's publish flow is synchronous (user waits for Meli API response) — a gateway adds complexity

**Effort**: High (new service, event contracts, all products must migrate)

---

### Option C: New greenfield `zeler-platform` + `zeler-meli-gateway` service, SheetSeller becomes just another module (RECOMMENDED)

**Approach**: Build a new platform from scratch with clear bounded contexts:

```
zeler-platform/
├── gateway/           # Meli OAuth + token management + webhook ingress
│   ├── auth/          # OAuth flows, token store, refresh service
│   └── webhooks/      # Webhook receiver, event routing, queue publisher
├── data-sync/         # Canonical Meli data sync (items, orders, shipments, etc.)
├── modules/
│   ├── sheets/        # SheetSeller product (Google Sheets add-on backend)
│   ├── publisher/     # PublicadorMeli product
│   ├── repricer/      # Repricer product
│   ├── autoreply/     # Autoreplyia product
│   └── fulldock/      # FullDock product
└── platform/
    ├── users/         # Platform user management
    ├── billing/       # Subscription management
    └── config/        # App/tenant configuration
```

The gateway is the ONLY service with Meli OAuth tokens. Products get tokens via internal service calls (not direct DB access). Products receive Meli events via queue subscriptions. Products that need to WRITE to Meli (publish item, change price) call the gateway's outbound API which proxies the Meli call with the correct token.

**Pros**:
- Clean slate, no legacy debt carried over as code (knowledge carried over as design)
- Bounded contexts are clear: each module has its own schema and doesn't touch others'
- Single token lifecycle (no race conditions by construction)
- SheetSeller brand stays as a product, not a platform concept
- Rate-limit managed centrally
- Extensible for future marketplace integrations (Amazon already in Repricer — could have `zeler-amazon-gateway`)

**Cons**:
- Highest initial effort (greenfield implementation)
- Requires clean event schema design before coding
- Products that write to Meli (Repricer price changes, PublicadorMeli publish) need gateway outbound API — adds latency (50-200ms per call depending on infra)
- Must solve: how does Repricer's price change loop (potentially 1000s of calls/hour) work through a gateway without becoming a bottleneck?

**Effort**: High (but this is explicitly green-field and user has confirmed this is acceptable)

---

## 7. Clean-Slate Opportunities

### Entities that MUST be re-bootstrapped from Meli

- **`meli_items`**: Meli is source of truth for all item data. Must backfill from `GET /users/{id}/items/search` + `GET /items/{ids}` bulk.
- **`meli_orders`**: Must fetch from `GET /orders/search` filtered by date/seller.
- **`meli_shipments`**: Must fetch from orders → shipment_id references.
- **`meli_questions`**: Must fetch from `GET /questions/search`.
- **`meli_messages`**: Must fetch from `GET /messages/packs`.
- **`meli_accounts`**: Must re-link from OAuth flow (users must re-authorize).
- **`meli_categories`**: Must fetch from `GET /sites/MLM/categories/`.

### Configurations worth redesigning from scratch

- **OAuth application registration**: Instead of 5 different Meli app registrations (each with own `client_id`), ONE platform Meli app with appropriate scopes for all product needs.
- **Token model**: Single token per `(account_id, platform_app_id)` — not per product. Products request tokens via internal API, never store them directly.
- **Webhook subscriptions**: Single webhook endpoint, ALL topics, ALL seller accounts — routed internally.
- **User/tenant model**: Platform user (operator) with permissions per module, per Meli account. Not 5 separate user tables.
- **Subscription/billing**: Single billing system (currently only SheetSeller has this — Repricer, Autoreplyia, FullDock have no billing).
- **Rate limit budget**: Managed centrally per seller account, across all product operations.

### Concepts that are PURE DEBT — must NOT carry over

1. **Per-nickname collection naming** (`{nick}_listados`, `{nick}_questions`, `{nick}_messages`): Unqueryable cross-tenant, unindexable at scale, violates every schema design principle.
2. **`info_app` MongoDB collection for OAuth credentials**: Storing `client_id`/`client_secret` in the database is insane. Use env vars or secrets manager.
3. **364-day JWT tokens for Sheets addon**: Security anti-pattern. Must redesign with short-lived tokens + refresh.
4. **CouchDB for `map_code_ml`**: Single VM, no replication, no managed service. Dead-end.
5. **Dual-write to legacy + core**: The `write_token_to_core` + legacy write pattern exists because the migration was incremental. Greenfield starts canonical.
6. **`sheetseller_app` as a separate MongoDB database**: The product-specific state should live in the module's own schema within the platform DB, not a separate cluster endpoint.
7. **Plaintext email credentials in source code** (`Genesis1:1`): Eliminate entirely.
8. **Feature flags `READ_TOKENS_FROM_CORE`**: The greenfield always reads from core. No flags.
9. **`sync_status.*` complexity**: The dual-write sync_status was a migration artifact. Greenfield has a single source of truth; no need for sync status tracking.

### Concepts WORTH preserving (as ideas, not code)

1. **RabbitMQ webhook pipeline architecture** (Repricer/SheetSeller's best pattern): receive webhook → enqueue → async process → write canonical. This is the right design.
2. **`zeler_core` canonical collection schema** (from `packages/core-models`): The entity models (`MeliItem`, `MeliOrder`, etc.) are well-designed — reuse them as the schema spec.
3. **`meli_account_apps` concept**: Per-(account, app) token storage with status + sync tracking is the right model.
4. **`sync_status` domain model** from Repricer: tracking domain health (oauth, linkage, items_backfill, etc.) per account is excellent for observability.
5. **`AccountResolver` pattern** (SheetSeller's `shared_resolvers`): resolve nickname → account_id → token is a good service contract.
6. **Backfill job framework** (`BackfillJob` entity in core-models): queue-based, tracked jobs for initial data ingestion.
7. **Per-module data isolation**: Repricer's `repricer_app` DB (separate from `zeler_core`) for product-specific operational data. Each module should have its own schema.
8. **Structured logging + heartbeat pattern** (Repricer's hardening): worker observability with `worker_run_start/end` events, heartbeat collection, kill-switch flags.

---

## 8. Open Questions & Inferences

### Q1: Do all 5 products share the SAME Meli OAuth application (`client_id`)?

**Unknown**: Cannot confirm from code (each reads from env var or `info_app` DB). **Inference**: They likely DON'T share the same `client_id`. Each was built independently and has its own Meli Developer Application. This means tokens are NOT interchangeable — each app gets its own token per seller. This actually REDUCES the race condition risk for refreshes (each product's token is independent). But it means rate limits are also independent (each app gets Meli's per-app rate limit budget). Verification needed by checking Cloud Run env vars or `info_app` docs.

**Decision inference**: For the greenfield, use ONE platform `client_id`. All tokens flow through the single gateway. Rate limits are centrally managed.

### Q2: Do sellers currently need to link their Meli account SEPARATELY to each product?

**Inference**: YES, based on the architecture. Each product has its own `vinculacion` service with its own OAuth callback URL. If a seller uses SheetSeller + Repricer + Autoreplyia, they go through 3 separate OAuth flows. This is terrible UX and is a strong argument FOR the platform hypothesis.

**Decision inference**: The greenfield platform must implement ONE OAuth flow per seller account. The seller links once, chooses which modules to enable.

### Q3: Will PublicadorMeli's publish flow work through a gateway?

**Inference**: The publish flow in PublicadorMeli is SYNCHRONOUS — the user clicks "Publish" and waits for Meli's response with the new `item_id`. A gateway can proxy this with acceptable latency (~50-100ms overhead). The answer is YES, but the gateway must support synchronous Meli API proxy (not just event routing).

### Q4: Can Repricer's high-frequency price change loop work through a gateway?

**Inference**: Repricer's workers (`subirPrecio`, `maximizarPrecio`, `automaticPrices`) can execute 100s-1000s of price changes per hour. A synchronous HTTP gateway per-call would be a bottleneck. **Solution**: The gateway should issue tokens to trusted internal services (Repricer workers) for a time-limited window, allowing direct Meli calls without per-call proxy. Or: workers call the gateway to GET a token, then call Meli directly. The token is cached and valid for ~6 hours. This preserves centralized token management while avoiding per-call overhead.

### Q5: Does SheetSeller have any Meli WRITE operations beyond token exchange?

**Inference from code**: NO — SheetSeller's Meli calls in `utils/meli_api.py` are all GET (read-only). The MercadoPago operations are for billing (subscriptions), not publishing. SheetSeller is a **pure read platform** for Meli data. This reinforces: SheetSeller cannot be a Meli gateway because it has no write API experience.

### Q6: What triggers the `categorias/` component in SheetSeller?

**Inference**: Based on the directory structure (`sheetsellerappindividual/categorias/`), this is a standalone script or scheduled job that syncs Meli categories into `zeler_core.meli_categories`. PublicadorMeli also has category syncing logic. In the greenfield, this should be a single platform-level category sync job.

---

## Executive Summary

1. **All 5 products ARE already converging on `zeler_core` as the shared data store** — this is happening organically. The greenfield formalizes and completes this convergence.

2. **Token storage IS already centralized** in `zeler_core.meli_account_apps` post-Phase10c. What's NOT centralized is token REFRESH — only Repricer refreshes from core; others still refresh from legacy.

3. **The webhook pipeline architecture is SOUND but duplicated 4x** — SheetSeller, Repricer, Autoreplyia, and FullDock each have their own producer/consumer/RabbitMQ stack. This is the dominant architectural debt.

4. **SheetSeller owns the most canonical Meli data** (orders, shipments, messages, claims) and has the most mature `zeler_core` schema — but as a PRODUCT, not a platform. Its value is in the design, not the brand.

5. **The hypothesis "SheetSeller as sole integration boundary" is partially correct but architecturally wrong in naming** — the right answer is a new `zeler-meli-gateway` that extracts SheetSeller's best capabilities (webhook pipeline, canonical schema, token store) into a neutral service.

6. **Autoreplyia and FullDock still use per-nickname collection naming** (`{nick}_questions`, `{nick}_listados`) — this is the most severe data model anti-pattern in the system. Cannot scale.

7. **Token refresh races are a latent risk**: 3 products (SheetSeller, Autoreplyia, FullDock) refresh from separate legacy stores. If they share a Meli `client_id`, this IS an active bug. If they don't, it's deferred debt.

8. **PublicadorMeli is an outlier**: no separate webhook pipeline, OAuth inline in FastAPI (not a standalone service), LLM integration, GCS for images — most different product in the family. Its publish flow (CREATE item) is the only net-new WRITE operation to Meli in the entire system.

9. **Repricer's architecture is the most mature reference**: fully canonical token management (env vars, not DB), reads from core only, handles `invalid_grant`, structured logging, heartbeat observability. Its patterns should be the **template for the greenfield platform**.

10. **`zeler-core`'s `sync-pipeline` package is the seed of the right platform design**: centralized webhook ingress, queue-based processing, canonical models. This should be the START of the greenfield `zeler-meli-gateway` design.

11. **One Meli app registration per product is the dominant waste**: 5 OAuth apps, 5 redirect URIs, 5 rate-limit budgets, 5 webhook subscriptions. Consolidating to ONE cuts operational complexity by 5x.

12. **The greenfield should be: `zeler-platform` monorepo with `gateway/`, `data-sync/`, and `modules/` (one per product)**. SheetSeller, Repricer, Autoreplyia, FullDock, PublicadorMeli become modules that share the gateway and data-sync layers.

13. **Naming decision: DO NOT call the platform "SheetSeller"**. Use `zeler-meli-hub` or `zeler-gateway` for the integration layer. SheetSeller is a MODULE in the platform, not the platform itself.

14. **`zeler-app` exists as a nascent unified frontend shell** — it should become the platform's unified UI, with product-specific sections per module.

15. **Data bootstrapping strategy**: OAuth re-linking is mandatory (all sellers must re-link once). Meli data (items, orders, etc.) can be backfilled from Meli API directly — no need to migrate from old collections.

---

## Affected Areas (for next phases)

- `zeler-core/packages/core-models` → extract as `@zeler/core-models` package, use as schema reference
- `zeler-core/packages/sync-pipeline` → architectural reference for `zeler-meli-gateway` webhook ingress
- `repricer-meli/vinculacion/src/app.py` → reference implementation for OAuth flow
- `repricer-meli/refrescar_tokens/src/renovar_tokens.py` → reference implementation for token refresh
- `repricer-meli/backend/app/adapters/meli_credentials.py` → reference for token reads
- All 5 `notificaciones/producer/` → consolidate into single platform webhook producer
- All 5 `vinculacion/` → consolidate into single platform OAuth service

---

## Risks

| Risk | Severity | Description |
|------|----------|-------------|
| Token refresh races | 🔴 CRITICAL | If products share Meli client_id, concurrent refreshes create 401 cascades. Verify client_id sharing before any deployment. |
| Plaintext credentials in SheetSeller source | 🔴 CRITICAL | `Genesis1:1` email password in `renovar_tokens.py`. Rotate immediately in any migration. |
| Autoreplyia data model regression | 🟠 HIGH | Per-nickname collections are unmigratable at scale without backfill. Must re-ingest from Meli API. |
| PublicadorMeli OAuth inline | 🟠 HIGH | No standalone vinculacion service; token management tangled with API logic. Separation required. |
| FullDock refresh not writing to core | 🟡 MEDIUM | FullDock's refrescar_tokens only writes to legacy. Post-greenfield, this would leave core stale. Already irrelevant if greenfield replaces it. |
| Questions/messages duplication | 🟡 MEDIUM | Two stores for same entity (zeler_core vs per-nickname). Greenfield must pick ONE and not carry the other. |
| Missing Meli write capability in SheetSeller | 🟡 MEDIUM | If SheetSeller is chosen as platform core, it has no PUT/POST to Meli. Must add or import from Repricer/PublicadorMeli. |

---

## Recommendation

**Proceed with Option C**: New greenfield `zeler-platform` monorepo.

**Immediate next phase**: `sdd-propose` — draft the platform proposal with:
1. Bounded context map (gateway, data-sync, modules)
2. Single Meli app registration strategy
3. Event schema contracts (what does each module receive?)
4. Token distribution model (how do modules get tokens for outbound calls?)
5. Module priority order (which to migrate/build first?)

**Ready for Proposal**: YES.

---

## References

- `sheetsellerappindividual/sheetsellerapi/src/` — SheetSeller backend
- `sheetsellerappindividual/vinculacion/src/app.py` — SheetSeller OAuth
- `sheetsellerappindividual/refrescar_tokens/src/renovar_tokens.py` — SheetSeller token refresh (legacy-only)
- `sheetsellerappindividual/notificaciones/producer/src/main.py` — SheetSeller webhook producer
- `publicadormeli/backend/src/services/meli_service.py` — PublicadorMeli Meli API calls
- `publicadormeli/backend/src/adapters/meli_credentials.py` — PublicadorMeli token reads
- `repricer-meli/vinculacion/src/app.py` — Repricer OAuth (canonical reference)
- `repricer-meli/refrescar_tokens/src/renovar_tokens.py` — Repricer token refresh (canonical reference)
- `repricer-meli/backend/app/adapters/meli_credentials.py` — Repricer token reads (canonical reference)
- `Autoreplyia/vinculacion/src/app.py` — Autoreplyia OAuth (≈identical to FullDock)
- `Autoreplyia/notificaciones/producer/src/main.py` — Autoreplyia webhook producer
- `fulldockmanager/vinculacion/src/app.py` — FullDock OAuth (≈identical to Autoreplyia)
- `fulldockmanager/refrescar_tokens/src/renovar_tokens.py` — FullDock refresh (legacy-only, most outdated)
- `zeler-core/packages/core-models/src/zeler_core_models/entities.py` — canonical schema reference
- `zeler-core/packages/sync-pipeline/src/zeler_sync_pipeline/webhook_ingress.py` — platform webhook seed
- `zeler-core/packages/sync-pipeline/src/zeler_sync_pipeline/routing.py` — Meli topic routing
- Obsidian: `sheetseller-docs/02 - Architecture/System Overview.md`
- Obsidian: `repricer-meli-docs/02 - Architecture/System Overview.md`
- Obsidian: `Autoreplyia/02 - Architecture/Arquitectura General.md`
- Obsidian: `publicadormeli/02 - Architecture/Arquitectura General.md`
