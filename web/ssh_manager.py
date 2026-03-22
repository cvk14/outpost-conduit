"""Async SSH operations for Outpost Conduit remote management.

Provides helpers for running commands and copying files to remote sites
via asyncssh. Each site's SSH connection parameters (host, user, key)
are derived from the site dict's ``ssh`` section with sensible defaults.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

import asyncssh

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-device-type command map
# ---------------------------------------------------------------------------

COMMANDS: dict[str, dict[str, str]] = {
    "glinet": {
        "status": "wg show 2>/dev/null; ip link show gretap0 2>/dev/null; bridge link 2>/dev/null",
        "restart": "/etc/init.d/wg-mcast-gretap restart",
        "reboot": "reboot",
    },
    "cradlepoint": {
        "status": "wg show 2>/dev/null; ip link show gretap0 2>/dev/null; bridge link show br0 2>/dev/null",
        "restart": "sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-gretap",
        "reboot": "sudo reboot",
    },
}

# Default SSH users per site type.
_DEFAULT_USERS: dict[str, str] = {
    "glinet": "root",
    "cradlepoint": "pi",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_keys(explicit_key: str | None = None) -> list[str]:
    """Return a list of SSH private key paths to try.

    If an explicit key is given, use only that. Otherwise try common keys
    (RSA first for Dropbear/OpenWrt compatibility, then ed25519).
    """
    if explicit_key:
        return [str(Path(explicit_key).expanduser())]
    ssh_dir = Path.home() / ".ssh"
    candidates = ["id_rsa", "id_ed25519", "id_ecdsa"]
    keys = [str(ssh_dir / k) for k in candidates if (ssh_dir / k).is_file()]
    return keys if keys else [str(ssh_dir / "id_ed25519")]


def _ssh_config(site: dict) -> dict:
    """Extract SSH connection parameters from a site dict.

    Falls back to sensible defaults:
    - **host**: ``site["tunnel_ip"]``
    - **username**: ``root`` for glinet, ``pi`` for cradlepoint
    - **client_keys**: ``~/.ssh/id_ed25519``

    The site's optional ``ssh`` section can override ``host``, ``user``,
    and ``key``.
    """
    ssh_section = site.get("ssh") or {}
    site_type = site.get("type", "glinet")
    return {
        "host": ssh_section.get("host", site.get("tunnel_ip", "127.0.0.1")),
        "username": ssh_section.get("user", _DEFAULT_USERS.get(site_type, "root")),
        "client_keys": _resolve_keys(ssh_section.get("key")),
        "known_hosts": None,  # Accept any host key (VPN-internal hosts)
    }


def get_command(site_type: str, action: str) -> str:
    """Look up a predefined command for *site_type* and *action*.

    Raises:
        KeyError: If the site type or action is not found.
    """
    return COMMANDS[site_type][action]


# ---------------------------------------------------------------------------
# SSH execution
# ---------------------------------------------------------------------------

async def run_ssh_command(site: dict, command: str, timeout: int = 30) -> str:
    """Connect to *site* via SSH, execute *command*, and return combined output.

    Returns stdout + stderr as a single string.  Connection and command
    errors are caught and returned as error messages (not raised).
    """
    cfg = _ssh_config(site)
    try:
        async with asyncssh.connect(
            cfg["host"],
            username=cfg["username"],
            client_keys=cfg["client_keys"],
            known_hosts=cfg["known_hosts"],
        ) as conn:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output
    except asyncio.TimeoutError:
        return f"[ERROR] Command timed out after {timeout}s"
    except (asyncssh.Error, OSError) as exc:
        return f"[ERROR] SSH connection failed: {exc}"


async def stream_ssh_command(
    site: dict, command: str, timeout: int = 30
) -> AsyncIterator[str]:
    """Connect to *site* via SSH and yield output line by line.

    Yields each line of stdout/stderr as it becomes available.  On error
    yields a single ``[ERROR] ...`` line.
    """
    cfg = _ssh_config(site)
    try:
        async with asyncssh.connect(
            cfg["host"],
            username=cfg["username"],
            client_keys=cfg["client_keys"],
            known_hosts=cfg["known_hosts"],
        ) as conn:
            async with conn.create_process(command) as proc:
                try:
                    async with asyncio.timeout(timeout):
                        # Read from both stdout and stderr
                        assert proc.stdout is not None
                        async for line in proc.stdout:
                            yield line
                except TimeoutError:
                    yield f"[ERROR] Command timed out after {timeout}s\n"
                    proc.terminate()
    except (asyncssh.Error, OSError) as exc:
        yield f"[ERROR] SSH connection failed: {exc}\n"


async def scp_directory(site: dict, local_dir: str, remote_dir: str) -> str:
    """SCP a local directory tree to *remote_dir* on *site*.

    Uses asyncssh's ``scp`` helper in recursive mode.

    Returns:
        A success message or an error string prefixed with ``[ERROR]``.
    """
    cfg = _ssh_config(site)
    try:
        async with asyncssh.connect(
            cfg["host"],
            username=cfg["username"],
            client_keys=cfg["client_keys"],
            known_hosts=cfg["known_hosts"],
        ) as conn:
            # Ensure remote directory exists
            await conn.run(f"mkdir -p {remote_dir}", check=True)
            await asyncssh.scp(
                local_dir,
                (conn, remote_dir),
                recurse=True,
            )
        return f"Copied {local_dir} -> {remote_dir}"
    except (asyncssh.Error, OSError) as exc:
        return f"[ERROR] SCP failed: {exc}"
