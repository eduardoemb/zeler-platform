var SHEETSELLER_EXTENSION_TOKEN_KEY = "SHEETSELLER_EXTENSION_TOKEN";
var SHEETSELLER_API_BASE_URL_KEY = "SHEETSELLER_API_BASE_URL";
var SHEETSELLER_DEFAULT_API_BASE_URL = "https://api.zeler.app";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Sheetseller")
    .addItem("Settings", "showSheetsellerSettings")
    .addSeparator()
    .addItem("Clear extension token", "clearSheetsellerExtensionToken")
    .addToUi();
}

function showSheetsellerSettings() {
  var settings = getSheetsellerSettings_();
  var html = HtmlService.createHtmlOutput(buildSheetsellerSettingsHtml_(settings))
    .setTitle("Sheetseller settings")
    .setWidth(420);
  SpreadsheetApp.getUi().showSidebar(html);
}

function saveSheetsellerSettings(form) {
  var apiBaseUrl = String((form && form.apiBaseUrl) || "").trim();
  var token = String((form && form.extensionToken) || "").trim();
  if (apiBaseUrl) {
    setSheetsellerApiBaseUrl(apiBaseUrl);
  }
  if (token) {
    setSheetsellerExtensionToken(token);
  }
  return getSheetsellerSettings_();
}

function setSheetsellerApiBaseUrl(apiBaseUrl) {
  var normalized = String(apiBaseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) {
    throw new Error("API base URL is required");
  }
  PropertiesService.getDocumentProperties().setProperty(
    SHEETSELLER_API_BASE_URL_KEY,
    normalized
  );
  return normalized;
}

function setSheetsellerExtensionToken(extensionToken) {
  var token = String(extensionToken || "").trim();
  if (!token) {
    throw new Error("Extension token is required");
  }
  // Tradeoff: the bearer token is per operator, so UserProperties isolates it by
  // Google account. DocumentProperties is intentionally reserved for the
  // non-secret API base URL shared by this spreadsheet.
  PropertiesService.getUserProperties().setProperty(
    SHEETSELLER_EXTENSION_TOKEN_KEY,
    token
  );
  return { tokenStored: true, tokenPrefix: token.substring(0, 10) };
}

function clearSheetsellerExtensionToken() {
  PropertiesService.getUserProperties().deleteProperty(SHEETSELLER_EXTENSION_TOKEN_KEY);
  SpreadsheetApp.getActive().toast("Sheetseller extension token cleared", "Sheetseller", 5);
  return { tokenStored: false };
}

function getSheetsellerExtensionToken_() {
  return PropertiesService.getUserProperties().getProperty(SHEETSELLER_EXTENSION_TOKEN_KEY) || "";
}

function getSheetsellerApiBaseUrl_() {
  return (
    PropertiesService.getDocumentProperties().getProperty(SHEETSELLER_API_BASE_URL_KEY) ||
    SHEETSELLER_DEFAULT_API_BASE_URL
  );
}

function getSheetsellerSettings_() {
  var token = getSheetsellerExtensionToken_();
  return {
    apiBaseUrl: getSheetsellerApiBaseUrl_(),
    tokenStored: Boolean(token),
    tokenPrefix: token ? token.substring(0, 10) : ""
  };
}

function buildSheetsellerSettingsHtml_(settings) {
  var prefix = settings.tokenStored ? "Stored token prefix: " + escapeHtml_(settings.tokenPrefix) : "No token stored";
  return "" +
    "<section style='font:14px Arial,sans-serif;color:#17202a;padding:16px'>" +
    "<h1 style='font-size:18px;margin:0 0 8px'>Sheetseller private pilot</h1>" +
    "<p style='line-height:1.45'>Paste the show-once extension token from zeler-app. The token is stored only for your Google account in this spreadsheet.</p>" +
    "<label>API base URL</label>" +
    "<input id='apiBaseUrl' style='box-sizing:border-box;width:100%;margin:6px 0 12px;padding:8px' value='" + escapeHtml_(settings.apiBaseUrl) + "'>" +
    "<label>Extension token</label>" +
    "<textarea id='extensionToken' rows='4' style='box-sizing:border-box;width:100%;margin:6px 0 12px;padding:8px' placeholder='zs_ext_...'></textarea>" +
    "<p style='font-size:12px;color:#52616b'>" + prefix + "</p>" +
    "<button onclick='save()' style='background:#123044;color:#fff;border:0;border-radius:4px;padding:8px 12px'>Save settings</button> " +
    "<button onclick='clearToken()' style='background:#fff;color:#8a1f11;border:1px solid #d8dee4;border-radius:4px;padding:8px 12px'>Clear token</button>" +
    "<script>function save(){google.script.run.withSuccessHandler(function(){document.querySelector(\"textarea\").value=\"\";}).saveSheetsellerSettings({apiBaseUrl:document.getElementById(\"apiBaseUrl\").value,extensionToken:document.getElementById(\"extensionToken\").value});}function clearToken(){google.script.run.clearSheetsellerExtensionToken();}</script>" +
    "</section>";
}

function escapeHtml_(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
