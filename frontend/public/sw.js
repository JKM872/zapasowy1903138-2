// BigOne Service Worker
// Handles caching, offline support, and push notifications

const CACHE_NAME = 'bigone-cache-v1';
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/manifest.json',
    '/icons/icon-192x192.png',
    '/icons/icon-512x512.png'
];

const API_CACHE_NAME = 'bigone-api-cache-v1';
const API_CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing Service Worker');

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating Service Worker');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME && name !== API_CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // API requests - network first with cache fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirstWithCache(request));
        return;
    }

    // Static assets - cache first
    event.respondWith(cacheFirstWithNetwork(request));
});

// Network first strategy with cache fallback
async function networkFirstWithCache(request) {
    const cache = await caches.open(API_CACHE_NAME);

    try {
        const networkResponse = await fetch(request);

        // Cache successful GET requests
        if (request.method === 'GET' && networkResponse.ok) {
            const responseToCache = networkResponse.clone();
            cache.put(request, responseToCache);
        }

        return networkResponse;
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', request.url);
        const cachedResponse = await cache.match(request);

        if (cachedResponse) {
            return cachedResponse;
        }

        // Return offline fallback for API
        return new Response(
            JSON.stringify({
                error: 'Offline',
                message: 'No internet connection',
                cached: false
            }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Cache first strategy with network fallback
async function cacheFirstWithNetwork(request) {
    const cachedResponse = await caches.match(request);

    if (cachedResponse) {
        // Update cache in background
        fetch(request).then((response) => {
            if (response.ok) {
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(request, response);
                });
            }
        }).catch(() => { });

        return cachedResponse;
    }

    try {
        const networkResponse = await fetch(request);

        if (networkResponse.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }

        return networkResponse;
    } catch (error) {
        // Return offline page
        return caches.match('/offline.html') || new Response('Offline', { status: 503 });
    }
}

// Push notification event
self.addEventListener('push', (event) => {
    console.log('[SW] Push notification received');

    let data = {
        title: 'BigOne',
        body: 'New predictions available!',
        icon: '/icons/icon-192x192.png',
        badge: '/icons/icon-72x72.png',
        tag: 'bigone-notification',
        data: {
            url: '/'
        }
    };

    if (event.data) {
        try {
            data = { ...data, ...event.data.json() };
        } catch (e) {
            data.body = event.data.text();
        }
    }

    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: data.icon,
            badge: data.badge,
            tag: data.tag,
            data: data.data,
            actions: [
                { action: 'view', title: 'View Predictions' },
                { action: 'dismiss', title: 'Dismiss' }
            ],
            vibrate: [200, 100, 200],
            requireInteraction: false
        })
    );
});

// Notification click event
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked:', event.action);

    event.notification.close();

    if (event.action === 'dismiss') {
        return;
    }

    const urlToOpen = event.notification.data?.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((windowClients) => {
                // Focus existing window if open
                for (const client of windowClients) {
                    if (client.url.includes(self.location.origin) && 'focus' in client) {
                        client.navigate(urlToOpen);
                        return client.focus();
                    }
                }
                // Open new window
                return clients.openWindow(urlToOpen);
            })
    );
});

// Background sync for offline actions
self.addEventListener('sync', (event) => {
    console.log('[SW] Background sync:', event.tag);

    if (event.tag === 'sync-predictions') {
        event.waitUntil(syncPredictions());
    }
});

async function syncPredictions() {
    // Sync any pending actions when back online
    console.log('[SW] Syncing predictions...');

    try {
        const response = await fetch('/api/predictions/today');
        if (response.ok) {
            console.log('[SW] Predictions synced successfully');
        }
    } catch (error) {
        console.log('[SW] Sync failed, will retry later');
    }
}

// Periodic background sync (if supported)
self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'update-predictions') {
        event.waitUntil(updatePredictions());
    }
});

async function updatePredictions() {
    console.log('[SW] Periodic update of predictions');

    try {
        const response = await fetch('/api/predictions/today');
        const data = await response.json();

        // Notify user if there are new qualifying matches
        if (data.predictions && data.predictions.length > 0) {
            const qualifying = data.predictions.filter(p => p.qualifies).length;

            if (qualifying > 0) {
                self.registration.showNotification('BigOne', {
                    body: `${qualifying} new qualifying predictions available!`,
                    icon: '/icons/icon-192x192.png',
                    tag: 'bigone-update',
                    data: { url: '/' }
                });
            }
        }
    } catch (error) {
        console.log('[SW] Periodic update failed');
    }
}

console.log('[SW] Service Worker loaded');
