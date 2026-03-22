"""Settings and health monitor API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from web.app import require_auth
from web.health_monitor import load_config, save_config, send_alert_email

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_auth)],
)


class SettingsUpdate(BaseModel):
    health_check_interval_minutes: Optional[int] = None
    smtp_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_to: Optional[str] = None
    smtp_tls: Optional[bool] = None


@router.get("")
async def get_settings():
    config = load_config()
    # Mask password in response
    if config.get("smtp_password"):
        config["smtp_password"] = "********"
    return config


@router.put("")
async def update_settings(body: SettingsUpdate):
    config = load_config()
    updates = body.model_dump(exclude_none=True)

    # Don't overwrite password with mask
    if updates.get("smtp_password") == "********":
        del updates["smtp_password"]

    config.update(updates)
    save_config(config)

    # Restart health monitor with new interval
    from web.app import get_health_monitor
    monitor = get_health_monitor()
    if monitor:
        monitor.stop()
        monitor.start()

    return {"status": "ok"}


@router.post("/test-email")
async def test_email():
    config = load_config()
    success = send_alert_email(
        config,
        "Outpost Conduit — Test Email",
        "This is a test email from Outpost Conduit.\n\n"
        "If you received this, your SMTP settings are configured correctly."
    )
    return {"status": "ok" if success else "failed", "sent": success}


@router.get("/health")
async def get_health():
    from web.app import get_health_monitor
    monitor = get_health_monitor()
    if monitor:
        return monitor.latest_results
    return {}
