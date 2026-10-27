// 每日新闻 PWA：网络优先，断网回退缓存
var CACHE = 'sanjianshi-v2';
self.addEventListener('install', function (e) { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).then(function (r) {
    var cp = r.clone();
    caches.open(CACHE).then(function (c) { c.put(e.request, cp); });
    return r;
  }).catch(function () { return caches.match(e.request); }));
});
