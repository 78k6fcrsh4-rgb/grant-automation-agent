"""Password hashing (bcrypt) and JWT issuing/verification. No external identity
provider — self-contained and portable to any host."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

ALGORITHM = "HS256"


def _secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if not key:
        # Dev fallback so local runs work; production MUST set SECRET_KEY.
        return "dev-insecure-change-me-in-production"
    return key


def token_ttl_minutes() -> int:
    try:
        return int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    except ValueError:
        return 480


def hash_password(plain: str) -> str:
    # bcrypt has a 72-byte limit; encode and truncate defensively.
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, email: str, tenant_id: int, role: str,
                        expires_minutes: Optional[int] = None) -> str:
    ttl = expires_minutes if expires_minutes is not None else token_ttl_minutes()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
