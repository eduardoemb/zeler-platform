var ZELERDATA_EXTENSION_TOKEN_KEY = "ZELERDATA_EXTENSION_TOKEN";
var ZELERDATA_API_BASE_URL_KEY = "ZELERDATA_API_BASE_URL";
var ZELERDATA_DEFAULT_API_BASE_URL = "https://api.zeler.app";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("ZelerData")
    .addItem("Settings", "showZelerDataSettings")
    .addSeparator()
    .addItem("Clear extension token", "clearZelerDataExtensionToken")
    .addToUi();
}

function showZelerDataSettings() {
  var settings = getZelerDataSettings_();
  var html = HtmlService.createHtmlOutput(buildZelerDataSettingsHtml_(settings))
    .setTitle("ZelerData settings")
    .setWidth(420);
  SpreadsheetApp.getUi().showSidebar(html);
}

function saveZelerDataSettings(form) {
  var apiBaseUrl = String((form && form.apiBaseUrl) || "").trim();
  var token = String((form && form.extensionToken) || "").trim();
  if (apiBaseUrl) {
    setZelerDataApiBaseUrl(apiBaseUrl);
  }
  if (token) {
    setZelerDataExtensionToken(token);
  }
  return getZelerDataSettings_();
}

function setZelerDataApiBaseUrl(apiBaseUrl) {
  var normalized = String(apiBaseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) {
    throw new Error("API base URL is required");
  }
  PropertiesService.getDocumentProperties().setProperty(
    ZELERDATA_API_BASE_URL_KEY,
    normalized
  );
  return normalized;
}

function setZelerDataExtensionToken(extensionToken) {
  var token = String(extensionToken || "").trim();
  if (!token) {
    throw new Error("Extension token is required");
  }
  // Tradeoff: the bearer token is per operator, so UserProperties isolates it by
  // Google account. DocumentProperties is intentionally reserved for the
  // non-secret API base URL shared by this spreadsheet.
  PropertiesService.getUserProperties().setProperty(
    ZELERDATA_EXTENSION_TOKEN_KEY,
    token
  );
  return { tokenStored: true, tokenPrefix: token.substring(0, 10) };
}

function clearZelerDataExtensionToken() {
  PropertiesService.getUserProperties().deleteProperty(ZELERDATA_EXTENSION_TOKEN_KEY);
  SpreadsheetApp.getActive().toast("ZelerData extension token cleared", "ZelerData", 5);
  return { tokenStored: false };
}

function getZelerDataExtensionToken_() {
  return PropertiesService.getUserProperties().getProperty(ZELERDATA_EXTENSION_TOKEN_KEY) || "";
}

function getZelerDataApiBaseUrl_() {
  return (
    PropertiesService.getDocumentProperties().getProperty(ZELERDATA_API_BASE_URL_KEY) ||
    ZELERDATA_DEFAULT_API_BASE_URL
  );
}

function getZelerDataSettings_() {
  var token = getZelerDataExtensionToken_();
  return {
    apiBaseUrl: getZelerDataApiBaseUrl_(),
    tokenStored: Boolean(token),
    tokenPrefix: token ? token.substring(0, 10) : ""
  };
}

function buildZelerDataSettingsHtml_(settings) {
  var prefix = settings.tokenStored ? "Stored token prefix: " + escapeHtml_(settings.tokenPrefix) : "No token stored";
  return "" +
    "<section style='font:14px Arial,sans-serif;color:#17202a;padding:16px'>" +
    "<h1 style='font-size:18px;margin:0 0 8px'>ZelerData private pilot</h1>" +
    "<p style='line-height:1.45'>Paste the show-once extension token from zeler-app. The token is stored only for your Google account in this spreadsheet.</p>" +
    "<label>API base URL</label>" +
    "<input id='apiBaseUrl' style='box-sizing:border-box;width:100%;margin:6px 0 12px;padding:8px' value='" + escapeHtml_(settings.apiBaseUrl) + "'>" +
    "<label>Extension token</label>" +
    "<textarea id='extensionToken' rows='4' style='box-sizing:border-box;width:100%;margin:6px 0 12px;padding:8px' placeholder='zs_ext_...'></textarea>" +
    "<p style='font-size:12px;color:#52616b'>" + prefix + "</p>" +
    "<button onclick='save()' style='background:#123044;color:#fff;border:0;border-radius:4px;padding:8px 12px'>Save settings</button> " +
    "<button onclick='clearToken()' style='background:#fff;color:#8a1f11;border:1px solid #d8dee4;border-radius:4px;padding:8px 12px'>Clear token</button>" +
    "<script>function save(){google.script.run.withSuccessHandler(function(){document.querySelector(\"textarea\").value=\"\";}).saveZelerDataSettings({apiBaseUrl:document.getElementById(\"apiBaseUrl\").value,extensionToken:document.getElementById(\"extensionToken\").value});}function clearToken(){google.script.run.clearZelerDataExtensionToken();}</script>" +
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
