# ZelerData Marketplace publication runbook

ZelerData is prepared as a public Google Sheets Editor add-on in repo, but publication remains a manual operator process. This runbook gives reviewers and operators a checklist without storing credentials, OAuth codes, tokens, cookies, or raw production evidence.

## Quick path

1. Verify source readiness in `modules/sheets/apps_script/sheetseller/`.
2. Complete the manual Google Cloud, OAuth, Apps Script, and Marketplace SDK steps below.
3. Record only placeholders and sanitized evidence in repo or review artifacts.

Manual-only steps are outside repo implementation. Do not automate them from this repository.

## Manual publication checklist

| Step | Owner | Pass/Fail | Sanitized evidence |
|---|---|---|---|
| Google Cloud project linkage | Authorized operator |  | `<google-cloud-project-id>` linked to Apps Script project. |
| OAuth consent screen | Authorized operator |  | Consent configured with `<support-url>` and `<privacy-policy-url>`. |
| Apps Script immutable version | Authorized operator |  | `<apps-script-version>` created from reviewed source. |
| Marketplace SDK listing | Authorized operator |  | `<marketplace-listing-id>` configured for Google Sheets. |
| Listing assets | Authorized operator |  | Icons/screenshots uploaded with no token or account data. |
| Review submission | Authorized operator |  | Submitted version and listing IDs recorded as placeholders. |
| Post-approval smoke tests | Authorized operator |  | Approved install context tested with sanitized formula screenshots. |

## Scope matrix

| Manifest scope | OAuth/Marketplace purpose | User-facing explanation |
|---|---|---|
| `https://www.googleapis.com/auth/script.container.ui` | Editor add-on UI | Show the ZelerData menu and settings sidebar. |
| `https://www.googleapis.com/auth/script.external_request` | Formula API access | Call the ZelerData Formula API. |
| `https://www.googleapis.com/auth/spreadsheets.currentonly` | Current spreadsheet formulas | Read and write only the current spreadsheet. |

No undocumented scopes should appear in OAuth consent or the Marketplace SDK listing.

## Production readiness checklist

| Prerequisite | Pass/Fail | Sanitized evidence |
|---|---|---|
| Official Formula API URL |  | Public add-on defaults to the reviewed production endpoint; record as `<formula-api-url>`. |
| Extension-token flow |  | Token issued from zeler-app `/sheets/config`; record only `<token-issued-at>` and never the token. |
| Audit and rate-limit behavior |  | Formula calls produce non-secret audit/rate-limit evidence. |
| Support escalation |  | Support escalation path documented with `<support-url>`. |
| Privacy policy URL |  | Marketplace listing references `<privacy-policy-url>`. |
| Support URL |  | Marketplace listing references `<support-url>`. |
| Immutable submitted version |  | `<apps-script-version>` matches the reviewed repository source. |
| Approved-context smoke evidence |  | Screenshots/logs redact cuenta, IDs, URLs, tokens, and account data. |

## Review evidence rules

- Use placeholders such as `<apps-script-version>`, `<marketplace-listing-id>`, `<support-url>`, and `<privacy-policy-url>`.
- Redact URLs, tokens, seller identifiers, OAuth codes, cookies, request IDs, and raw logs before attaching evidence.
- Keep Google Console actions manual. Repo tests and docs prove readiness; they do not submit or mutate Google resources.

## Smoke plan after approval

1. Install the Marketplace listing in an approved Google account and open a Google Sheet.
2. Confirm the **ZelerData** menu appears after install and on open.
3. Save a show-once extension token through **ZelerData → Settings**.
4. Run a supported formula such as `=ZELERDATA_SKU("cuenta")`.
5. Run one deferred formula and confirm `DATA_UNAVAILABLE` is stable.
6. Clear or revoke the token and confirm `TOKEN_MISSING` or `TOKEN_REVOKED` is stable.

## Manual-only boundary

Google Cloud project linkage, OAuth consent configuration, Apps Script version creation, Marketplace SDK edits, listing asset upload, review submission, and post-approval smoke tests are manual-only and outside repo implementation.
