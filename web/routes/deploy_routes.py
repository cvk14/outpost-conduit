"""Deploy and remote-management routes for Outpost Conduit Web UI.

Provides REST endpoints for pushing configs, running setup scripts,
restarting services, checking status, and rebooting remote sites.
Also exposes a WebSocket endpoint for interactive SSH sessions.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from web.app import get_inventory, get_settings, require_auth
from web.auth import decode_token
from web.ssh_manager import get_command, run_ssh_command, scp_directory, stream_ssh_command

logger = logging.getLogger(__name__)

# Project root — scripts/ lives alongside web/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# REST router — auth-protected site operations
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/sites",
    tags=["deploy"],
    dependencies=[Depends(require_auth)],
)


def _get_site_or_404(name: str) -> dict:
    """Look up a site by name or raise 404."""
    site = get_inventory().get_site(name)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Site '{name}' not found")
    return site


@router.post("/{name}/push")
async def push_configs(name: str):
    """SCP generated configs + setup script to remote ``/tmp/{name}/``."""
    site = _get_site_or_404(name)
    settings = get_settings()

    site_dir = os.path.join(settings["output_dir"], name)
    if not os.path.isdir(site_dir):
        raise HTTPException(
            status_code=404,
            detail=f"No generated configs for '{name}'. Run generate first.",
        )

    remote_dir = f"/tmp/{name}"
    result = await scp_directory(site, site_dir, remote_dir)
    if result.startswith("[ERROR]"):
        raise HTTPException(status_code=502, detail=result)

    # Also push the appropriate setup script
    site_type = site.get("type", "glinet")
    if site_type == "cradlepoint":
        script_name = "pi-setup.sh"
    else:
        script_name = "glinet-setup.sh"

    script_path = str(PROJECT_ROOT / "scripts" / script_name)
    if os.path.isfile(script_path):
        script_result = await scp_directory(site, script_path, remote_dir)
        if script_result.startswith("[ERROR]"):
            logger.warning("Failed to push setup script: %s", script_result)
            return {
                "status": "partial",
                "message": f"Configs pushed but setup script copy failed: {script_result}",
            }

    return {"status": "ok", "message": f"Configs pushed to {remote_dir}"}


@router.post("/{name}/setup")
async def run_setup(name: str):
    """Run the appropriate setup script on the remote site (120s timeout)."""
    site = _get_site_or_404(name)
    site_type = site.get("type", "glinet")

    if site_type == "cradlepoint":
        script = "pi-setup.sh"
    else:
        script = "glinet-setup.sh"

    remote_dir = f"/tmp/{name}"
    cmd = f"chmod +x {remote_dir}/{script} && {remote_dir}/{script} {remote_dir}"
    output = await run_ssh_command(site, cmd, timeout=120)

    if output.startswith("[ERROR]"):
        raise HTTPException(status_code=502, detail=output)

    return {"status": "ok", "output": output}


@router.post("/{name}/restart")
async def restart_services(name: str):
    """Restart WireGuard + GRETAP on the remote site."""
    site = _get_site_or_404(name)
    site_type = site.get("type", "glinet")

    try:
        cmd = get_command(site_type, "restart")
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No restart command for site type '{site_type}'",
        )

    output = await run_ssh_command(site, cmd, timeout=30)
    if output.startswith("[ERROR]"):
        raise HTTPException(status_code=502, detail=output)

    return {"status": "ok", "output": output}


@router.post("/{name}/status")
async def check_status(name: str):
    """Check WireGuard + GRETAP status on the remote site."""
    site = _get_site_or_404(name)
    site_type = site.get("type", "glinet")

    try:
        cmd = get_command(site_type, "status")
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No status command for site type '{site_type}'",
        )

    output = await run_ssh_command(site, cmd, timeout=30)
    if output.startswith("[ERROR]"):
        raise HTTPException(status_code=502, detail=output)

    return {"status": "ok", "output": output}


@router.post("/{name}/reboot")
async def reboot_site(name: str):
    """Reboot the remote site (10s timeout — may disconnect, that's OK)."""
    site = _get_site_or_404(name)
    site_type = site.get("type", "glinet")

    try:
        cmd = get_command(site_type, "reboot")
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No reboot command for site type '{site_type}'",
        )

    output = await run_ssh_command(site, cmd, timeout=10)
    # Reboot will almost certainly disconnect; that's fine.
    return {"status": "ok", "message": "Reboot command sent", "output": output}


# ---------------------------------------------------------------------------
# WebSocket router — interactive SSH
# ---------------------------------------------------------------------------

ssh_ws_router = APIRouter(tags=["ssh-ws"])


@ssh_ws_router.websocket("/api/ws/ssh/{name}")
async def ws_ssh(ws: WebSocket, name: str, token: str = Query(...)):
    """Interactive SSH session over WebSocket.

    Authentication is via ``token`` query parameter (JWT).
    Client sends JSON ``{"command": "..."}`` messages.
    Server streams output lines as JSON ``{"output": "..."}`` and
    sends ``{"done": true}`` when the command finishes.
    """
    # Authenticate
    settings = get_settings()
    try:
        decode_token(token, settings["jwt_secret"])
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        return

    # Validate site
    inv = get_inventory()
    site = inv.get_site(name)
    if site is None:
        await ws.close(code=1008, reason=f"Site '{name}' not found")
        return

    await ws.accept()

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                command = msg.get("command", "")
            except (json.JSONDecodeError, AttributeError):
                await ws.send_json({"error": "Invalid JSON"})
                continue

            if not command:
                await ws.send_json({"error": "Empty command"})
                continue

            # Stream SSH output back to the client
            async for line in stream_ssh_command(site, command, timeout=30):
                await ws.send_json({"output": line})

            await ws.send_json({"done": True})
    except WebSocketDisconnect:
        logger.debug("SSH WebSocket for %s disconnected", name)
