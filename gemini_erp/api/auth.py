"""API authentication: JWT issue/verify + RBAC dependencies.

Reuses the desktop AuthService (bcrypt verify, same role permissions) — no auth
logic is duplicated. Tokens are stateless JWTs; every request re-loads the user
from the DB so a deactivated account or changed role takes effect immediately.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import false, true
from sqlalchemy.orm import joinedload

from api.config import (
    JWT_ALGORITHM,
    JWT_SECRET,
    JWT_TTL_MINUTES,
    LOGIN_LOCK_SECONDS,
    LOGIN_MAX_ATTEMPTS,
)
from database import get_session
from models import User
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])
_auth_service = AuthService()
_bearer = HTTPBearer(auto_error=False)

# In-memory per-username failure tracker (single API process). Not persistence —
# just a brute-force slowdown mirroring the desktop 5-attempts/30s lockout.
_failures: dict[str, list[float]] = {}


def _enforce_rate_limit(username: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(username, []) if now - t < LOGIN_LOCK_SECONDS]
    _failures[username] = recent
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        retry = int(LOGIN_LOCK_SECONDS - (now - recent[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {retry} seconds.",
        )


def _record_failure(username: str) -> None:
    _failures.setdefault(username, []).append(time.time())


def _clear_failures(username: str) -> None:
    _failures.pop(username, None)


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_TTL_MINUTES)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.name if user.role else None,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Resolve the bearer token to a live, active user (role eager-loaded)."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = _decode_token(credentials.credentials)
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    session = get_session()
    try:
        user = (
            session.query(User)
            .options(joinedload(User.role))
            .filter(User.id == user_id, User.is_active == true(), User.is_deleted == false())
            .first()
        )
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
        _ = user.role.permissions  # force-load before detaching
        session.expunge(user)
        return user
    finally:
        session.close()


def require_permission(module_key: str):
    """Dependency factory: 403 unless the current user's role permits module_key."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not AuthService.has_permission(user, module_key):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this resource")
        return user

    return checker


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str | None
    permitted_modules: list[str]
    must_change_password: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _user_out(user: User) -> UserOut:
    try:
        permitted = json.loads(user.role.permissions) if user.role else []
    except (ValueError, TypeError):
        permitted = []
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role.name if user.role else None,
        permitted_modules=permitted,
        must_change_password=bool(user.must_change_password),
    )


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    username = (body.username or "").strip()
    _enforce_rate_limit(username)

    session = get_session()
    try:
        user = _auth_service.authenticate(session, username, body.password)
    finally:
        session.close()

    if user is None:
        _record_failure(username)
        # Same generic message for unknown-user and wrong-password.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    _clear_failures(username)

    # Block accounts that still owe a password change (e.g. the seeded default
    # admin, or an admin-reset account). This runs only AFTER a correct password,
    # so it leaks nothing about which usernames exist. It stops a fresh
    # deployment's well-known default admin from getting an API token before the
    # password has been changed on the desktop.
    if user.must_change_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Password change required. Log in to the desktop app to set a new "
            "password before using the mobile app.",
        )

    token = create_access_token(user)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
