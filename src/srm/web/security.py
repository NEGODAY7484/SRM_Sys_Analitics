"""Password hashing utilities (PBKDF2-HMAC, stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    """Hash password using PBKDF2-HMAC-SHA256.

    Stored format:
        pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
    """

    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    salt_s = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    hash_s = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt_s}${hash_s}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(it_s)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
