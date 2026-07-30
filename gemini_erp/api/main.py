"""FastAPI app for the Gemini ERP mobile companion (read-first).

Run from the gemini_erp/ folder:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

Reads the same GEMINI_DB_URL as the desktop app (so it hits the shared SQL
Server) and GEMINI_JWT_SECRET for signing tokens. The API is the only process a
phone talks to — SQL Server is never exposed directly.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import router as auth_router
from api.config import CORS_ORIGINS
from api.routers import dashboard, documents, gst, invoices, outstanding, stock

app = FastAPI(title="Gemini ERP API", version="1.0", description="Read-first mobile companion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # auth travels in the Authorization header, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(dashboard.router)
app.include_router(outstanding.router)
app.include_router(stock.router)
app.include_router(invoices.router)
app.include_router(gst.router)
app.include_router(documents.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}


# Serve the installable PWA (M29b) from the same origin as the API, so the app
# has no CORS to negotiate and there is a single HTTPS endpoint to secure. The
# API routes above are registered first, so /api/* always wins; everything else
# (index.html, app.js, sw.js, manifest, icons) is served from static/.
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="pwa")
