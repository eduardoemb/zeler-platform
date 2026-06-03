# ZelerData Google Workspace Marketplace add-on

This directory contains the ZelerData Apps Script project prepared for public Google Workspace Marketplace review. It exposes the **ZelerData** menu, stores each user's show-once extension token in Apps Script user properties, and forwards `ZELERDATA_*` custom functions to the zeler-platform Formula API.

## Quick path

1. Install ZelerData from Google Workspace Marketplace.
2. Open a Google Sheet and confirm the **ZelerData** menu appears.
3. Open **ZelerData → Settings**, paste the show-once extension token from `https://app.zeler.ai/sheets/config`, and choose **Save token**.
4. Start with `=ZELERDATA_SKU("cuenta")`, then validate the formulas documented in `docs/sheets/zelerdata-formulas.md`.

Do not paste tokens into this repository, issues, chat, logs, screenshots, spreadsheet cells, or support tickets.

## Source readiness checklist

- [ ] `appsscript.json` uses V8 and only the documented OAuth scopes.
- [ ] `Config.gs` defines `onInstall(e)` and `onOpen(e)` for the public menu/sidebar flow.
- [ ] `Client.gs` sends requests to `/sheets/formulas:execute` with the saved bearer token and returns review-safe error messages.
- [ ] `Formulas.gs` preserves all 53 wrapper names, parameters, aliases, and Google Sheets autocomplete JSDoc.
- [ ] This README and `docs/sheets/zelerdata-marketplace-publication.md` point operators to manual Marketplace release steps.
- [ ] The submitted Apps Script source matches an immutable Apps Script version recorded in the release evidence.

## Configure ZelerData settings

- `showZelerDataSettings` opens the public settings sidebar.
- The sidebar links to zeler-app Sheets config for token creation.
- The Formula API URL defaults to the production-safe endpoint in `Config.gs`; Marketplace users should not edit infrastructure endpoints.
- `setZelerDataApiBaseUrl` remains available only for support-led review or rollback diagnostics, not for normal Marketplace setup.

The API base URL is stored in document properties because it is non-secret spreadsheet configuration. The extension token is stored in user properties so each Google account keeps its own bearer credential within Apps Script constraints.

## Authorize scopes

Google asks for the manifest scopes needed to show the ZelerData UI, call the Formula API, and interact only with the current spreadsheet. The scope matrix for OAuth consent and Marketplace SDK review lives in `docs/sheets/zelerdata-marketplace-publication.md`.

## Public formula smoke checks

`cuenta` must be the seller nickname or canonical seller visible to token scope. Use placeholders in repo evidence and sanitized screenshots.

```text
=ZELERDATA_SKU("cuenta")
=ZELERDATA_STOCK("cuenta", "SKU-1", "MLA1")
=ZELERDATA_DASHBOARD("cuenta", "todos", "todos", "base", "si")
=ZELERDATA_IMAGENES("cuenta", "todos", "todos")
```

Supported and deferred formula behavior is documented in `docs/sheets/zelerdata-formulas.md`.

## Release boundary

Repo changes prove source readiness only. Google Cloud project linkage, OAuth consent, immutable Apps Script version creation, Marketplace SDK listing, asset upload, review submission, and approved-context smoke tests are manual operator steps documented in `docs/sheets/zelerdata-marketplace-publication.md`.
