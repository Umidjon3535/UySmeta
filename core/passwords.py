"""
Parollarni scrypt bilan xeshlash. Format asl versiya (Node.js crypto.scrypt) bilan bir xil:
"scrypt$<salt base64>$<hash base64>", N=16384, r=8, p=1 — eski parollar bilan kirish ishlaydi.
"""

import base64
import hashlib
import hmac
import secrets

KEY_LENGTH = 64
_N, _R, _P = 16384, 8, 1


def _scrypt(password: str, salt: bytes, length: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=length, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, KEY_LENGTH)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    parts = (stored or "").split("$")
    if len(parts) != 3 or parts[0] != "scrypt" or not parts[1] or not parts[2]:
        return False
    try:
        salt = base64.b64decode(parts[1])
        expected = base64.b64decode(parts[2])
    except ValueError:
        return False
    actual = _scrypt(password, salt, len(expected))
    return hmac.compare_digest(actual, expected)
