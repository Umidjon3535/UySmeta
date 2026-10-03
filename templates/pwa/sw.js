{% autoescape off %}/* UySmeta service worker (core/views/pages.py: service_worker). Versiya: {{ version }}
 * - Sahifalar: avval internet, bo'lmasa — /offline (shaxsiy sahifalar keshlanmaydi).
 * - Static (CSS/JS/rasm): kesh, so'ng internet (fayl nomida ?v= versiya bor).
 * - API, admin, kirish, to'lov — faqat internet. */
const CACHE = "uysmeta-{{ version }}";
const PRECACHE = [{% for url in precache %}"{{ url }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
const NETWORK_ONLY = ["/api/", "/admin", "/kirish", "/royxat", "/chiqish", "/tiklash", "/hamyon", "/buyurtma", "/sw.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("uysmeta-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin || NETWORK_ONLY.some((p) => url.pathname.startsWith(p))) return;

  // Sahifalar: internet; uzilgan bo'lsa — offline sahifasi
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline")));
    return;
  }

  // Static fayllar: kesh → internet (va keshga yozish)
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
      )
    );
  }
});
{% endautoescape %}
