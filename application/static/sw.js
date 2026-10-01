// Keeps the visitor page and its script on the phone, so the page opens at
// once on a weak signal, or with none, or while the free server wakes up.
// Only those two are kept. Every API call goes to the network, and the page
// keeps its own copy of the last pass. The gate and admin pages pass through.
const CACHE = "visitor-page";
const PAGE = "/";
const SCRIPT = /src="(app\.js\?v=\w+)"/;

// Stored as soon as the worker installs, so a reload with no signal works on
// the same visit, not only on the next one.
self.addEventListener("install", event =>
  event.waitUntil(refresh().catch(() => {}).then(() => self.skipWaiting())));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname === "/app.js") event.respondWith(script(event.request));
  else if (url.pathname === PAGE) event.respondWith(page(event));
});

// A script's address carries its version, so a kept copy never goes stale.
async function script(request) {
  const cache = await caches.open(CACHE);
  return (await cache.match(request, {ignoreVary: true})) || keepScript(cache, request);
}

// Only the current version is kept: the server marks it immutable. One copy
// of the script is enough, so the older one goes.
async function keepScript(cache, request) {
  const answer = await fetch(request);
  if (answer.ok && (answer.headers.get("Cache-Control") || "").includes("immutable")) {
    for (const old of await cache.keys()) {
      if (new URL(old.url).pathname === "/app.js") await cache.delete(old);
    }
    await cache.put(request, answer.clone());
  }
  return answer;
}

// Fetches the page, keeps the script it names, then keeps the page. The page
// is kept only after its script, so the two always match.
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

// The kept page shows at once, and a fresh one is stored behind it, so a new
// version shows from the next visit. With nothing kept, the network answers
// straight away and is stored after that.
async function page(event) {
  const kept = await caches.match(PAGE, {ignoreSearch: true, ignoreVary: true});
  const fresh = fetch(event.request);
  event.waitUntil(fresh.then(answer => refresh(answer.clone())).catch(() => {}));
  return kept || fresh;
}
