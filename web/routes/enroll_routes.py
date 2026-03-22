"""Enrollment API — allows remote devices to self-enroll via CLI one-liner."""

import asyncio
import io
import os
import shutil
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


async def _apply_hub_config(settings: dict) -> None:
    """Copy generated hub config to system dirs and restart WireGuard + bridge."""
    output_dir = settings["output_dir"]
    hub_dir = os.path.join(output_dir, "hub")

    # Copy WireGuard config
    wg_conf = os.path.join(hub_dir, "wg0.conf")
    if os.path.isfile(wg_conf):
        shutil.copy2(wg_conf, "/etc/wireguard/wg0.conf")

    # Copy bridge scripts
    bridge_up = os.path.join(hub_dir, "setup-bridge.sh")
    bridge_down = os.path.join(hub_dir, "teardown-bridge.sh")
    if os.path.isfile(bridge_up):
        shutil.copy2(bridge_up, "/usr/local/bin/wg-mcast-bridge-up")
    if os.path.isfile(bridge_down):
        shutil.copy2(bridge_down, "/usr/local/bin/wg-mcast-bridge-down")

    # Restart services
    proc = await asyncio.create_subprocess_shell(
        "sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-bridge && "
        "sudo bash /home/chris/outpost-conduit/scripts/relay-setup.sh 2>/dev/null || true",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


@router.post("")
async def enroll_site(body: EnrollRequest, token: str = Query(...)):
    """Enroll a new site. Requires the JWT token as a query param.
    Returns the site's config bundle as a zip."""
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

    # Generate configs for all sites (preserves existing keys)
    await asyncio.to_thread(generate_all, settings["inventory_path"], settings["output_dir"])

    # Apply hub config and restart services so the new peer is immediately accepted
    try:
        await _apply_hub_config(settings)
    except Exception:
        pass  # Non-fatal — hub can be restarted manually

    # Build zip with site config + setup script
    site_dir = os.path.join(settings["output_dir"], body.name)
    if not os.path.isdir(site_dir):
        raise HTTPException(500, "Config generation failed")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    setup_script = os.path.join(
        project_root, "scripts",
        "glinet-setup.sh" if body.type == "glinet" else "pi-setup.sh"
    )

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
    from web.auth import decode_token
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        raise HTTPException(401, "Invalid token")

    setup_cmd = "sh ./glinet-setup.sh /tmp/oc-enroll" if type == "glinet" else "sudo bash ./pi-setup.sh /tmp/oc-enroll"

    script = f"""#!/bin/sh
set -e
echo "=== Outpost Conduit Enrollment ==="
echo "Site: {name}"
echo "Hub: {hub}"
echo ""

# Install prerequisites
echo "[0/4] Installing prerequisites..."
opkg update 2>/dev/null || echo "Warning: some repos unavailable"
opkg install kmod-gre 2>/dev/null || echo "Warning: kmod-gre install failed — install via LuCI if needed"
command -v curl >/dev/null 2>&1 || opkg install curl 2>/dev/null
command -v unzip >/dev/null 2>&1 || opkg install unzip 2>/dev/null

# Create temp dir
rm -rf /tmp/oc-enroll
mkdir -p /tmp/oc-enroll
cd /tmp/oc-enroll

# Enroll and download config bundle
echo "[1/4] Enrolling with hub..."
curl -sf -X POST \\
  "{hub}/api/enroll?token={token}" \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"{name}","type":"{type}","wan_ip":"dynamic"}}' \\
  -o config.zip

if [ ! -f config.zip ]; then
    echo "Error: enrollment failed — check hub connectivity"
    exit 1
fi

echo "[2/4] Extracting config..."
unzip -o config.zip

echo "[3/4] Running setup (network will restart — connection may drop)..."
chmod +x *.sh 2>/dev/null || true
{setup_cmd}

echo ""
echo "[4/4] Verifying..."
sleep 5
wg show 2>/dev/null || echo "WireGuard not yet active"
ip link show gretap0 2>/dev/null || echo "GRETAP not yet active"

echo ""
echo "=== Enrollment complete ==="
"""
    return script
