from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Passwords ──────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


# ── JWTs ───────────────────────────────────────────────────────────────────


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.jwt_expiration_hours)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_user_token(user_id: str, email: str) -> str:
    return create_access_token({"sub": user_id, "email": email})


def create_state_token(user_id: str, return_origin: Optional[str] = None) -> str:
    """Short-lived signed token used as the OAuth `state` param (CSRF guard).

    Also carries the frontend origin the flow was started from, so the
    callback can redirect back to wherever the user actually is (e.g. a
    local Vite dev server on :5173) instead of a hardcoded FRONTEND_URL —
    redirecting to the wrong origin drops the user's session, since
    localStorage is scoped per-origin.
    """
    data = {"sub": user_id, "purpose": "oauth_state"}
    if return_origin:
        data["return_origin"] = return_origin
    return create_access_token(data, timedelta(minutes=10))


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        logger.debug("Token verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── FastAPI dependencies ─────────────────────────────────────────────────────


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Use with Depends(get_current_user) — returns the decoded JWT payload."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return verify_token(credentials.credentials)


async def get_current_user_id(user: dict = Depends(get_current_user)) -> str:
    """Use with Depends(get_current_user_id) — returns just the user id string."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return user_id


async def optional_user_id(request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            return None
        payload = verify_token(token)
        return payload.get("sub")
    except (ValueError, JWTError, HTTPException):
        return None
