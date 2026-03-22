"""JWT + bcrypt authentication utilities for Outpost Conduit Web UI."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


def hash_password(password: str) -> str:
    """Hash a password with bcrypt and return the hash as a string."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(username: str, secret: str, expire_hours: int = 24) -> str:
    """Create a JWT token with HS256 signing.

    Args:
        username: Subject claim for the token.
        secret: HMAC secret key.
        expire_hours: Hours until expiry (negative values create already-expired tokens).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """Decode and verify a JWT token.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is malformed or signature is invalid.
    """
    return jwt.decode(token, secret, algorithms=["HS256"])
