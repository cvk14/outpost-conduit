"""Enrollment API — allows remote devices to self-enroll via CLI one-liner."""

import asyncio
import io
import os
import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from web.app import get_inventory, get_settings
from scripts.generate_configs import generate_all

router = APIRouter(prefix="/api/enroll", tags=["enroll"])


class EnrollRequest(BaseModel):
    name: str
    type: str = "glinet"
    wan_ip: str = "dynamic"
    description: str = ""


@router.post("")
async def enroll_site(body: EnrollRequest, token: str = Query(...)):
    """Enroll a new site. Requires the JWT token as a query param.
    Returns the site's config bundle as a zip."""
    # Verify token
    from web.auth import decode_token
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        raise HTTPException(401, "Invalid token")

    inv = get_inventory()
    settings = get_settings()

    # Build site data
    site_data = body.model_dump()
    if not site_data.get("tunnel_ip"):
        site_data["tunnel_ip"] = inv.next_tunnel_ip()

    # Add to inventory
    try:
        inv.add_site(site_data)
    except ValueError as e:
        raise HTTPException(409, str(e))

    # Generate configs
    await asyncio.to_thread(generate_all, settings["inventory_path"], settings["output_dir"])

    # Return config zip
    site_dir = os.path.join(settings["output_dir"], body.name)
    if not os.path.isdir(site_dir):
        raise HTTPException(500, "Config generation failed")

    # Also include the setup script in the zip
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    setup_script = os.path.join(project_root, "scripts", "glinet-setup.sh" if body.type == "glinet" else "pi-setup.sh")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(site_dir):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, site_dir)
                zf.write(full, arc)
        if os.path.isfile(setup_script):
            zf.write(setup_script, os.path.basename(setup_script))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={body.name}.zip"},
    )


@router.get("/script", response_class=PlainTextResponse)
async def enrollment_script(
    name: str = Query(...),
    token: str = Query(...),
    hub: str = Query(...),
    type: str = Query("glinet"),
):
    """Return a self-contained enrollment shell script for the remote device."""
    # Verify token
    from web.auth import decode_token
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        raise HTTPException(401, "Invalid token")

    setup_cmd = "./glinet-setup.sh /tmp/oc-enroll" if type == "glinet" else "sudo bash ./pi-setup.sh /tmp/oc-enroll"

    script = f"""#!/bin/sh
set -e
echo "=== Outpost Conduit Enrollment ==="
echo "Site: {name}"
echo "Hub: {hub}"
echo ""

# Check dependencies
command -v curl >/dev/null 2>&1 || {{ echo "Error: curl not found. Install with: opkg install curl"; exit 1; }}
command -v unzip >/dev/null 2>&1 || {{ echo "Error: unzip not found. Install with: opkg install unzip"; exit 1; }}

# Create temp dir
rm -rf /tmp/oc-enroll
mkdir -p /tmp/oc-enroll
cd /tmp/oc-enroll

# Enroll and download config bundle
echo "[1/3] Enrolling with hub..."
curl -sf -X POST \\
  "{hub}/api/enroll?token={token}" \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"{name}","type":"{type}","wan_ip":"dynamic"}}' \\
  -o config.zip

if [ ! -f config.zip ]; then
    echo "Error: enrollment failed"
    exit 1
fi

echo "[2/3] Extracting config..."
unzip -o config.zip

echo "[3/3] Running setup..."
chmod +x *.sh
{setup_cmd}

echo ""
echo "=== Enrollment complete ==="
echo "WireGuard: wg show"
"""
    return script
