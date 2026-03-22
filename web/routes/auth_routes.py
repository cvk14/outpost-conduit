"""Authentication routes for Outpost Conduit Web UI."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.app import get_settings
from web.auth import verify_password, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate a user and return a JWT token.

    Returns 401 if username doesn't match or password is incorrect.
    """
    settings = get_settings()
    if body.username != settings["admin_user"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(body.password, settings["admin_password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(body.username, settings["jwt_secret"])
    return {"token": token}
