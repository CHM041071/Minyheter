// Nettverk først, så du alltid får dagens brief – men siste versjon fungerer offline.
const CACHE = "nyhetsbrief-v2";
const SKALL = ["./", "stil.css", "manifest.webmanifest", "icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SKALL)));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(n => n !== CACHE).map(n => caches.delete(n)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then(svar => {
        const kopi = svar.clone();
        caches.open(CACHE).then(c => c.put(e.request, kopi));
        return svar;
      })
      .catch(() => caches.match(e.request))
  );
});
