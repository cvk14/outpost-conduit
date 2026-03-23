"""Live multicast traffic capture via WebSocket."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from web.auth import decode_token
from web.app import get_settings

router = APIRouter(tags=["capture"])


@router.websocket("/api/ws/multicast")
async def ws_multicast_capture(ws: WebSocket, token: str = Query(...)):
    """Stream live multicast traffic from br-mcast via tcpdump."""
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        return

    await ws.accept()

    # Start tcpdump capturing multicast on br-mcast
    # -l = line buffered, -n = no DNS, -e = show MAC addresses
    # Filter: only multicast destination (224.0.0.0/4)
    proc = await asyncio.create_subprocess_shell(
        "sudo tcpdump -i br-mcast -l -n -e 'multicast and not arp' 2>/dev/null",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                # Send keepalive if tcpdump has no output
                await ws.send_json({"type": "keepalive"})
                continue

            text = line.decode().strip()
            if not text:
                continue

            # Parse tcpdump output into structured data
            packet = _parse_tcpdump_line(text)
            await ws.send_json(packet)

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        proc.kill()
        await proc.wait()


def _parse_tcpdump_line(line: str) -> dict:
    """Parse a tcpdump -n -e line into structured fields.

    Example input:
    23:14:50.680789 5e:ec:26:44:ce:f4 > 01:00:5e:00:00:fb, ethertype IPv4 (0x0800), length 142: 10.0.0.114.5353 > 224.0.0.251.5353: 0 [5q] PTR...

    Returns dict with: timestamp, src_mac, dst_mac, src_ip, dst_ip, protocol, length, info
    """
    result = {"type": "packet", "raw": line}

    parts = line.split(" ", 1)
    if len(parts) >= 1:
        result["timestamp"] = parts[0]

    # Extract IPs — look for "A.B.C.D.port > A.B.C.D.port:" pattern
    import re

    ip_match = re.search(
        r"(\d+\.\d+\.\d+\.\d+)\.(\d+)\s+>\s+(\d+\.\d+\.\d+\.\d+)\.(\d+)",
        line,
    )
    if ip_match:
        result["src_ip"] = ip_match.group(1)
        result["src_port"] = ip_match.group(2)
        result["dst_ip"] = ip_match.group(3)
        result["dst_port"] = ip_match.group(4)

        # Determine protocol from port
        port = int(ip_match.group(4))
        if port == 5353:
            result["protocol"] = "mDNS"
        elif port == 1900:
            result["protocol"] = "SSDP"
        elif port == 5350:
            result["protocol"] = "Relay"
        else:
            result["protocol"] = "UDP:" + str(port)

    # Extract MAC addresses
    mac_match = re.search(
        r"([0-9a-f:]{17})\s+>\s+([0-9a-f:]{17})",
        line,
    )
    if mac_match:
        result["src_mac"] = mac_match.group(1)
        result["dst_mac"] = mac_match.group(2)

    # Extract length
    len_match = re.search(r"length (\d+)", line)
    if len_match:
        result["length"] = int(len_match.group(1))

    return result
