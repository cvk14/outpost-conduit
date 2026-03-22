"""Inventory manager for Outpost Conduit Web UI.

Provides CRUD operations on the sites.yaml inventory file with
atomic writes and file locking.
"""

import fcntl
import os
import tempfile

import yaml

from scripts.generate_configs import validate_inventory


class InventoryManager:
    """Manage the sites.yaml inventory file."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> dict:
        """Read and return the YAML inventory."""
        with open(self.path) as f:
            return yaml.safe_load(f)

    def _save(self, inv: dict) -> None:
        """Validate and atomically write the inventory to disk.

        Uses validate_inventory() for structural checks (skipped when
        the sites list is empty, since the web UI allows removing all
        sites). Writes to a temp file with fcntl.flock(), then uses
        os.replace() for an atomic swap.
        """
        # Only validate when there are sites; validate_inventory requires >= 1
        if inv.get("sites"):
            validate_inventory(inv)

        dir_name = os.path.dirname(os.path.abspath(self.path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as tmp_f:
                fcntl.flock(tmp_f, fcntl.LOCK_EX)
                yaml.dump(inv, tmp_f, default_flow_style=False)
                fcntl.flock(tmp_f, fcntl.LOCK_UN)
            os.replace(tmp_path, self.path)
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def get_sites(self) -> list[dict]:
        """Return the list of sites from the inventory."""
        inv = self.load()
        return inv.get("sites", [])

    def get_site(self, name: str) -> dict | None:
        """Return a single site by name, or None if not found."""
        for site in self.get_sites():
            if site["name"] == name:
                return site
        return None

    def add_site(self, site: dict) -> None:
        """Add a new site to the inventory.

        Raises ValueError if a site with the same name already exists.
        """
        inv = self.load()
        for existing in inv.get("sites", []):
            if existing["name"] == site["name"]:
                raise ValueError(f"Site '{site['name']}' already exists")
        inv.setdefault("sites", []).append(site)
        self._save(inv)

    def update_site(self, name: str, updates: dict) -> None:
        """Update fields of an existing site.

        Raises ValueError if the site is not found.
        """
        inv = self.load()
        for site in inv.get("sites", []):
            if site["name"] == name:
                site.update(updates)
                self._save(inv)
                return
        raise ValueError(f"Site '{name}' not found")

    def delete_site(self, name: str) -> None:
        """Remove a site from the inventory.

        Raises ValueError if the site is not found.
        """
        inv = self.load()
        original_len = len(inv.get("sites", []))
        inv["sites"] = [s for s in inv.get("sites", []) if s["name"] != name]
        if len(inv["sites"]) == original_len:
            raise ValueError(f"Site '{name}' not found")
        self._save(inv)

    def next_tunnel_ip(self) -> str:
        """Find the first available tunnel IP in the 172.27.N.1 range.

        Scans octets 1-254 and returns the first one not already in use
        by the hub or any site.
        """
        inv = self.load()
        used_octets: set[int] = set()

        # Hub tunnel IP
        hub_ip = inv.get("hub", {}).get("tunnel_ip", "")
        if hub_ip:
            parts = hub_ip.split(".")
            if len(parts) == 4:
                used_octets.add(int(parts[2]))

        # Site tunnel IPs
        for site in inv.get("sites", []):
            tip = site.get("tunnel_ip", "")
            parts = tip.split(".")
            if len(parts) == 4:
                used_octets.add(int(parts[2]))

        for octet in range(1, 255):
            if octet not in used_octets:
                return f"172.27.{octet}.1"

        raise ValueError("No available tunnel IP octets (1-254 all in use)")
