from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        seed = settings.credentials_encryption_key or settings.secret_key
        # Derive a valid 32-byte urlsafe-base64 Fernet key from any string seed.
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        _fernet = Fernet(key)
    return _fernet


def encrypt_dict(data: dict[str, Any]) -> str:
    """Encrypt a credentials dict to an opaque string for DB storage."""
    raw = json.dumps(data).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("utf-8")


def decrypt_dict(token: str) -> dict[str, Any]:
    """Decrypt a stored credentials string back into a dict."""
    try:
        raw = _get_fernet().decrypt(token.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except InvalidToken:
        return {}
