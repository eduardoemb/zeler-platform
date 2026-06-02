function zelerdataExecute_(formulaName, cuenta, args) {
  var token = getZelerDataExtensionToken_();
  if (!token) {
    return [["TOKEN_MISSING: configure the ZelerData extension token from the ZelerData menu"]];
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
    return [["INTERNAL: Formula API request failed"]];
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
      error: { code: "INTERNAL", message: "Formula API returned invalid JSON" },
      values: [["INTERNAL: Formula API returned invalid JSON"]]
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
  var message = code + ": " + ((envelope && envelope.error && envelope.error.message) || "formula data is unavailable");
  if (code === "TOKEN_MISSING") {
    message = "TOKEN_MISSING: configure the ZelerData extension token from the ZelerData menu";
  }
  return [[message]];
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
