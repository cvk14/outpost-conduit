"""Tests for web.auth JWT + bcrypt authentication module."""

import pytest

from web.auth import hash_password, verify_password, create_token, decode_token


class TestPasswordHashing:
    """Tests for bcrypt password hashing and verification."""

    def test_hash_and_verify(self):
        """hash_password produces a hash that verify_password accepts."""
        password = "correct-horse-battery-staple"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """verify_password rejects an incorrect password."""
        hashed = hash_password("real-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_is_bcrypt_format(self):
        """hash_password returns a string starting with '$2b$'."""
        hashed = hash_password("test")
        assert hashed.startswith("$2b$")


class TestJWT:
    """Tests for JWT token creation and decoding."""

    def test_create_and_decode(self):
        """create_token returns a JWT that decode_token can read back."""
        secret = "test-secret-key"
        token = create_token("admin", secret, expire_hours=1)
        payload = decode_token(token, secret)
        assert payload["sub"] == "admin"
        assert "exp" in payload

    def test_expired_token_raises(self):
        """decode_token raises an exception for an expired token."""
        secret = "test-secret-key"
        token = create_token("admin", secret, expire_hours=-1)
        with pytest.raises(Exception):
            decode_token(token, secret)

    def test_invalid_token_raises(self):
        """decode_token raises an exception for a garbage token."""
        with pytest.raises(Exception):
            decode_token("not.a.real.token", "secret")
