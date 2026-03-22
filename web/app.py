"""FastAPI application for Outpost Conduit Web UI."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.auth import decode_token

# Module-level settings populated during lifespan startup.
_settings: dict = {}

WEB_DIR = Path(__file__).parent


def get_settings() -> dict:
    """Return the current application settings dict."""
    return _settings


def require_auth(request: Request) -> dict:
    """FastAPI dependency: extract and verify JWT from Authorization header.

    Expects header format: ``Authorization: Bearer <token>``

    Returns:
        Decoded JWT payload dict.

    Raises:
        HTTPException 401 if the header is missing, malformed, or the token is invalid.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(token, _settings["jwt_secret"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load settings from environment variables on startup."""
    _settings["admin_user"] = os.environ.get("ADMIN_USER", "admin")
    _settings["admin_password_hash"] = os.environ.get("ADMIN_PASSWORD_HASH", "")
    _settings["jwt_secret"] = os.environ.get("JWT_SECRET", "change-me")
    _settings["inventory_path"] = os.environ.get("INVENTORY_PATH", "sites.yaml")
    _settings["output_dir"] = os.environ.get("OUTPUT_DIR", "output")
    yield
    _settings.clear()


app = FastAPI(title="Outpost Conduit", lifespan=lifespan)

# Mount static files.
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# Include routers (import here to avoid circular imports).
from web.routes.auth_routes import router as auth_router  # noqa: E402

app.include_router(auth_router)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main application page."""
    html_path = WEB_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve the login page."""
    html_path = WEB_DIR / "templates" / "login.html"
    return HTMLResponse(content=html_path.read_text())
