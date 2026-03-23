"""Live multicast traffic capture via WebSocket."""

import asyncio
import re

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

    # -l = line buffered, -v = verbose (decodes mDNS/DNS payloads),
    # -e = show MACs, -n = no reverse DNS on IPs
    # -A = print packet payload in ASCII (shows mDNS service names)
    proc = await asyncio.create_subprocess_shell(
        "sudo tcpdump -i br-mcast -l -n -e -v 'multicast and not arp' 2>/dev/null",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    buffer = []
    try:
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "keepalive"})
                continue

            if not line:
                await ws.send_json({"type": "keepalive"})
                continue

            text = line.decode().strip()
            if not text:
                continue

            # tcpdump -v outputs multi-line: header line starts with timestamp,
            # continuation lines start with whitespace (contain DNS records, etc.)
            if text[0].isdigit():
                # New packet — flush previous buffer
                if buffer:
                    packet = _parse_packet(buffer)
                    await ws.send_json(packet)
                buffer = [text]
            else:
                # Continuation line (DNS records, payload data)
                buffer.append(text)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        # Flush last packet
        if buffer:
            try:
                packet = _parse_packet(buffer)
                await ws.send_json(packet)
            except Exception:
                pass
        proc.kill()
        await proc.wait()


def _parse_packet(lines: list) -> dict:
    """Parse a multi-line tcpdump -v -e packet into structured data."""
    header = lines[0]
    detail_lines = lines[1:] if len(lines) > 1 else []
    detail_text = " ".join(detail_lines)

    result = {"type": "packet", "raw": "\n".join(lines)}

    # Timestamp
    parts = header.split(" ", 1)
    if parts:
        result["timestamp"] = parts[0]

    # MAC addresses
    mac_match = re.search(r"([0-9a-f:]{17})\s+>\s+([0-9a-f:]{17})", header)
    if mac_match:
        result["src_mac"] = mac_match.group(1)
        result["dst_mac"] = mac_match.group(2)

    # IP + port
    ip_match = re.search(
        r"(\d+\.\d+\.\d+\.\d+)\.(\d+)\s+>\s+(\d+\.\d+\.\d+\.\d+)\.(\d+)",
        header,
    )
    if ip_match:
        result["src_ip"] = ip_match.group(1)
        result["src_port"] = ip_match.group(2)
        result["dst_ip"] = ip_match.group(3)
        result["dst_port"] = ip_match.group(4)

        port = int(ip_match.group(4))
        if port == 5353:
            result["protocol"] = "mDNS"
        elif port == 1900:
            result["protocol"] = "SSDP"
        elif port == 5350:
            result["protocol"] = "Relay"
        else:
            result["protocol"] = "UDP:" + str(port)

    # Length
    len_match = re.search(r"length (\d+)", header)
    if len_match:
        result["length"] = int(len_match.group(1))

    # --- Extract mDNS/DNS payload details ---
    full = header + " " + detail_text

    # Service names: _xyz._tcp.local, _xyz._udp.local
    services = list(set(re.findall(r"(_[\w-]+\._(tcp|udp)\.local\.?)", full)))
    if services:
        result["services"] = [s[0].rstrip(".") for s in services]

    # PTR records (service pointers) — e.g., "PTR My Device._hap._tcp.local."
    ptrs = re.findall(r"PTR\s+([^\s,()]+)", full)
    if ptrs:
        result["ptrs"] = list(set(ptrs))

    # SRV records — hostname:port
    srvs = re.findall(r"SRV\s+(\S+?)\.local\.:(\d+)", full)
    if srvs:
        result["srvs"] = [{"host": s[0], "port": int(s[1])} for s in srvs]

    # TXT records — key=value pairs (contains device info)
    txts = re.findall(r'"([^"]+)"', full)
    if txts:
        # Filter to key=value pairs
        kv = [t for t in txts if "=" in t]
        if kv:
            result["txt"] = kv

    # A/AAAA records — IP addresses
    a_records = re.findall(r"\bA\s+(\d+\.\d+\.\d+\.\d+)", full)
    if a_records:
        result["addresses"] = list(set(a_records))

    # Hostnames from PTR/SRV — extract readable names
    names = re.findall(r"(?:PTR|SRV)\s+(\S+?)\.(?:local|_)", full)
    hostnames = [n for n in set(names) if not n.startswith("_") and len(n) > 2]
    if hostnames:
        result["hostnames"] = hostnames

    # Device identification — look for manufacturer/model in TXT
    for t in txts:
        tl = t.lower()
        if tl.startswith("manufacturer=") or tl.startswith("md=") or tl.startswith("model="):
            result["device_info"] = t
            break

    # Query type (QM = multicast query, QU = unicast query)
    if "(QM)" in full:
        result["query_type"] = "query"
    elif "(QU)" in full:
        result["query_type"] = "query-unicast"
    elif "0*-" in full or "0*" in full:
        result["query_type"] = "response"
    elif "[0q]" in full:
        result["query_type"] = "response"

    return result
