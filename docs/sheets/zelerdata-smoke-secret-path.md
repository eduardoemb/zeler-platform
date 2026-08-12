# ZelerData B1 authenticated smoke — fixed secret path

Runbook for one authenticated ZelerData smoke run through the pre-existing Secret Manager secret `zelerdata-smoke-pilot`. One authorized run adds one secret version, injects its value inline into the env-only smoke CLI, and disables and destroys that exact version afterwards. The runner never creates or deletes a secret, never mutates IAM, and never executes B1 on its own: every run is a separately authorized operator work unit.

## Quick path

1. Complete the Day-0 gate: a human admin pre-provisions `zelerdata-smoke-pilot` and binds the VM execution principal at Secret level with only the four version permissions. No project-scope `secrets.create`.
2. A maintainer reviews sanitized Cloud Audit Logs for the admin `secrets.create` and the secret-level `setIamPolicy` before authorizing B1.
3. Reset the native runtime ledger to B1 and grant separate B1 authorization for the run.
4. Run the fixed-secret smoke runner, then confirm the captured version is disabled and destroyed and its token revoked before reporting success.

## Fixed contract

| Item | Value |
|---|---|
| GCP project | `zeler-platform-dev` |
| Fixed secret | `zelerdata-smoke-pilot` (pre-existing; never created or deleted by the runner) |
| Smoke base URL | `https://sheets.zeler.ai` |
| Seller | `82453304` |
| Formula scope | `formulas:execute` |
| Broker module / scope | `sheets` / `admin:sheets` |
| Broker JWT TTL | ≤ 300 seconds |
| Extension token TTL | ≤ 3600 seconds |
| Lock + state path | `/var/run/zelerdata-smoke.active`, atomic mode-0600, guarded by a non-blocking `flock` |
| Smoke env keys | `ZELERDATA_SMOKE_BASE_URL`, `ZELERDATA_SMOKE_TOKEN`, `ZELERDATA_SMOKE_SELLER` |
| Smoke CLI | Existing env-only `authenticated_smoke.py`; never modified |

## Day-0 gate

The Day-0 gate is a human-admin prerequisite. The runner fails closed until it is satisfied and never performs it.

- [ ] Human admin creates `zelerdata-smoke-pilot` once (or confirms the pre-existing resource).
- [ ] Human admin creates a custom IAM role containing exactly four Secret Manager version permissions: `secretmanager.versions.add`, `secretmanager.versions.access`, `secretmanager.versions.disable`, and `secretmanager.versions.destroy` (the design's `versions.add/access/disable/destroy`).
- [ ] Human admin binds that role to the VM execution principal on exactly `projects/zeler-platform-dev/secrets/zelerdata-smoke-pilot` (Secret level, not project level). A time condition is optional.
- [ ] Predefined `roles/secretmanager.secretVersionManager` is the documented fallback when a custom role is unavailable; it is bound at the same Secret level.
- [ ] No project-scope grant contains `secretmanager.secrets.create`; the runner must never hold or rely on it.

The runner's gcloud usage is restricted to the four version operations (`versions add`, `versions access`, `versions disable`, `versions destroy`). It never calls `secrets create`, `secrets delete`, or `setIamPolicy`.

## Maintainer sanitized-evidence review

Before any B1 run, a maintainer reviews sanitized Cloud Audit Logs that show the admin actions from the Day-0 gate:

- [ ] Sanitized `secrets.create` entry for `zelerdata-smoke-pilot` (values and credentials removed).
- [ ] Sanitized secret-level `setIamPolicy` entry proving the binding is on the secret, not the project.
- [ ] Evidence confirms only the four version permissions, with no project-scope `secrets.create`.
- [ ] The review verdict is recorded before B1 authorization.

No local Mongo tooling is part of this review or of any B1 operation. The local assistant environment must not query or recover through production Mongo; evidence and recovery go through sanitized Cloud Audit Logs and the canonical Sheets API.

## Version-ID lifecycle — never `latest`

Every run binds one explicit version ID:

1. `versions add` receives the token only through stdin (`--data-file=-`); the runner captures the strict numeric version ID from the canonical output.
2. `versions access`, `versions disable`, and `versions destroy` all target that exact captured ID.
3. The `latest` alias, blank values, and malformed or non-ASCII IDs are rejected before any effect.

The token value exists only in stdin, in memory, and in the scrubbed smoke child environment. It never appears in argv, runner environment variables, files, or logs.

## Inline injection only

The smoke CLI consumes exactly three environment variables:

| Key | Value |
|---|---|
| `ZELERDATA_SMOKE_BASE_URL` | `https://sheets.zeler.ai` |
| `ZELERDATA_SMOKE_TOKEN` | the minted extension token |
| `ZELERDATA_SMOKE_SELLER` | `82453304` |

- The child environment is a scrubbed baseline plus exactly those three keys; inherited `ZELERDATA_SMOKE_*` and broker/JWT/token/secret values never reach the child.
- The smoke child argv is static (command path only), runs without a shell, and the smoke is invoked exactly once per run.
- The materializer, env templates, `docker-compose.yml`, and the smoke CLI are not modified.
- The CLI redacts the token and seller from every output line.

## Lock, state, and recovery contract

- Before adding a version, the runner acquires a non-blocking `flock`; a second concurrent invocation exits non-zero with `CONCURRENT_RUN_REJECTED`.
- Active state is written atomically with mode 0600 to `/var/run/zelerdata-smoke.active`. It contains only the phase, a timestamp, and the captured version ID.
- The state file is removed only after both destroy and revoke succeed.
- Recovery fails closed while active state exists: an interrupted run leaves the state behind, and the runner never claims success on partial cleanup.

## Cleanup ordering and TTL

Every exit path (success, failure, SIGTERM, SIGINT) runs the same ordered cleanup:

1. Disable the captured version.
2. Destroy the captured version.
3. Mint a fresh broker JWT (TTL ≤ 300 seconds) and revoke the extension token.
4. Remove the active state and release the lock.

TTL contract: the broker JWT is freshly minted with TTL ≤ 300 seconds; the extension token expires at most 3600 seconds after minting. Cleanup never reports success if any step fails. The destroy invocation is non-interactive (for example, the gcloud `--quiet` flag) so the cleanup path cannot stall on a confirmation prompt. SIGKILL or VM loss cannot run cleanup: recovery state is left behind and the manual recovery path below applies.

## API/audit recovery — no Mongo

When a run is interrupted beyond automatic cleanup (for example, VM loss or SIGKILL):

1. Read the captured version ID from the remaining active state.
2. Recover evidence from sanitized Cloud Audit Logs for the version operations.
3. List and revoke any matching extension-token metadata through the canonical Sheets API.

This runbook contains no Mongo command. A local assistant must not query or recover through production Mongo; recovery goes through the API surface and audit logs only.

## Authorization before any run

- The native runtime ledger is reset to B1 as an explicit operator step before any run.
- B1 authorization is granted separately from the runner and from tests.
- The runner and its tests never trigger B1 automatically; B1 execution is a separately authorized operator work unit.

## Run readiness checklist

- [ ] Day-0 gate complete and recorded.
- [ ] Maintainer sanitized-evidence review complete.
- [ ] Native ledger reset to B1 and separate B1 authorization granted.
- [ ] One explicit version ID captured; `latest` never used.
- [ ] Cleanup ordering (disable → destroy → fresh broker JWT → revoke → remove state) succeeded.

## Related artifacts

- Runner: `infra/gce/operations/zelerdata_smoke_runner.py`
- Runner tests: `tests/operations/test_zelerdata_smoke_runner.py`
- SDD change: `zelerda-b1-smoke-secret-path` (Engram planning topics)
