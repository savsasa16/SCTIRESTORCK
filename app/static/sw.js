const CACHE_NAME = 'sc-stock-cache-v1';
const urlsToCache = [
    '/',
    '/static/style.css',
    // เพิ่มลิงก์ของไอคอนและไฟล์อื่นๆ ที่จำเป็น
    'https://res.cloudinary.com/doi8m4e1o/image/upload/v1749883714/favicon-96x96_e50eyw.png',
    'https://res.cloudinary.com/doi8m4e1o/image/upload/v1749883713/favicon_mq1iqu.svg',
    'https://res.cloudinary.com/doi8m4e1o/image/upload/v1749883714/favicon_spqmcc.ico',
    'https://res.cloudinary.com/doi8m4e1o/image/upload/v1749883714/apple-touch-icon_c2me0k.png',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
        .then(cache => {
            console.log('Opened cache');
            return cache.addAll(urlsToCache);
        })
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
        .then(response => {
            if (response) {
                return response;
            }
            return fetch(event.request);
        })
    );
});