"""User management — multi-admin with password + passkey support."""

import json
import os
import secrets
from pathlib import Path

import bcrypt

USERS_PATH = Path(__file__).parent.parent / "users.json"


def _load() -> dict:
    if USERS_PATH.is_file():
        return json.loads(USERS_PATH.read_text())
    return {"users": {}}


def _save(data: dict) -> None:
    USERS_PATH.write_text(json.dumps(data, indent=2))


def list_users() -> list[dict]:
    """Return list of users (without password hashes or credential secrets)."""
    data = _load()
    result = []
    for username, info in data.get("users", {}).items():
        result.append({
            "username": username,
            "has_password": bool(info.get("password_hash")),
            "passkey_count": len(info.get("passkeys", [])),
            "created": info.get("created", ""),
        })
    return result


def get_user(username: str) -> dict | None:
    data = _load()
    return data.get("users", {}).get(username)


def create_user(username: str, password: str) -> None:
    data = _load()
    if username in data.get("users", {}):
        raise ValueError(f"User '{username}' already exists")
    if "users" not in data:
        data["users"] = {}
    data["users"][username] = {
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "passkeys": [],
        "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save(data)


def delete_user(username: str) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"User '{username}' not found")
    if len(data["users"]) <= 1:
        raise ValueError("Cannot delete the last user")
    del data["users"][username]
    _save(data)


def change_password(username: str, new_password: str) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"User '{username}' not found")
    data["users"][username]["password_hash"] = bcrypt.hashpw(
        new_password.encode(), bcrypt.gensalt()
    ).decode()
    _save(data)


def verify_password(username: str, password: str) -> bool:
    user = get_user(username)
    if not user or not user.get("password_hash"):
        return False
    return bcrypt.checkpw(password.encode(), user["password_hash"].encode())


def add_passkey(username: str, credential_id: str, public_key: str, sign_count: int, name: str = "") -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"User '{username}' not found")
    data["users"][username].setdefault("passkeys", []).append({
        "credential_id": credential_id,
        "public_key": public_key,
        "sign_count": sign_count,
        "name": name or f"Passkey {len(data['users'][username]['passkeys']) + 1}",
        "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save(data)


def remove_passkey(username: str, credential_id: str) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"User '{username}' not found")
    passkeys = data["users"][username].get("passkeys", [])
    data["users"][username]["passkeys"] = [
        p for p in passkeys if p["credential_id"] != credential_id
    ]
    _save(data)


def get_all_passkeys() -> list[dict]:
    """Return all passkeys across all users (for authentication lookup)."""
    data = _load()
    result = []
    for username, info in data.get("users", {}).items():
        for pk in info.get("passkeys", []):
            result.append({**pk, "username": username})
    return result


def update_passkey_sign_count(credential_id: str, new_count: int) -> None:
    data = _load()
    for info in data.get("users", {}).values():
        for pk in info.get("passkeys", []):
            if pk["credential_id"] == credential_id:
                pk["sign_count"] = new_count
                _save(data)
                return


def migrate_from_env() -> None:
    """Migrate single-user from .env to users.json if needed."""
    if USERS_PATH.is_file():
        data = _load()
        if data.get("users"):
            return  # Already have users

    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if admin_hash:
        data = {"users": {
            admin_user: {
                "password_hash": admin_hash,
                "passkeys": [],
                "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            }
        }}
        _save(data)
