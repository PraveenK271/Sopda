"""API configuration read from the environment."""

import logging
import os

logger = logging.getLogger(__name__)

# Signing key for JWT access tokens. MUST be set in production (a long random
# string). A fixed dev fallback keeps tokens stable across a local run but is
# unsafe for deployment — we warn loudly if it is used.
_DEV_SECRET = "gemini-erp-dev-insecure-secret-change-me"
JWT_SECRET = os.getenv("GEMINI_JWT_SECRET", _DEV_SECRET)
if JWT_SECRET == _DEV_SECRET:
    logger.warning(
        "GEMINI_JWT_SECRET is not set - using an insecure development key. "
        "Set GEMINI_JWT_SECRET before deploying the API."
    )

JWT_ALGORITHM = "HS256"
JWT_TTL_MINUTES = int(os.getenv("GEMINI_JWT_TTL_MINUTES", "720"))  # default 12h

# CORS origins allowed to call the API (the PWA's origin). Comma-separated env
# var; defaults to "*" for dev. Tokens travel in the Authorization header (not
# cookies), so "*" does not expose credentials, but restrict it in production.
CORS_ORIGINS = [o.strip() for o in os.getenv("GEMINI_API_CORS_ORIGINS", "*").split(",") if o.strip()]

# Login brute-force slowdown (mirrors the desktop dialog: 5 tries / 30s).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 30
