"""API configuration read from the environment."""

import logging
import os

from dotenv import load_dotenv

# Load gemini_erp/.env (the same file database.py reads GEMINI_DB_URL from) so
# GEMINI_JWT_SECRET can be set there. Done here because api.config may be
# imported before database.py has run its own load_dotenv().
_GEMINI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_GEMINI_DIR, ".env"))
load_dotenv()

logger = logging.getLogger(__name__)

# Signing key for JWT access tokens. REQUIRED — there is deliberately NO
# hardcoded fallback: a shipped default key would let anyone who has seen the
# source forge a valid token for any user/role (full auth bypass). The API
# refuses to start without it.
JWT_SECRET = os.getenv("GEMINI_JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "GEMINI_JWT_SECRET is not set. Generate a long random value, e.g.\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
        "and set it in the environment or gemini_erp/.env before starting the API."
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
