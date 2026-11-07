/* Service Worker für Messe Tracker Pro
   Cache-Version erhöhen → alte Caches werden beim Aktivieren gelöscht. */
const CACHE_VERSION = 'mt-v1';
const APP_SHELL = [
  '/',
  '/pwa-start',
  '/scan-qr',
  '/static/manifest.json',
  '/static/offline.html',
  '/static/jsQR.min.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
];

// ---------- Install: App-Shell vorcachen ----------
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    // allSettled: einzelne Fehler (z. B. fehlendes jsQR.min.js)
    // dürfen den Service Worker nicht blockieren
    await Promise.allSettled(
      APP_SHELL.map(url =>
        cache.add(url).catch(err =>
          console.warn('[SW] Precache fehlgeschlagen:', url, err))
      )
    );
  })());
  self.skipWaiting();
});

// ---------- Activate: alte Caches entfernen ----------
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => k !== CACHE_VERSION)
          .map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

// ---------- Fetch-Strategie ----------
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // API: Network-only, klarer Fehler bei Offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith((async () => {
      try {
        return await fetch(req);
      } catch (err) {
        return new Response(
          JSON.stringify({
            status: 'offline',
            message: 'Keine Verbindung zum Server.'
          }),
          { status: 503,
            headers: { 'Content-Type': 'application/json' } }
        );
      }
    })());
    return;
  }

  // Scan-Seiten: Network-first, Cache-Fallback
  if (url.pathname.startsWith('/scan/')) {
    event.respondWith((async () => {
      try {
        const resp = await fetch(req);
        if (resp.ok) {
          const copy = resp.clone();
          const cache = await caches.open(CACHE_VERSION);
          cache.put(req, copy);
        }
        return resp;
      } catch (err) {
        const cached = await caches.match(req);
        if (cached) return cached;
        const fallback = await caches.match('/static/offline.html');
        return fallback || new Response(
          '<h1>Offline</h1><p>Diese Seite wurde nicht vorab ' +
          'geladen. Bitte einmal mit Internet öffnen.</p>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
    })());
    return;
  }

  // Alle anderen GET-Anfragen: Cache-first, dann Netzwerk
  event.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const resp = await fetch(req);
      if (resp.ok) {
        const copy = resp.clone();
        const cache = await caches.open(CACHE_VERSION);
        cache.put(req, copy);
      }
      return resp;
    } catch (err) {
      const fallback = await caches.match('/static/offline.html');
      return fallback || new Response(
        'Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } }
      );
    }
  })());
});

// ---------- Background Sync (optional, Android) ----------
self.addEventListener('sync', (event) => {
  if (event.tag === 'mt-sync-pending') {
    event.waitUntil(self.clients.matchAll({ type: 'window' })
      .then(clients => clients.forEach(c =>
        c.postMessage({ type: 'mt-sync-now' }))));
  }
});