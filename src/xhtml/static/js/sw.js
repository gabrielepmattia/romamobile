/*
 * Service worker di Roma mobile.
 *
 * Regola numero uno: le pagine di questo sito contengono tempi di attesa in
 * tempo reale. Servirne una dalla cache significherebbe mostrare autobus
 * passati dieci minuti fa, che e' peggio di non mostrare nulla. Quindi:
 *
 *   - navigazioni (HTML)  -> solo rete; se la rete manca, pagina di cortesia
 *   - asset statici       -> cache, con aggiornamento in background
 *   - tutto il resto      -> solo rete
 *
 * Serve da /sw.js (vedi la rotta in src/urls.py) per avere scope su tutto il
 * sito.
 */

var VERSIONE = 'roma-mobile-v1';
var OFFLINE_URL = '/xhtml/s/html/offline.html';

/* Asset che vale la pena avere sottomano: cambiano di rado e servono a ogni pagina. */
var PRECACHE = [
	OFFLINE_URL,
	'/xhtml/s/css/screen.css',
	'/xhtml/s/img/favicon.png',
	'/xhtml/s/img/icon-192.png'
];

/* Prefissi serviti da Django come file statici: /<app>/s/... */
function eStatico(url) {
	return url.pathname.indexOf('/s/') !== -1 &&
		/\.(css|js|png|gif|jpg|jpeg|svg|ico|woff2?)$/.test(url.pathname);
}

self.addEventListener('install', function (e) {
	e.waitUntil(
		caches.open(VERSIONE).then(function (cache) {
			return cache.addAll(PRECACHE);
		}).then(function () {
			return self.skipWaiting();
		})
	);
});

self.addEventListener('activate', function (e) {
	e.waitUntil(
		caches.keys().then(function (nomi) {
			return Promise.all(nomi.map(function (n) {
				if (n !== VERSIONE) {
					return caches.delete(n);
				}
			}));
		}).then(function () {
			return self.clients.claim();
		})
	);
});

self.addEventListener('fetch', function (e) {
	var req = e.request;
	if (req.method !== 'GET') {
		return;
	}
	var url = new URL(req.url);
	if (url.origin !== self.location.origin) {
		return;
	}

	if (req.mode === 'navigate') {
		e.respondWith(
			fetch(req).catch(function () {
				return caches.match(OFFLINE_URL);
			})
		);
		return;
	}

	if (eStatico(url)) {
		e.respondWith(
			caches.match(req).then(function (risposta) {
				var rete = fetch(req).then(function (fresca) {
					if (fresca && fresca.status === 200) {
						var copia = fresca.clone();
						caches.open(VERSIONE).then(function (cache) {
							cache.put(req, copia);
						});
					}
					return fresca;
				}).catch(function () {
					return risposta;
				});
				return risposta || rete;
			})
		);
	}
});
