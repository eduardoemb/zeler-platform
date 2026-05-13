# Private/manual Apps Script pilot

This directory contains the minimum Sheetseller Apps Script project used for the private pilot. It is intentionally thin: formulas keep their legacy names and forward to the zeler-platform Formula API with an extension token.

## Create Apps Script project

1. Open the target Google Sheet.
2. Go to **Extensions → Apps Script**.
3. Copy these files into the Apps Script editor with the same names:
   - `appsscript.json`
   - `Config.gs`
   - `Client.gs`
   - `Formulas.gs`
4. Save the project and reload the spreadsheet.

## Configure API base URL and token

1. In Apps Script, run `setSheetsellerApiBaseUrl("https://<pilot-api-host>")` once for the spreadsheet, or open `showSheetsellerSettings` from the **Sheetseller** menu and paste the base URL.
2. Create an extension token in zeler-app `/sheets/config` and copy it during the show-once moment.
3. Open **Sheetseller → Settings**, paste the extension token, and save. Do not paste tokens into this repository, issues, chat, logs, or screenshots.

The API base URL is stored in document properties because it is non-secret spreadsheet configuration. The extension token is stored in user properties so each operator keeps their own bearer credential within Apps Script constraints.

## Authorize scopes

Run `showSheetsellerSettings` from Apps Script or reload the sheet and use the menu. Google will ask for the manifest scopes needed to show UI, call the Formula API, and interact with the current spreadsheet.

## Test a formula

After saving the token, try a small formula first:

```text
=SHEETSELLER_SKU("SELLER_NICKNAME")
```

`cuenta` is the Mercado Libre seller nickname authorized by the extension token. Legacy parameters named `databaseName` or `collectionName` are treated as the same seller nickname for the pilot wrappers.

## Release boundary

This is not a Marketplace package. Marketplace publication remains deferred until quotas, support/privacy assets, review evidence, and private-pilot hardening are complete.
