# Legacy Decommission Runbook

**Status**: Non-destructive planning artifact for SDD Phase 7.  
**Change**: `zeler-platform-greenfield`  
**Safety gate**: destructive actions require explicit human approval and verified credentials/environment.

## Hard stops

- Do not archive GitHub repositories from automation.
- Do not stop/delete Cloud Run services or VMs from automation.
- Do not revoke Meli OAuth credentials from automation.
- Do not drop Mongo databases from automation.
- Do not mutate `zeler-core` SDD artifacts.

## Dry-run audit

Run the local audit before every Phase 7 review:

```bash
uv run python -m infra.decommission.audit --format markdown
uv run python -m infra.decommission.audit --format json
```

The audit is intentionally read-only. It inventories the five legacy product repos,
`zeler-core`, legacy service/database/OAuth targets, and returns `safe_to_execute=false`.

## Phase 7 approval checklist

### P7.1 — Freeze five legacy repos

Targets: `sheetsellerappindividual`, `publicadormeli`, `repricer-meli`, `Autoreplyia`, `fulldockmanager`.

Required before manual approval:

1. Phase 6 archive remains CRITICAL=0.
2. Seller communication plan has been sent and support is staffed.
3. A deprecation README has been reviewed for each repo.
4. Rollback plan is documented: unarchive repo and restore write access.

### P7.2 — Archive `zeler-core`

Required before manual approval:

1. Product repos are frozen or have dated freeze approvals.
2. `zeler-core` README deprecation/migration guide is reviewed.
3. Final tag plan (`v-final`) is approved.
4. No mutation of zeler-core SDD artifacts is needed.

### P7.3 — Stop legacy Cloud Run services + VMs

Required before manual approval:

1. Cloud Monitoring confirms zero production traffic.
2. Runtime credentials and GCP project are verified by an operator.
3. Restart commands and rollback owner are documented.
4. Grace period expiry date is recorded in the post-mortem draft.

### P7.4 — Drop legacy databases

Required before manual approval:

1. P7.1 freeze date is at least 30 days old.
2. Final Mongo/Atlas snapshot is taken and restore-tested.
3. Platform code/config has no legacy connection string usage.
4. An operator signs off that legal/support retention needs are satisfied.

### P7.5 — Revoke legacy Meli OAuth apps

Required before manual approval:

1. P7.4 is complete and logged.
2. `zeler_platform.meli_accounts` contains only `app_id="zeler-platform"`.
3. Meli developer portal access is verified.
4. Operator confirms no active webhook URL still routes to legacy services.

### P7.6 — Final post-mortem

`docs/migration-postmortem.md` starts as a draft. Publish it only after P7.1-P7.5 have real timestamps,
approvers, evidence links, and rollback notes.
