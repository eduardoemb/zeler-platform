function zelerdataExecute_(formulaName, cuenta, args) {
  var token = getZelerDataExtensionToken_();
  if (!token) {
    return [[zelerdataPublicErrorMessage_("TOKEN_MISSING", "")]];
  }
  var payload = {
    formula: formulaName,
    cuenta: String(cuenta || ""),
    args: args || {},
    request_id: Utilities.getUuid()
  };
  var response;
  try {
    response = UrlFetchApp.fetch(zelerdataBuildEndpoint_(getZelerDataApiBaseUrl_()), {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: "Bearer " + token
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
  } catch (error) {
    return [[zelerdataPublicErrorMessage_("NETWORK_ERROR", "")]];
  }
  if (response.getResponseCode && response.getResponseCode() >= 500) {
    return [[zelerdataPublicErrorMessage_("SERVICE_UNAVAILABLE", "")]];
  }
  return zelerdataEnvelopeToValues_(zelerdataParseResponse_(response));
}

function zelerdataBuildEndpoint_(apiBaseUrl) {
  return String(apiBaseUrl || "").replace(/\/+$/, "") + "/sheets/formulas:execute";
}

function zelerdataParseResponse_(response) {
  var body = response.getContentText() || "{}";
  try {
    return JSON.parse(body);
  } catch (error) {
    return {
      ok: false,
      error: { code: "SERVICE_UNAVAILABLE", message: "The service returned an unreadable response" },
      values: [[zelerdataPublicErrorMessage_("SERVICE_UNAVAILABLE", "")]]
    };
  }
}

function zelerdataEnvelopeToValues_(envelope) {
  if (envelope && Array.isArray(envelope.values)) {
    if (envelope.values.length === 0) {
      return [[""]];
    }
    return zelerdataCoerce2d_(envelope.values);
  }
  var code = (envelope && envelope.error && envelope.error.code) || "DATA_UNAVAILABLE";
  var message = (envelope && envelope.error && envelope.error.message) || "";
  if (code === "PROCESSING") {
    return [[zelerdataProcessingMessage_(envelope.error)]];
  }
  return [[zelerdataPublicErrorMessage_(code, message)]];
}

function zelerdataProcessingMessage_(error) {
  var seconds = Number(error && error.retry_after_seconds);
  var wait = isFinite(seconds) && seconds > 0 ? Math.round(seconds) : 60;
  return "PROCESANDO: vuelve a calcular en ~" + wait + "s";
}

function zelerdataPublicErrorMessage_(code, message) {
  if (code === "TOKEN_MISSING") {
    return "TOKEN_MISSING: open ZelerData > Settings and save a show-once extension token from zeler-app Sheets config";
  }
  if (code === "TOKEN_REVOKED") {
    return "TOKEN_REVOKED: create a new token in zeler-app and save it from ZelerData > Settings";
  }
  if (code === "SELLER_FORBIDDEN") {
    return "SELLER_FORBIDDEN: this token is not authorized for the requested cuenta";
  }
  if (code === "NETWORK_ERROR") {
    return "NETWORK_ERROR: ZelerData could not reach the Formula API. Try again or contact Zeler support.";
  }
  if (code === "SERVICE_UNAVAILABLE" || code === "INTERNAL") {
    return "SERVICE_UNAVAILABLE: ZelerData could not complete this request. Try again or contact Zeler support.";
  }
  if (code === "PROCESSING") {
    return zelerdataProcessingMessage_({});
  }
  if (code === "DATA_UNAVAILABLE") {
    return "DATA_UNAVAILABLE: this formula is not available for the requested data yet";
  }
  var safeMessage = String(message || "formula data is unavailable").replace(/https?:\/\/\S+/g, "[redacted-url]");
  return code + ": " + safeMessage;
}

function zelerdataCoerce2d_(value) {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return [[""]];
    }
    if (Array.isArray(value[0])) {
      return value;
    }
    return value.map(function (item) {
      return [item];
    });
  }
  return [[value]];
}

/**
 * Discovers existing =ZELERDATA_* formula cells and re-sets them in place
 * (same formula text) to request recalculation. Only cells whose
 * formula matches the exact prefix are touched; user formulas (=SUM, etc.)
 * are never modified. This is a manual, user-invoked action, not a
 * background timer, to respect Apps Script quotas and user intent. Completion
 * refers to scanning, not visible results. A document lock coordinates scripts,
 * not human editors; the immediate reread is not an atomic compare-and-set.
 */
function refreshZelerDataResults() {
  var result = { refreshed: 0, scanned: 0, skippedChanged: 0, pending: true,
    recalculationVerified: false, status: "busy" };
  var lock = LockService.getDocumentLock();
  if (!lock || !lock.tryLock(1000)) return result;
  var properties;
  var cursor;
  var key = "zelerdata.manualRefresh.v1";
  var started = Date.now();
  var pattern = /^=ZELERDATA_[A-Z0-9_]+\(/i;
  try {
    var spreadsheet = SpreadsheetApp.getActive();
    properties = PropertiesService.getDocumentProperties();
    if (!properties) throw new Error("Document properties unavailable");
    var sheets = spreadsheet.getSheets();
    if (sheets.length > 500) throw new Error("Local tab budget exceeded");
    var saved = properties.getProperty(key);
    try { cursor = saved ? JSON.parse(saved) : null; } catch (invalidCursor) { cursor = null; }
    if (!cursor || !Array.isArray(cursor.sheets) || cursor.sheets.length > 500 ||
        !cursor.sheets.every(function (id) { return Number.isInteger(id) && id >= 0; }) ||
        !Number.isInteger(cursor.index) || cursor.index < 0 || cursor.index > cursor.sheets.length ||
        !Number.isInteger(cursor.row) || cursor.row < 0 ||
        !Number.isInteger(cursor.col) || cursor.col < 0) {
      cursor = { sheets: sheets.map(function (sheet) { return sheet.getSheetId(); }),
        index: 0, row: 0, col: 0 };
    }
    result.status = "scheduled";
    while (cursor.index < cursor.sheets.length && result.scanned < 2000 &&
           result.refreshed < 20 && Date.now() - started < 20000) {
      var sheet = sheets.filter(function (candidate) {
        return candidate.getSheetId() === cursor.sheets[cursor.index];
      })[0];
      if (!sheet || cursor.row >= sheet.getLastRow() || sheet.getLastColumn() === 0) {
        cursor.index++;
        cursor.row = 0;
        cursor.col = 0;
        continue;
      }
      var columns = sheet.getLastColumn();
      if (cursor.col >= columns) {
        cursor.row++;
        cursor.col = 0;
        continue;
      }
      var width = Math.min(50, columns - cursor.col, 2000 - result.scanned);
      var formulas = sheet.getRange(cursor.row + 1, cursor.col + 1, 1, width).getFormulas()[0];
      for (var offset = 0; offset < formulas.length; offset++) {
        if (result.refreshed >= 20 || Date.now() - started >= 20000) break;
        var formula = formulas[offset];
        var row = cursor.row;
        var col = cursor.col;
        if (formula && pattern.test(formula)) {
          var cell = sheet.getRange(row + 1, col + 1);
          if (cell.getFormula() === formula) {
            cell.setFormula(formula);
            result.refreshed++;
          } else {
            result.skippedChanged++;
          }
        }
        result.scanned++;
        cursor.col++;
      }
    }
    result.pending = cursor.index < cursor.sheets.length;
  } catch (refreshError) {
    result.status = "failed";
    result.pending = true;
  } finally {
    try {
      if (properties && cursor) {
        if (result.pending) properties.setProperty(key, JSON.stringify(cursor));
        else properties.deleteProperty(key);
      }
    } finally {
      lock.releaseLock();
    }
  }
  SpreadsheetApp.getActive().toast(result.refreshed + " recalculation requests; " +
    (result.pending ? "scan pending: run Refresh results again" : "scan finished") +
    "; cell results not verified", "ZelerData", 5);
  return result;
}
