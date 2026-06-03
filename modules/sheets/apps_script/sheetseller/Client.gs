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
  return [[zelerdataPublicErrorMessage_(code, message)]];
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
