"""Milestone 29b check: the PWA is served by the API and API routes still win.

The visual/interaction test is manual (load on a phone, log in, tap around).
This automated check verifies the wiring:
- the app shell + PWA assets are served from the same origin
- the manifest is valid JSON with icons; the icons are real PNGs
- the service worker is served
- mounting the static app at "/" did NOT shadow the API (/api/* still routes,
  and a protected route without a token is still 401, not a static 404)

Run with: python check_milestone29b.py
"""

import json
import os
import warnings

os.environ.setdefault("GEMINI_JWT_SECRET", "check-suite-jwt-secret")
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def main():
    # App shell.
    r = client.get("/")
    assert r.status_code == 200, r.status_code
    assert "text/html" in r.headers.get("content-type", ""), r.headers.get("content-type")
    assert "Gemini" in r.text and "/app.js" in r.text, "index.html missing markers"
    print("App shell served at / (index.html)")

    # JS + CSS.
    for path, marker in [("/app.js", "viewDashboard"), ("/styles.css", ".metric")]:
        rr = client.get(path)
        assert rr.status_code == 200 and marker in rr.text, f"{path} not served correctly"
    print("app.js + styles.css served")

    # Manifest is valid JSON with icons.
    rm = client.get("/manifest.webmanifest")
    assert rm.status_code == 200, rm.status_code
    manifest = json.loads(rm.text)
    assert manifest["start_url"] == "/" and len(manifest["icons"]) >= 2, manifest
    print("manifest.webmanifest valid with icons")

    # Service worker.
    rs = client.get("/sw.js")
    assert rs.status_code == 200 and "gemini-pwa" in rs.text, "sw.js not served"
    print("sw.js served")

    # Icons are real PNGs.
    for icon in ("/icon-192.png", "/icon-512.png"):
        ri = client.get(icon)
        assert ri.status_code == 200 and ri.content[:8] == PNG_SIG, f"{icon} not a PNG"
    print("icons served as PNG")

    # API still wins under the "/" mount.
    assert client.get("/api/health").json() == {"status": "ok"}, "API health broke under mount"
    assert client.get("/api/stock").status_code == 401, "protected API route not enforced"
    print("API routes still win over the static mount (/api/health 200, /api/stock 401)")

    print("PASS")


if __name__ == "__main__":
    main()
