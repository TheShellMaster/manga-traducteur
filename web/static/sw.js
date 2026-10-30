// Manga Translator Studio - Service Worker (PWA Offline Shell & Cache)
const CACHE_NAME = 'manga-translator-v2.1';
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/css/animations.css',
  '/static/js/app.js',
  '/static/js/animations.js',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) {
            return caches.delete(k);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // Only cache GET requests for static assets, never API calls or dynamic uploads
  const url = new URL(event.request.url);
  if (event.request.method === 'GET' && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request);
      })
    );
  }
});
