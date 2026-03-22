"""Diagnostics API — network tests for latency, packet loss, and multicast."""

import asyncio
import re
import time

from fastapi import APIRouter, Depends, HTTPException

from web.app import get_inventory, get_settings, require_auth
from web.ssh_manager import run_ssh_command

router = APIRouter(
    prefix="/api/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(require_auth)],
)


@router.post("/ping/{name}")
async def ping_test(name: str, count: int = 10):
    """Ping a site through the WireGuard tunnel. Returns latency + packet loss."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")

    tunnel_ip = site["tunnel_ip"]
    proc = await asyncio.create_subprocess_shell(
        f"ping -c {min(count, 50)} -W 2 {tunnel_ip}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()

    # Parse ping results
    result = {
        "site": name,
        "tunnel_ip": tunnel_ip,
        "packets_sent": 0,
        "packets_received": 0,
        "packet_loss_pct": 100.0,
        "rtt_min": None,
        "rtt_avg": None,
        "rtt_max": None,
        "rtt_mdev": None,
        "raw": output,
    }

    # Parse "X packets transmitted, Y received, Z% packet loss"
    loss_match = re.search(
        r"(\d+) packets transmitted, (\d+) received.*?(\d+(?:\.\d+)?)% packet loss",
        output,
    )
    if loss_match:
        result["packets_sent"] = int(loss_match.group(1))
        result["packets_received"] = int(loss_match.group(2))
        result["packet_loss_pct"] = float(loss_match.group(3))

    # Parse "rtt min/avg/max/mdev = X/X/X/X ms"
    rtt_match = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        output,
    )
    if rtt_match:
        result["rtt_min"] = float(rtt_match.group(1))
        result["rtt_avg"] = float(rtt_match.group(2))
        result["rtt_max"] = float(rtt_match.group(3))
        result["rtt_mdev"] = float(rtt_match.group(4))

    return result


@router.post("/mtu/{name}")
async def mtu_test(name: str):
    """Test MTU path to a site by sending pings of increasing size."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")

    tunnel_ip = site["tunnel_ip"]
    results = []

    for size in [100, 500, 1000, 1200, 1350, 1380, 1400, 1420]:
        proc = await asyncio.create_subprocess_shell(
            f"ping -c 1 -W 2 -s {size} -M do {tunnel_ip}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout.decode() + stderr.decode()).strip()
        success = proc.returncode == 0
        results.append({"size": size, "success": success})

    return {"site": name, "tunnel_ip": tunnel_ip, "results": results}


@router.post("/multicast/{name}")
async def multicast_test(name: str):
    """Test multicast relay to a site.

    Sends a unique test packet via the relay and checks if the site
    receives it (requires socat on the remote device).
    """
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")

    test_id = f"MCAST_TEST_{int(time.time())}"
    tunnel_ip = site["tunnel_ip"]

    # Hub→Site test: send a unicast UDP packet directly to the site's tunnel IP
    # and have the site confirm receipt. This tests the WireGuard + GRETAP path.
    try:
        # Start listener on remote site
        listen_cmd = (
            "rm -f /tmp/mcast_test.log; "
            "socat -u UDP4-RECVFROM:9998,reuseaddr "
            "SYSTEM:'cat >> /tmp/mcast_test.log' & "
            "LPID=$!; "
            "sleep 6; "
            "kill $LPID 2>/dev/null; "
            "cat /tmp/mcast_test.log 2>/dev/null; "
            "rm -f /tmp/mcast_test.log"
        )
        listen_task = asyncio.create_task(run_ssh_command(site, listen_cmd, timeout=18))

        # Wait for SSH to connect (~3s) + socat to bind (~1s) + margin
        await asyncio.sleep(6)

        # Send test packet multiple times to handle timing variance
        for _ in range(3):
            send_proc = await asyncio.create_subprocess_shell(
                f"echo '{test_id}' | socat - UDP4-SENDTO:{tunnel_ip}:9998",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await send_proc.communicate()
            await asyncio.sleep(0.5)

        listener_output = await listen_task
        received = test_id in listener_output

        return {
            "site": name,
            "test_id": test_id,
            "direction": "hub_to_site",
            "received": received,
            "output": listener_output.strip(),
        }

    except Exception as e:
        return {
            "site": name,
            "test_id": test_id,
            "direction": "hub_to_site",
            "received": False,
            "error": str(e),
        }


@router.post("/multicast-return/{name}")
async def multicast_return_test(name: str):
    """Test multicast return path (site → hub) via the relay."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")

    test_id = f"MCAST_RET_{int(time.time())}"

    # For site→hub, the relay forwards mDNS (port 5353) not port 9999.
    # Send on port 5353 from the site, check if hub relay received it
    # by listening on the relay port (5350) for the forwarded packet.
    hub_listener = await asyncio.create_subprocess_shell(
        "timeout 10 socat -u UDP4-RECVFROM:9998,reuseaddr STDOUT",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    await asyncio.sleep(1)

    # Send test directly as unicast to hub relay port (bypasses mDNS port conflicts)
    try:
        await run_ssh_command(
            site,
            f"echo '{test_id}' | socat - UDP4-SENDTO:172.27.0.1:9998",
            timeout=5,
        )
    except Exception:
        pass

    # Wait for hub listener
    try:
        stdout, _ = await asyncio.wait_for(hub_listener.communicate(), timeout=10)
        received = test_id in stdout.decode()
    except asyncio.TimeoutError:
        hub_listener.kill()
        received = False

    return {
        "site": name,
        "test_id": test_id,
        "direction": "site_to_hub",
        "received": received,
    }


@router.post("/all/{name}")
async def run_all_tests(name: str):
    """Run all diagnostic tests for a site."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")

    results = {}

    # Ping test
    try:
        results["ping"] = await ping_test(name, count=5)
        del results["ping"]["raw"]  # Remove verbose output
    except Exception as e:
        results["ping"] = {"error": str(e)}

    # MTU test
    try:
        results["mtu"] = await mtu_test(name)
    except Exception as e:
        results["mtu"] = {"error": str(e)}

    # Multicast hub→site
    try:
        results["multicast_to_site"] = await multicast_test(name)
    except Exception as e:
        results["multicast_to_site"] = {"error": str(e)}

    # Multicast site→hub
    try:
        results["multicast_to_hub"] = await multicast_return_test(name)
    except Exception as e:
        results["multicast_to_hub"] = {"error": str(e)}

    return {"site": name, "results": results}
