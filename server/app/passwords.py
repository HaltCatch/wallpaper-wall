"""Password primitives for local accounts.

The application deliberately keeps password handling outside HTTP handlers
and SQLite queries.  The encoded value includes every parameter required for
verification so the format can be upgraded without changing user records.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P)
    return "$".join((
        "scrypt",
        str(_N),
        str(_R),
        str(_P),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt_bytes = base64.urlsafe_b64decode(salt.encode("ascii"))
        expected_bytes = base64.urlsafe_b64decode(expected.encode("ascii"))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt_bytes, n=int(n), r=int(r), p=int(p), dklen=len(expected_bytes))
    except (ValueError, TypeError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(actual, expected_bytes)
