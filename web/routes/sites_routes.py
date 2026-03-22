"""Sites CRUD and hub operations routes for Outpost Conduit Web UI."""

import asyncio
import io
import logging
import os
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.app import get_inventory, get_settings, require_auth
from scripts.generate_configs import generate_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sites", tags=["sites"], dependencies=[Depends(require_auth)])
hub_router = APIRouter(prefix="/api/hub", tags=["hub"], dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SiteCreate(BaseModel):
    name: str
    type: str
    tunnel_ip: str = ""
    wan_ip: str = "dynamic"
    description: str = ""
    ssh: Optional[dict] = None


class SiteUpdate(BaseModel):
    type: Optional[str] = None
    tunnel_ip: Optional[str] = None
    wan_ip: Optional[str] = None
    description: Optional[str] = None
    ssh: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _run_generate_all() -> None:
    """Run synchronous generate_all in a background thread."""
    settings = get_settings()
    inventory_path = settings["inventory_path"]
    output_dir = settings["output_dir"]
    await asyncio.to_thread(generate_all, inventory_path, output_dir)


# ---------------------------------------------------------------------------
# Sites routes — IMPORTANT: /next-ip MUST come before /{name} routes
# ---------------------------------------------------------------------------


@router.get("/next-ip")
async def next_ip():
    """Return the next available tunnel IP."""
    inv = get_inventory()
    try:
        tunnel_ip = inv.next_tunnel_ip()
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"tunnel_ip": tunnel_ip}


@router.get("")
async def list_sites():
    """List all sites from the inventory."""
    return get_inventory().get_sites()


@router.post("", status_code=201)
async def add_site(body: SiteCreate):
    """Add a new site to the inventory and regenerate configs."""
    inv = get_inventory()
    site_dict = body.model_dump(exclude_none=True)

    # Auto-assign tunnel_ip if not provided or empty
    if not site_dict.get("tunnel_ip"):
        site_dict["tunnel_ip"] = inv.next_tunnel_ip()

    try:
        inv.add_site(site_dict)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Generate configs in background
    try:
        await _run_generate_all()
    except Exception as e:
        logger.warning("Config generation failed after adding site: %s", e)

    return site_dict


@router.put("/{name}")
async def update_site(name: str, body: SiteUpdate):
    """Update an existing site and regenerate configs."""
    inv = get_inventory()
    updates = body.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        inv.update_site(name, updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Generate configs in background
    try:
        await _run_generate_all()
    except Exception as e:
        logger.warning("Config generation failed after updating site: %s", e)

    return inv.get_site(name)


@router.delete("/{name}", status_code=204)
async def delete_site(name: str):
    """Delete a site from the inventory and regenerate configs."""
    inv = get_inventory()

    try:
        inv.delete_site(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Generate configs in background
    try:
        await _run_generate_all()
    except Exception as e:
        logger.warning("Config generation failed after deleting site: %s", e)


@router.post("/{name}/generate")
async def generate_site(name: str):
    """Generate configs for a specific site (regenerates all)."""
    inv = get_inventory()
    if inv.get_site(name) is None:
        raise HTTPException(status_code=404, detail=f"Site '{name}' not found")

    try:
        await _run_generate_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config generation failed: {e}")

    return {"status": "ok", "message": f"Configs generated for {name}"}


@router.get("/{name}/download")
async def download_site(name: str):
    """Download a site's config bundle as a zip file."""
    inv = get_inventory()
    if inv.get_site(name) is None:
        raise HTTPException(status_code=404, detail=f"Site '{name}' not found")

    settings = get_settings()
    site_dir = os.path.join(settings["output_dir"], name)

    if not os.path.isdir(site_dir):
        raise HTTPException(status_code=404, detail=f"No generated configs found for '{name}'")

    # Build zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(site_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                arc_name = os.path.relpath(full_path, site_dir)
                zf.write(full_path, arc_name)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


# ---------------------------------------------------------------------------
# Hub routes
# ---------------------------------------------------------------------------


@hub_router.post("/regenerate")
async def hub_regenerate():
    """Regenerate all configs, copy to system dirs, and restart hub services."""
    try:
        await _run_generate_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config generation failed: {e}")

    # Copy generated configs to system locations
    settings = get_settings()
    hub_dir = os.path.join(settings["output_dir"], "hub")
    try:
        proc = await asyncio.create_subprocess_shell(
            f"sudo cp {hub_dir}/wg0.conf /etc/wireguard/wg0.conf && "
            f"sudo cp {hub_dir}/setup-bridge.sh /usr/local/bin/wg-mcast-bridge-up && "
            f"sudo cp {hub_dir}/teardown-bridge.sh /usr/local/bin/wg-mcast-bridge-down && "
            "sudo systemctl restart wg-quick@wg0 && "
            "sudo systemctl restart wg-mcast-bridge",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Hub apply returned code %d: %s", proc.returncode, stderr.decode())
            return {
                "status": "partial",
                "message": "Configs regenerated but apply/restart failed",
                "error": stderr.decode().strip(),
            }
    except Exception as e:
        logger.warning("Hub apply failed: %s", e)
        return {
            "status": "partial",
            "message": "Configs regenerated but apply/restart failed",
            "error": str(e),
        }

    return {"status": "ok", "message": "Configs regenerated, applied, and services restarted"}
