"""Stats collector — WireGuard + bridge parsers and background poller.

Parses output from ``wg show wg0 dump`` and ``bridge -s link show br-mcast``,
merges with site inventory, and broadcasts live stats over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# A WireGuard peer is considered *online* if its last handshake was within
# this many seconds; *stale* if older but non-zero; *offline* if zero/never.
ONLINE_THRESHOLD_SECONDS = 300


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_wg_dump(output: str) -> list[dict]:
    """Parse tab-separated output of ``wg show <iface> dump``.

    Interface lines have 4 fields (private_key, fwmark, listen_port, …) and
    are skipped.  Peer lines have 8+ fields:
        [0] public_key, [1] preshared_key, [2] endpoint, [3] allowed_ips,
        [4] latest_handshake, [5] transfer_rx, [6] transfer_tx, [7] keepalive

    Note: despite the column *names* in ``wg show``, the **dump** format is:
        transfer-rx (bytes received) then transfer-tx (bytes sent).
    However, the task spec maps index [5] -> tx_bytes and [6] -> rx_bytes,
    matching the field order as given.  We follow the spec.

    Returns:
        List of peer dicts.
    """
    peers: list[dict] = []
    for line in output.strip().splitlines():
        fields = line.split("\t")
        if len(fields) < 8:
            # Interface line (4 fields) or malformed — skip.
            continue
        peers.append({
            "public_key": fields[0],
            "endpoint": fields[2],
            "allowed_ips": fields[3],
            "last_handshake": int(fields[4]),
            "tx_bytes": int(fields[5]),
            "rx_bytes": int(fields[6]),
        })
    return peers


def parse_bridge_stats(output: str) -> list[dict]:
    """Parse output of ``bridge link show <bridge>`` (port names + state).

    Each port line matches::

        N: name(@suffix)?: <FLAGS> ... state STATE ...

    Traffic stats are NOT reliably available from ``bridge -s`` across kernel
    versions.  Use ``parse_ip_link_stats()`` separately for traffic data.

    Returns:
        List of port dicts with keys: name, state, and zeroed traffic fields.
    """
    ports: list[dict] = []
    header_re = re.compile(
        r"^\d+:\s+(\S+?)(?:@\S+)?:\s+<[^>]*>.*\bstate\s+(\S+)"
    )

    for line in output.strip().splitlines():
        m = header_re.match(line)
        if m:
            ports.append({
                "name": m.group(1),
                "state": m.group(2),
                "rx_bytes": 0, "rx_packets": 0, "rx_errors": 0,
                "tx_bytes": 0, "tx_packets": 0, "tx_errors": 0,
            })
    return ports


def parse_ip_link_stats(output: str) -> dict:
    """Parse output of ``ip -s link show <iface>``.

    Extracts RX/TX bytes, packets, errors from the stats lines.

    Returns:
        Dict with rx_bytes, rx_packets, rx_errors, tx_bytes, tx_packets, tx_errors.
    """
    result = {
        "rx_bytes": 0, "rx_packets": 0, "rx_errors": 0,
        "tx_bytes": 0, "tx_packets": 0, "tx_errors": 0,
    }
    lines = output.strip().splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("RX:") and i + 1 < len(lines):
            vals = lines[i + 1].split()
            if vals:
                result["rx_bytes"] = int(vals[0])
            if len(vals) >= 2:
                result["rx_packets"] = int(vals[1])
            if len(vals) >= 3:
                result["rx_errors"] = int(vals[2])
        elif stripped.startswith("TX:") and i + 1 < len(lines):
            vals = lines[i + 1].split()
            if vals:
                result["tx_bytes"] = int(vals[0])
            if len(vals) >= 2:
                result["tx_packets"] = int(vals[1])
            if len(vals) >= 3:
                result["tx_errors"] = int(vals[2])
    return result


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_stats(
    sites: list[dict],
    peers: list[dict],
    bridge_ports: list[dict],
) -> dict:
    """Merge site inventory with live WireGuard peer and bridge data.

    Matches each site to a peer by ``public_key``.  Determines status:
    - **online**: last handshake within ``ONLINE_THRESHOLD_SECONDS``
    - **stale**: last handshake older than threshold but non-zero
    - **offline**: no matching peer or handshake == 0

    Returns:
        Dict with keys ``summary``, ``sites``, ``bridge_ports``, ``timestamp``.
    """
    now = int(time.time())
    peer_map: dict[str, dict] = {p["public_key"]: p for p in peers}

    merged_sites: list[dict] = []
    counts = {"online": 0, "stale": 0, "offline": 0}

    for site in sites:
        pub_key = site.get("public_key", "")
        peer = peer_map.get(pub_key)
        status = _compute_status(peer, now)
        counts[status] += 1

        entry: dict[str, Any] = {**site, "status": status}
        if peer:
            entry.update({
                "endpoint": peer["endpoint"],
                "tx_bytes": peer["tx_bytes"],
                "rx_bytes": peer["rx_bytes"],
                "last_handshake": peer["last_handshake"],
            })
        merged_sites.append(entry)

    return {
        "summary": {
            "total": len(sites),
            "online": counts["online"],
            "stale": counts["stale"],
            "offline": counts["offline"],
        },
        "sites": merged_sites,
        "bridge_ports": bridge_ports,
        "timestamp": now,
    }


def _compute_status(peer: dict | None, now: int) -> str:
    """Return 'online', 'stale', or 'offline' for a peer."""
    if peer is None:
        return "offline"
    hs = peer.get("last_handshake", 0)
    if hs == 0:
        return "offline"
    age = now - hs
    if age <= ONLINE_THRESHOLD_SECONDS:
        return "online"
    return "stale"


# ---------------------------------------------------------------------------
# StatsCollector (background async task)
# ---------------------------------------------------------------------------

class StatsCollector:
    """Background poller that collects WireGuard + bridge stats.

    Usage::

        collector = StatsCollector(
            wg_interface="wg0",
            bridge_name="br-mcast",
            output_dir="/path/to/output",
            get_sites=lambda: [...],   # callback returning site list
            interval=10,
        )
        collector.start()
        # Later, to stop:
        collector.stop()

    WebSocket handlers should add their connection to ``collector.clients``
    and remove it on disconnect.
    """

    def __init__(
        self,
        wg_interface: str = "wg0",
        bridge_name: str = "br-mcast",
        output_dir: str = "output",
        get_sites: Callable[[], list[dict]] | None = None,
        interval: int = 10,
    ) -> None:
        self.wg_interface = wg_interface
        self.bridge_name = bridge_name
        self.output_dir = Path(output_dir)
        self.get_sites = get_sites or (lambda: [])
        self.interval = interval

        self.clients: set = set()
        self.latest: dict = {}
        self._task: asyncio.Task | None = None

    # -- Public API ---------------------------------------------------------

    def start(self) -> None:
        """Create the background polling task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("StatsCollector started (interval=%ds)", self.interval)

    def stop(self) -> None:
        """Cancel the background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("StatsCollector stopped")

    # -- Internals ----------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Continuously poll WireGuard and bridge stats."""
        while True:
            try:
                wg_output = await self._run_cmd(
                    f"sudo wg show {self.wg_interface} dump"
                )
                bridge_output = await self._run_cmd(
                    f"bridge link show {self.bridge_name}"
                )

                peers = parse_wg_dump(wg_output)
                bridge_ports = parse_bridge_stats(bridge_output)

                # Fetch per-port traffic stats via ip -s link
                for port in bridge_ports:
                    try:
                        port_stats_output = await self._run_cmd(
                            f"ip -s link show {port['name']}"
                        )
                        stats = parse_ip_link_stats(port_stats_output)
                        port.update(stats)
                    except Exception:
                        pass

                sites = self.get_sites()
                self._attach_keys(sites)

                self.latest = merge_stats(sites, peers, bridge_ports)
                await self._broadcast(self.latest)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stats poll error")

            await asyncio.sleep(self.interval)

    def _attach_keys(self, sites: list[dict]) -> None:
        """Read public keys from output/<site-name>/keys/publickey files.

        Mutates each site dict in place, adding a ``public_key`` field if the
        key file exists and the site doesn't already have one.
        """
        for site in sites:
            if site.get("public_key"):
                continue
            name = site.get("name", "")
            key_path = self.output_dir / name / "keys" / "publickey"
            if key_path.is_file():
                site["public_key"] = key_path.read_text().strip()

    async def _broadcast(self, data: dict) -> None:
        """Send JSON payload to all connected WebSocket clients."""
        if not self.clients:
            return
        payload = json.dumps(data)
        dead: list = []
        for ws in self.clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    @staticmethod
    async def _run_cmd(cmd: str) -> str:
        """Run a shell command and return its stdout."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Command %r failed (rc=%d): %s", cmd, proc.returncode, stderr.decode().strip())
        return stdout.decode()
