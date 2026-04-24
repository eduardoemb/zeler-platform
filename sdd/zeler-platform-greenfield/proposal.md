# Proposal: zeler-platform-greenfield

## 1. Intent

Build a single greenfield platform — `zeler-platform` — that owns all Meli integration as a first-class concern, and re-houses the five existing products (SheetSeller, PublicadorMeli, Repricer, Autoreplyia, FullDock) as **modules** that consume a shared **gateway**. The five legacy repos and the current `zeler-core` shadow-sync layer are decommissioned. No data migration, no backward compatibility: bootstrap from Meli.

## 2. Problem Statement (evidence from explore.md)

- **4 duplicated webhook pipelines** — SheetSeller, Repricer, Autoreplyia, FullDock each ship their own producer/consumer/RabbitMQ stack.
- **Token refresh races** — three independent 5h30m refresh workers against the same Meli client_id; only Repricer is canonical.
- **Per-nickname collections** (`{nick}_listados`, `{nick}_questions`, `{nick}_messages`) in Autoreplyia/FullDock — unscalable, unindexable, unmigratable.
- **Plaintext credentials in source** (`renovar_tokens.py`: `Genesis1:1`).
- **"SheetSeller" name leaks product branding into platform responsibility** — canonical Meli data lives behind a Google-Sheets-flavored brand.
- **No single writer to Meli** — PublicadorMeli is the only writer, orphaned; no shared write-governance.
- **zeler-core shadow-sync** is a transitional bridge pattern, not a target architecture.

## 3. Decision

### Architecture
New monorepo `zeler-platform` (the current `zeler-core` repo becomes irrelevant — archive or repurpose):

```
zeler-platform/
├── gateway/            # zeler-meli-gateway — THE single Meli boundary
│                       # OAuth, token refresh, webhook receiver, outbound proxy
├── core/               # shared domain models, canonical entities, event contracts
├── modules/            # product capabilities — consume gateway/core, never call Meli
│   ├── sheets-module/        # ex-SheetSeller (user-facing name can stay)
│   ├── publisher-module/     # ex-PublicadorMeli
│   ├── repricer-module/      # ex-Repricer (reference implementation)
│   ├── autoreply-module/     # ex-Autoreplyia
│   └── stock-module/         # ex-FullDock
└── zeler-app/          # existing Next.js shell → platform UI
```

### Naming
- Platform: **`zeler-platform`**
- Meli boundary: **`zeler-meli-gateway`**
- Ex-SheetSeller: code/package = **`sheets-module`**; marketing name "SheetSeller" may survive in UI only.

### Database
- **Brand-new MongoDB Atlas cluster** named `zeler-platform` (separate Atlas project if org permits).
- **Single database**: `zeler_platform`, multi-collection.
- **Schema validation ON from day 1** via Atlas JSON Schema.
- Connection string via Secret Manager. **No shared cluster** with legacy `zeler_core` / product DBs — clean blast radius.
- **No migration.** Bootstrap from Meli for questions/messages/items.

### Tokens
- **One** Meli OAuth app.
- **One** collection: `zeler_platform.meli_accounts`.
- **One** refresh worker inside the gateway.
- Modules never see raw tokens — they request outbound Meli calls through the gateway (proxy API).

### Webhooks
- **Single** receiver endpoint registered with Meli.
- Gateway fans out to modules via internal event bus (RabbitMQ, already in stack).

### Decommissioning
- Current `zeler-core` Python shadow-sync: decommissioned.
- 5 legacy product repos: frozen/archived, re-implemented as modules.

## 4. Scope

### In Scope
- `gateway/` service: OAuth, token refresh, webhook receiver, outbound Meli proxy, rate-limit governance.
- `core/` package: canonical domain models, event contracts, AccountResolver, sync_status.
- `modules/` scaffolding + **one reference module** (Repricer — closest to target already).
- `zeler-app` wired to the new platform.
- New Atlas cluster + `zeler_platform` DB with schema validation.
- Bootstrap-from-Meli script (items, questions, messages, orders).

### Out of Scope
- Non-Meli marketplaces (Amazon, Shopify) — gateway design must NOT preclude them, but no implementation now.
- Multi-tenant SaaS productization (billing, licensing, white-label).
- Data migration from legacy DBs.
- Implementing all 5 modules in this change — only Repricer is committed; others follow as separate changes.

## 5. Alternatives Considered

| Option | Decision | Reason |
|--------|----------|--------|
| **A** — SheetSeller becomes the platform (user's original hypothesis) | ❌ REJECTED | "SheetSeller" is a product brand (Google-Sheets add-on). Embedding platform responsibility in a product concept creates permanent conceptual coupling and naming debt. User asked to flag this explicitly. |
| **B** — Rename SheetSeller to something neutral, keep as monolith | ❌ REJECTED | Still carries transplanted DNA. OAuth/webhook/data code inside SheetSeller is Sheets-addon-flavored, not platform-flavored. Rename = lipstick. |
| **C** — New `zeler-platform` with dedicated gateway, modules consume | ✅ ACCEPTED | Clean boundaries. Gateway is the ONLY Meli client. Modules are capabilities, not integration carriers. Name decoupled from any single product. |
| **D** — Evolve `zeler-core` in place | ❌ REJECTED | User explicitly chose greenfield. Shadow-sync is a bridge, not a target. |
| **E** — Event-sourced microservices per capability | ❌ REJECTED (overkill) | Too much operational complexity for team size. Modular monorepo + event bus delivers 80% of the benefit at 20% of the cost. |

## 6. Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Team capacity to rebuild 5 products | High | Phased rollout; Repricer first as reference; other modules stand up incrementally while legacy keeps running. |
| Meli rate limits concentrated on one OAuth app | Medium | Gateway implements rate-limit governance + per-module quotas + backpressure. |
| Webhook registration: only ONE app registers per seller | N/A (feature) | This is actually an **argument FOR** the design — centralized registration is the correct end state. |
| Learning curve on new monorepo patterns | Medium | Repricer is closest to the target model; start there so the team ports existing muscle memory. |
| Bootstrap-from-Meli API cost/time for large sellers | Medium | Paginated bootstrap, resumable, rate-limit-aware; run once per seller at onboarding. |

## 7. Success Criteria

- [ ] Zero direct Meli API calls originate outside `gateway/`.
- [ ] Zero Meli tokens stored outside `zeler_platform.meli_accounts`.
- [ ] Exactly one webhook receiver endpoint registered with Meli.
- [ ] A new capability (e.g. future Shopify integration) can be added as a new gateway + module pair **without modifying existing modules**.
- [ ] Bootstrap-from-Meli runs end-to-end on an empty cluster for a test seller.
- [ ] Repricer module runs against `zeler_platform` only (no legacy DB dependency).
- [ ] Schema validation enforced on every collection at DB level.

## 8. Capabilities

> Contract for sdd-spec. Each New Capability → new spec file.

### New Capabilities
- `meli-gateway`: OAuth flow, token lifecycle, webhook receiver, outbound proxy, rate-limit governance.
- `meli-account-registry`: canonical `meli_accounts` store, per-account+app credentials, refresh ownership.
- `webhook-event-bus`: internal fan-out from gateway to modules via RabbitMQ topics/contracts.
- `platform-core-models`: canonical domain entities (items, questions, messages, orders), event contracts, AccountResolver, sync_status.
- `module-runtime`: conventions, lifecycle hooks, and SDK that all modules use to consume gateway/core.
- `repricer-module`: reference module — price-update capability built on the new stack.
- `platform-bootstrap`: bootstrap-from-Meli script (items, questions, messages, orders) for fresh-cluster onboarding.

### Modified Capabilities
- None. Greenfield — no existing specs to modify.

## 9. Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `zeler-platform/` (new repo) | New | Entire platform monorepo created from scratch. |
| `zeler-platform/gateway/` | New | Single Meli integration service. |
| `zeler-platform/core/` | New | Shared domain + event contracts. |
| `zeler-platform/modules/repricer-module/` | New | Reference module. |
| `zeler-platform/zeler-app/` | Moved | Existing Next.js shell relocated as platform UI. |
| MongoDB Atlas | New cluster | New `zeler-platform` cluster + `zeler_platform` DB with schema validation. |
| `zeler-core` (current repo) | Decommissioned | Archived or repurposed; shadow-sync retired. |
| 5 legacy product repos | Frozen | Archived; capabilities re-implemented as modules over time. |

## 10. Rollback Plan

Greenfield parallel build — legacy stays running until each module reaches parity:
- Gateway rollout is additive: new OAuth app, new webhook endpoint, new cluster. Legacy continues to receive its own webhooks.
- If gateway or a module fails, we **do not touch legacy**; legacy keeps serving its users unchanged.
- Per-module cutover is flag-controlled: sellers migrate one at a time via re-linking to the new OAuth app.
- If the whole program is aborted: archive `zeler-platform`, keep legacy. No production data lost — the new cluster has no unique data until cutover.

## 11. Dependencies

- New MongoDB Atlas cluster provisioning (new project preferred).
- New Meli OAuth application registered for the platform.
- Secret Manager entries for gateway credentials.
- RabbitMQ (already in stack) — shared or dedicated vhost for platform events.
- Node/TS + Python runtimes for monorepo tooling (stack TBD in design phase).

## 12. Next Steps

After this proposal is accepted, `sdd-spec` and `sdd-design` can run in parallel:
- **sdd-spec** writes specs for each New Capability listed above.
- **sdd-design** produces the technical design (stack choice, monorepo tooling, gateway internals, event contracts, bootstrap strategy).
