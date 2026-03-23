"""FastAPI application for Outpost Conduit Web UI."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.auth import decode_token
from web.inventory import InventoryManager
from web.stats import StatsCollector
from web.health_monitor import HealthMonitor

# Module-level settings populated during lifespan startup.
_settings: dict = {}
_inventory: InventoryManager | None = None
_collector: StatsCollector | None = None
_health_monitor: HealthMonitor | None = None

WEB_DIR = Path(__file__).parent


def get_settings() -> dict:
    """Return the current application settings dict."""
    return _settings


def get_inventory() -> InventoryManager:
    """Return the InventoryManager singleton (initialised during lifespan)."""
    return _inventory


def get_collector() -> StatsCollector:
    """Return the StatsCollector singleton (initialised during lifespan)."""
    return _collector


def get_health_monitor() -> HealthMonitor:
    """Return the HealthMonitor singleton (initialised during lifespan)."""
    return _health_monitor


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
    global _inventory, _collector, _health_monitor

    _settings["admin_user"] = os.environ.get("ADMIN_USER", "admin")
    _settings["admin_password_hash"] = os.environ.get("ADMIN_PASSWORD_HASH", "")
    _settings["jwt_secret"] = os.environ.get("JWT_SECRET", "change-me")
    _settings["inventory_path"] = os.environ.get("INVENTORY_PATH", "sites.yaml")
    _settings["output_dir"] = os.environ.get("OUTPUT_DIR", "output")

    # Migrate single-user from .env to multi-user system
    from web.users import migrate_from_env
    migrate_from_env()

    _inventory = InventoryManager(_settings["inventory_path"])
    _collector = StatsCollector(
        output_dir=_settings["output_dir"],
        get_sites=lambda: _inventory.get_sites(),
    )
    _collector.start()
    _health_monitor = HealthMonitor(
        get_sites=lambda: _inventory.get_sites(),
        get_inventory_path=lambda: _settings["inventory_path"],
        get_output_dir=lambda: _settings["output_dir"],
    )
    _health_monitor.start()
    yield
    _health_monitor.stop()
    _collector.stop()
    _inventory = None
    _collector = None
    _settings.clear()


app = FastAPI(title="Outpost Conduit", lifespan=lifespan)

# Mount static files.
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# Include routers (import here to avoid circular imports).
from web.routes.auth_routes import router as auth_router  # noqa: E402
from web.routes.status_routes import router as status_router  # noqa: E402
from web.routes.sites_routes import router as sites_router, hub_router, download_router  # noqa: E402
from web.routes.deploy_routes import router as deploy_router, ssh_ws_router  # noqa: E402
from web.routes.enroll_routes import router as enroll_router  # noqa: E402
from web.routes.diagnostics_routes import router as diagnostics_router  # noqa: E402
from web.routes.settings_routes import router as settings_router  # noqa: E402
from web.routes.mcast_capture_routes import router as mcast_capture_router  # noqa: E402
from web.routes.users_routes import router as users_router, auth_router as passkey_auth_router  # noqa: E402

app.include_router(auth_router)
app.include_router(status_router)
app.include_router(sites_router)
app.include_router(download_router)
app.include_router(hub_router)
app.include_router(deploy_router)
app.include_router(ssh_ws_router)
app.include_router(enroll_router)
app.include_router(diagnostics_router)
app.include_router(settings_router)
app.include_router(mcast_capture_router)
app.include_router(users_router)
app.include_router(passkey_auth_router)


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
