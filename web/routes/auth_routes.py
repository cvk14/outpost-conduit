"""Authentication routes for Outpost Conduit Web UI."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.app import get_settings
from web.auth import create_token
from web import users

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate a user with password and return a JWT token."""
    if not users.verify_password(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    settings = get_settings()
    token = create_token(body.username, settings["jwt_secret"])
    return {"token": token}
