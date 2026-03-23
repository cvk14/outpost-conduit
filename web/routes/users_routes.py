"""User management and WebAuthn passkey routes."""

import base64
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

import webauthn
from webauthn.helpers import (
    bytes_to_base64url,
    base64url_to_bytes,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from web.app import require_auth, get_settings
from web.auth import create_token
from web import users

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_auth)])
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory challenge store (per-session)
_challenges: dict = {}

RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
RP_NAME = "Outpost Conduit"


def _get_origin(request: Request) -> str:
    """Determine the origin from the request."""
    host = request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto", "http")
    if ":" in host and host.split(":")[1] == "443":
        scheme = "https"
    if host.endswith(".io") or host.endswith(".com") or host.endswith(".net"):
        scheme = "https"
    return f"{scheme}://{host}"


# --- User CRUD ---

class UserCreate(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    password: str


@router.get("")
async def list_all_users():
    return users.list_users()


@router.post("")
async def create_user(body: UserCreate):
    try:
        users.create_user(body.username, body.password)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": "ok"}


@router.delete("/{username}")
async def delete_user(username: str):
    try:
        users.delete_user(username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@router.put("/{username}/password")
async def change_password(username: str, body: PasswordChange):
    try:
        users.change_password(username, body.password)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "ok"}


# --- Passkey Registration ---

@router.post("/{username}/passkey/register-options")
async def passkey_register_options(username: str, request: Request):
    """Generate WebAuthn registration options for a user."""
    user = users.get_user(username)
    if not user:
        raise HTTPException(404, f"User '{username}' not found")

    existing_creds = [
        webauthn.helpers.structs.PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(pk["credential_id"])
        )
        for pk in user.get("passkeys", [])
    ]

    options = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=username.encode(),
        user_name=username,
        user_display_name=username,
        exclude_credentials=existing_creds,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    # Store challenge for verification
    _challenges[username] = options.challenge

    return json.loads(webauthn.options_to_json(options))


class PasskeyRegisterBody(BaseModel):
    credential: dict
    name: str = ""


@router.post("/{username}/passkey/register")
async def passkey_register(username: str, body: PasskeyRegisterBody, request: Request):
    """Verify and store a new passkey for a user."""
    challenge = _challenges.pop(username, None)
    if not challenge:
        raise HTTPException(400, "No pending registration challenge")

    try:
        verification = webauthn.verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=_get_origin(request),
        )
    except Exception as e:
        raise HTTPException(400, f"Registration failed: {e}")

    users.add_passkey(
        username=username,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
        name=body.name,
    )

    return {"status": "ok"}


@router.delete("/{username}/passkey/{credential_id}")
async def remove_passkey(username: str, credential_id: str):
    try:
        users.remove_passkey(username, credential_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "ok"}


# --- Passkey Authentication (no auth required) ---

@auth_router.post("/passkey/auth-options")
async def passkey_auth_options():
    """Generate WebAuthn authentication options."""
    all_passkeys = users.get_all_passkeys()

    allow_creds = [
        webauthn.helpers.structs.PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(pk["credential_id"])
        )
        for pk in all_passkeys
    ]

    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_creds,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    _challenges["__auth__"] = options.challenge

    return json.loads(webauthn.options_to_json(options))


class PasskeyAuthBody(BaseModel):
    credential: dict


@auth_router.post("/passkey/authenticate")
async def passkey_authenticate(body: PasskeyAuthBody, request: Request):
    """Verify a passkey authentication and return a JWT."""
    challenge = _challenges.pop("__auth__", None)
    if not challenge:
        raise HTTPException(400, "No pending authentication challenge")

    # Find the credential
    cred_id_b64 = body.credential.get("id", "")
    all_passkeys = users.get_all_passkeys()
    matching = [pk for pk in all_passkeys if pk["credential_id"] == cred_id_b64]
    if not matching:
        raise HTTPException(400, "Unknown credential")

    pk = matching[0]

    try:
        verification = webauthn.verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=_get_origin(request),
            credential_public_key=base64url_to_bytes(pk["public_key"]),
            credential_current_sign_count=pk["sign_count"],
        )
    except Exception as e:
        raise HTTPException(400, f"Authentication failed: {e}")

    users.update_passkey_sign_count(cred_id_b64, verification.new_sign_count)

    settings = get_settings()
    token = create_token(pk["username"], settings["jwt_secret"])
    return {"token": token, "username": pk["username"]}
