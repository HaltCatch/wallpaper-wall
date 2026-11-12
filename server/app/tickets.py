"""Short-lived signed download tickets for private media.

A ticket lets the browser hand a plain URL to the desktop wallpaper helper
without that helper holding a session cookie.  It is scoped to one media
object and expires quickly; it is not a general session mechanism.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def issue_ticket(secret: str, media_id: str, ttl_seconds: int) -> str:
    payload = json.dumps({"media_id": media_id, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_ticket(secret: str, media_id: str, token: str | None) -> bool:
    if not token or not secret:
        return False
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return hmac.compare_digest(expected, actual) and data.get("media_id") == media_id and int(data.get("exp", 0)) >= int(time.time())
