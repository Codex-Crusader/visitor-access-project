// Keeps the visitor page and its script on the phone. API calls always go to the network.
const CACHE = "visitor-page";
const PAGE = "/";
const SCRIPT = /src="(visitor\.js\?v=\w+)"/;

// Stored at install, so a reload with no signal works on this visit too.
self.addEventListener("install", event =>
  event.waitUntil(refresh().catch(() => {}).then(() => self.skipWaiting())));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname === "/visitor.js") event.respondWith(script(event.request));
  else if (url.pathname === PAGE) event.respondWith(page(event));
});

// A script's address carries its version, so a kept copy never goes stale.
async function script(request) {
  const cache = await caches.open(CACHE);
  return (await cache.match(request, {ignoreVary: true})) || keepScript(cache, request);
}

// Keeps only the current, immutable version of the script, and drops any other script.
async function keepScript(cache, request) {
  const answer = await fetch(request);
  if (answer.ok && (answer.headers.get("Cache-Control") || "").includes("immutable")) {
    for (const old of await cache.keys()) {
      if (new URL(old.url).pathname !== PAGE) await cache.delete(old);
    }
    await cache.put(request, answer.clone());
  }
  return answer;
}

// Keeps the script, then the page, so the two always match.
async function refresh(answer) {
  const cache = await caches.open(CACHE);
  answer = answer || await fetch(PAGE);
  if (!answer.ok) return;
  const src = (await answer.clone().text()).match(SCRIPT);
  if (src && !(await cache.match("/" + src[1], {ignoreVary: true}))) {
    await keepScript(cache, new Request("/" + src[1]));
  }
  await cache.put(PAGE, answer);
}

// The kept page shows at once. A fresh one is stored for next time.
async function page(event) {
  const kept = await caches.match(PAGE, {ignoreSearch: true, ignoreVary: true});
  const fresh = fetch(event.request);
  event.waitUntil(fresh.then(answer => refresh(answer.clone())).catch(() => {}));
  return kept || fresh;
}
