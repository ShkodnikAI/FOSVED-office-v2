"""Encrypt/decrypt values stored in secrets_store using a master key from env.

The master key never touches the database — only Render environment.
If it is missing, encryption functions raise rather than silently
storing plaintext (fail closed, not fail open).
"""
import os
import logging

logger = logging.getLogger("fosved.secrets")

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = None
    logger.critical("cryptography package not installed — secrets encryption unavailable")

_MASTER_KEY = os.environ.get("SECRETS_MASTER_KEY", "")
_fernet = Fernet(_MASTER_KEY.encode()) if _MASTER_KEY and Fernet else None


def is_configured():
    """Return True if SECRETS_MASTER_KEY is set and cryptography is available."""
    return _fernet is not None


def encrypt_value(plain: str) -> str:
    """Encrypt a plaintext value. Raises if master key not configured."""
    if not _fernet:
        raise RuntimeError("SECRETS_MASTER_KEY not set — cannot encrypt")
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_value(token: str):
    """Decrypt an encrypted token. Returns None on any failure (wrong key, corrupt data)."""
    if not _fernet:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, Exception):
        return None


def mask_value(plain: str) -> str:
    """For display only — never the real value. Returns a masked representation."""
    if not plain or len(plain) < 8:
        return "\u2022" * 8  # bullet chars
    return plain[:3] + "\u2026" + plain[-4:]  # first3…last4
