/* RunSense service worker.
 *
 * Deliberately caches nothing: training data, chat and coach plans must
 * always be the live ones. It only lets the app be installed and shows a
 * clear message when the phone has no connection, instead of a browser
 * error page. */

const OFFLINE_HTML = `<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RunSense</title>
<body style="margin:0;display:grid;place-items:center;min-height:100vh;font-family:system-ui;background:#0b1220;color:#e2e8f0;text-align:center;padding:24px">
<div><div style="font-size:20px;font-weight:700;margin-bottom:8px">目前沒有網路連線</div>
<div style="color:#94a3b8">RunSense 需要連到伺服器才能顯示最新的訓練與聊天內容。<br>確認手機網路後再重新整理。</div></div></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // everything else: the browser's own handling
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } }),
    ),
  );
});
