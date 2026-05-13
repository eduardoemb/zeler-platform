# Private/manual Apps Script pilot

This directory contains the minimum Sheetseller Apps Script project used for the private pilot. It is intentionally thin: formulas keep their legacy names and forward to the zeler-platform Formula API with an extension token.

Pilot seller: `82453304`

Use only seller `82453304` for this manual validation pass. Do not query old stores, production dumps, or unrelated sellers while validating the pilot.

## Safety gates before touching a Google Sheet

- Formula API deployed: zeler-platform must expose `/sheets/formulas:execute`, `/sheets/formulas:batch`, and `/sheets/formulas/inventory` in the pilot environment.
- The Formula API deployment must have the extension token pepper configured before any token is issued or validated.
- zeler-app `/sheets/config` deployed: the operator must be able to create a show-once extension token from the existing Sheetseller config UI.
- The token shown by zeler-app must be scoped only to pilot seller `82453304` / its visible `cuenta` nickname.
- Do not paste real tokens into repo/issues/logs, chat, screenshots, support tickets, test output, or comments.
- Do not paste tokens into this repository, issues, chat, logs, or screenshots.
- Do not deploy from this checklist. This runbook is for private/manual install and smoke validation only; release and deploy decisions stay with the orchestrator/operator.

## Create Apps Script project (private, from repo files)

1. Open the pilot Google Sheet for seller `82453304`.
2. Go to **Extensions → Apps Script** and create a private Apps Script project bound to that spreadsheet.
3. In the Apps Script editor, enable **Project Settings → Show "appsscript.json" manifest file in editor** if the manifest is hidden.
4. Copy these files from this repo path, preserving the same names:
   - `modules/sheets/apps_script/sheetseller/appsscript.json`
   - `modules/sheets/apps_script/sheetseller/Config.gs`
   - `modules/sheets/apps_script/sheetseller/Client.gs`
   - `modules/sheets/apps_script/sheetseller/Formulas.gs`
5. Save the Apps Script project.
6. Reload the spreadsheet and confirm the **Sheetseller** menu appears.

## Configure API base URL and token

1. In Apps Script, run `setSheetsellerApiBaseUrl("https://<pilot-api-host>")` once for the spreadsheet, or open `showSheetsellerSettings` from the **Sheetseller** menu and paste the base URL.
2. Create an extension token in zeler-app `/sheets/config` and copy it during the show-once extension token moment.
3. Open **Sheetseller → Settings**, paste the extension token, and save. Never store the raw token in the spreadsheet cells or any repo artifact.

The API base URL is stored in document properties because it is non-secret spreadsheet configuration. The extension token is stored in user properties so each operator keeps their own bearer credential within Apps Script constraints.

## Authorize scopes

Run `showSheetsellerSettings` from Apps Script or reload the sheet and use the menu. Google will ask for the manifest scopes needed to show UI, call the Formula API, and interact with the current spreadsheet.

## Validation matrix for currently implemented wrappers

`cuenta` must be the seller nickname or canonical seller visible to token scope. For this pilot, use the nickname associated with seller `82453304`; examples below use the placeholder `"cuenta"` so no real account label is committed.

| Formula | Example Google Sheets formula | Expected pilot check |
|---|---|---|
| `SHEETSELLER_CATEGORIAS` | `=SHEETSELLER_CATEGORIAS("cuenta", "MLA1")` | Category ID by item ID, blank for unknown item IDs. |
| `SHEETSELLER_CODIGOML` | `=SHEETSELLER_CODIGOML("cuenta", "SKU-1", "MLA1")` | Inventory / ML code by SKU + item ID. |
| `SHEETSELLER_CODIGOML2SKUID` | `=SHEETSELLER_CODIGOML2SKUID("cuenta", "INV-1", "si")` | Optional headers plus code, item ID, SKU rows. |
| `SHEETSELLER_DASHBOARD` | `=SHEETSELLER_DASHBOARD("cuenta", "todos", "todos", "base", "si")` | MVP dashboard columns for current item data. |
| `SHEETSELLER_DASHBOARDSINCATALOGO` | `=SHEETSELLER_DASHBOARDSINCATALOGO("cuenta", "todos", "todos", "base", "si")` | Same MVP dashboard columns, excluding rows with catalog indicators. |
| `SHEETSELLER_DIASPUBLICADA` | `=SHEETSELLER_DIASPUBLICADA("cuenta", "MLA1")` | Days since publication date when current read model has a date. |
| `SHEETSELLER_ID` | `=SHEETSELLER_ID("cuenta", "SKU-1")` | Item IDs for the SKU; duplicates are allowed. |
| `SHEETSELLER_IDSTOCK` | `=SHEETSELLER_IDSTOCK("cuenta", "SKU-1", "si")` | Optional headers plus SKU, item ID, stock rows. |
| `SHEETSELLER_IMAGENES` | `=SHEETSELLER_IMAGENES("cuenta", "todos", "todos")` | Thumbnail URLs from the current item read model. |
| `SHEETSELLER_PRECIO` | `=SHEETSELLER_PRECIO("cuenta", "SKU-1", "MLA1", "base")` | Base price by SKU + item ID. |
| `SHEETSELLER_PUBLICACIONES` | `=SHEETSELLER_PUBLICACIONES("cuenta", "todos", "todos", "base", "", "si")` | MVP current publication table. |
| `SHEETSELLER_SKU` | `=SHEETSELLER_SKU("cuenta")` | Unique SKU list for the authorized seller. |
| `SHEETSELLER_STATUS` | `=SHEETSELLER_STATUS("cuenta", "MLA1")` | Current publication status by item ID. |
| `SHEETSELLER_STOCK` | `=SHEETSELLER_STOCK("cuenta", "SKU-1", "MLA1")` | Stock by SKU + item ID. |
| `SHEETSELLER_TITULO` | `=SHEETSELLER_TITULO("cuenta", "MLA1")` | Current listing title by item ID. |
| `SHEETSELLER_URL` | `=SHEETSELLER_URL("cuenta", "SKU-1", "MLA1")` | Current permalink by SKU + item ID. |

Start with the smallest smoke check, then move to table formulas:

```text
=SHEETSELLER_SKU("cuenta")
=SHEETSELLER_STOCK("cuenta", "SKU-1", "MLA1")
=SHEETSELLER_DASHBOARD("cuenta", "todos", "todos", "base", "si")
=SHEETSELLER_IMAGENES("cuenta", "todos", "todos")
```

## Expected stable errors during pilot

- `DATA_UNAVAILABLE`: expected for formulas whose backend handler/read model is not implemented yet, for example Batch B/C/D/E formulas outside the matrix above. The wrapper exists, but the platform intentionally returns a safe unavailable cell instead of calling old services.
- `TOKEN_MISSING`: expected when the Apps Script user properties do not contain a saved token.
- `TOKEN_REVOKED`: expected after the token is revoked or rotated away in zeler-app.
- `SELLER_FORBIDDEN`: expected when `cuenta` does not match seller `82453304` / the token seller scope.
- `FORMULA_UNKNOWN`: expected only if the formula name sent to the API is not in the 53-formula registry.
- `BAD_ARGUMENT`: expected for malformed arguments or incompatible range cardinality.
- `RATE_LIMITED`: expected if a manual recalculation loop exceeds the per-token/per-seller budget.
- `INTERNAL`: unexpected; stop validation, capture the non-secret request context, and escalate without token material.

## Manual pilot checklist

- [ ] Confirm Formula API deployed with extension token pepper configured.
- [ ] Confirm zeler-app `/sheets/config` deployed and able to issue a show-once extension token.
- [ ] Confirm the token is scoped only to seller `82453304`.
- [ ] Install the private Apps Script project from the repo files listed above.
- [ ] Configure the pilot API base URL and save the token through **Sheetseller → Settings**.
- [ ] Validate the four smoke formulas, then the full matrix for implemented wrappers.
- [ ] Call one not-yet-implemented formula and confirm `DATA_UNAVAILABLE` is stable.
- [ ] Clear the saved token and confirm `TOKEN_MISSING` is stable.
- [ ] Revoke or rotate the token from zeler-app and confirm `TOKEN_REVOKED` is stable.
- [ ] Confirm audit/recalculation evidence does not include raw token material.

## Release boundary

This is not a Marketplace package. Marketplace publication remains deferred until quotas, support/privacy assets, review evidence, and private-pilot hardening are complete.
