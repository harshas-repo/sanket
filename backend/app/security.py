"""Authentication primitives.

Deliberately small for V1 (as specified): password hashing via PBKDF2 from the
standard library and stateless HMAC-signed bearer tokens. No external JWT library,
no third-party identity provider to wire up for a demo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from backend.app.config import settings

_ITERATIONS = 120_000
_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
    )
    return hmac.compare_digest(candidate.hex(), digest)


def _sign(payload: str) -> str:
    return hmac.new(
        settings.resolved_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def create_token(subject: dict[str, str], ttl_hours: int | None = None) -> str:
    body = dict(subject)
    body["exp"] = int(time.time()) + (ttl_hours or settings.token_ttl_hours) * 3600
    body["jti"] = secrets.token_hex(8)
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8")).decode()
    return f"{encoded}.{_sign(encoded)}"


@dataclass
class TokenClaims:
    subject: dict[str, str]
    expired: bool = False
    invalid: bool = False

    @property
    def user_id(self) -> str | None:
        return self.subject.get("sub")


def read_token(token: str) -> TokenClaims:
    try:
        encoded, signature = token.rsplit(".", 1)
    except ValueError:
        return TokenClaims({}, invalid=True)
    if not hmac.compare_digest(signature, _sign(encoded)):
        return TokenClaims({}, invalid=True)
    try:
        body = json.loads(base64.urlsafe_b64decode(encoded.encode("utf-8")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return TokenClaims({}, invalid=True)
    if int(body.get("exp", 0)) < time.time():
        return TokenClaims(body, expired=True)
    return TokenClaims(body)


def parse_authorization(header: str | None) -> TokenClaims | None:
    if not header:
        return None
    parts = header.split()
    raw = parts[1] if len(parts) == 2 and parts[0].lower() in {"bearer", "token"} else parts[0]
    return read_token(raw.strip())
