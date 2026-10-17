// Darmowy przekaźnik SofaScore na Google Apps Script (IP Google, nie GitHuba).
// Wdrożenie: script.google.com → Nowy projekt → wklej → Wdróż → Nowe wdrożenie
// → Typ: Aplikacja internetowa → Wykonaj jako: Ja → Dostęp: Każdy → Wdróż.
// Skopiuj URL (…/exec) do sekretu GitHub SOFASCORE_RELAY.
// Przepuszcza wyłącznie adresy API SofaScore.
function doGet(e) {
  var url = (e && e.parameter && e.parameter.url) || '';
  if (!/^https:\/\/(www|api)\.sofascore\.com\/api\/v1\//.test(url)) {
    return ContentService.createTextOutput('{"error":"forbidden url"}')
      .setMimeType(ContentService.MimeType.JSON);
  }
  var r = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true,
    headers: { 'User-Agent': 'okhttp/4.12.0', 'Accept': 'application/json' }
  });
  var body = r.getContentText();
  if (r.getResponseCode() !== 200 && body.charAt(0) !== '{') {
    body = '{"error":{"code":' + r.getResponseCode() + '}}';
  }
  return ContentService.createTextOutput(body).setMimeType(ContentService.MimeType.JSON);
}
