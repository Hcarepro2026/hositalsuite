"""Install-on-phone (PWA) bits: manifest + service worker.

Per-hospital name and colours. Same software, each hospital's own icon
label on the home screen.
"""
from __future__ import annotations

import json

from flask import Response, current_app, make_response, url_for


def manifest_payload(org, settings: dict) -> dict:
    name = (getattr(org, "name", None) or "Hospital Suite").strip()[:80]
    short = name if len(name) <= 12 else (getattr(org, "code", None) or name[:12])
    theme = (settings or {}).get("brand_primary") or "#0e5a8a"
    bg = "#0a4468"
    return {
        "name": name,
        "short_name": str(short)[:12],
        "description": f"{name} — book a visit, join the queue, tell us a problem.",
        "start_url": "/welcome?source=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": bg,
        "theme_color": theme,
        "lang": "en-NG",
        "dir": "ltr",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-maskable.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "categories": ["medical", "health"],
        "prefer_related_applications": False,
    }


def manifest_response(org, settings: dict) -> Response:
    body = json.dumps(manifest_payload(org, settings), ensure_ascii=True)
    resp = make_response(body)
    resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


SW_JS = r"""/* Hospital Suite — keep the last screens on a weak signal. */
const CACHE = "hs-shell-__VERSION__";
const SHELL = [
  "/offline",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;
  // Never cache staff writes, APIs, or sign-in posts.
  if (url.pathname.indexOf("/api/") === 0) return;
  if (url.pathname.indexOf("/admin") === 0) return;

  // CSS/JS must be network-first. Cache-first froze the old look on phones
  // after we changed Sign in (giant logo, eye sitting under the box).
  if (url.pathname.indexOf("/static/") === 0) {
    event.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return caches.match(req); })
    );
    return;
  }

  event.respondWith(
    fetch(req).then(function (res) {
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) {
        return hit || caches.match("/offline");
      });
    })
  );
});
"""


def service_worker_response() -> Response:
    ver = str(current_app.config.get("APP_VERSION") or "1.7.11")
    resp = make_response(SW_JS.replace("__VERSION__", ver.replace(".", "-")))
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp
