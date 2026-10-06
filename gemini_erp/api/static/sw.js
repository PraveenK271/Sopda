// Service worker: cache the app shell so the PWA loads offline. API responses
// are always fetched from the network (never cached — they are dynamic and
// auth-scoped).
// Bump on every app-shell change: the shell is served cache-first, so a new
// name is what makes installed phones fetch the new files (v2: v1.2.0
// cancelled-invoice marking).
const CACHE = "gemini-pwa-v2";
const SHELL = [
  "/",
  "/index.html",
  "/app.js",
  "/styles.css",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never intercept API calls — always go to the network.
  if (url.pathname.startsWith("/api")) return;
  if (event.request.method !== "GET") return;
  // Cache-first for the shell, falling back to network.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
