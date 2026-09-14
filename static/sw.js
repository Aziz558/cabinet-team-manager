const CACHE_NAME = 'cabinet-jmh-v3';

self.addEventListener('install', event => {
  // Ne pré-cache plus aucune page HTML : le reseau est la seule source de verite.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  // Navigations (pages Flask) : JAMAIS de cache, erreur = page d'erreur, pas un vieux HTML.
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request));
    return;
  }
  // Assets statiques et CDN : network-first, fallback cache (hors ligne).
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const copy = response.clone();
        if (response.ok) {
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(cacheNames.filter(n => n !== CACHE_NAME).map(n => caches.delete(n)))
    )
    .then(() => self.clients.claim())
    // Les fenetres ouvertes (PWA incluses) recoverent le HTML neuf.
    .then(() => self.clients.matchAll({ type: 'window' }))
    .then(clients => clients.forEach(c => c.navigate(c.url).catch(() => {})))
  );
});
