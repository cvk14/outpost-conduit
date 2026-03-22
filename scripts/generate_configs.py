#!/usr/bin/env python3
"""wg-mcast config generator.

Reads a sites.yaml inventory and generates WireGuard configs,
GRETAP/bridge setup scripts, and key material for all sites.
"""

import argparse
import os
import subprocess
import sys
import yaml

VALID_SITE_TYPES = {"glinet", "cradlepoint"}
HUB_REQUIRED_FIELDS = {"wan_ip", "tunnel_ip", "listen_port"}
SITE_REQUIRED_FIELDS = {"name", "type", "tunnel_ip", "wan_ip"}


def load_inventory(path: str) -> dict:
    """Load and return the YAML site inventory."""
    with open(path) as f:
        return yaml.safe_load(f)


def validate_inventory(inv: dict) -> None:
    """Validate inventory structure. Raises ValueError on problems."""
    if "hub" not in inv:
        raise ValueError("Missing required 'hub' section")

    for field in HUB_REQUIRED_FIELDS:
        if field not in inv["hub"]:
            raise ValueError(f"Hub missing required field: {field}")

    if "sites" not in inv or not inv["sites"]:
        raise ValueError("Must define at least one entry in 'sites'")

    seen_names = set()
    seen_ips = {inv["hub"]["tunnel_ip"]}

    for i, site in enumerate(inv["sites"]):
        for field in SITE_REQUIRED_FIELDS:
            if field not in site:
                raise ValueError(
                    f"Site at index {i} missing required field: {field}"
                )

        if site["type"] not in VALID_SITE_TYPES:
            raise ValueError(
                f"Site '{site['name']}' has invalid type '{site['type']}'. "
                f"Must be one of: {VALID_SITE_TYPES}"
            )

        if site["name"] in seen_names:
            raise ValueError(f"Duplicate site name: '{site['name']}'")
        seen_names.add(site["name"])

        if site["tunnel_ip"] in seen_ips:
            raise ValueError(
                f"Duplicate tunnel_ip: '{site['tunnel_ip']}' "
                f"in site '{site['name']}'"
            )
        seen_ips.add(site["tunnel_ip"])


def generate_keypair() -> tuple[str, str]:
    """Generate a WireGuard key pair. Returns (private_key, public_key)."""
    result = subprocess.run(
        ["wg", "genkey"], capture_output=True, text=True, check=True
    )
    private_key = result.stdout.strip()

    result = subprocess.run(
        ["wg", "pubkey"],
        input=private_key,
        capture_output=True,
        text=True,
        check=True,
    )
    public_key = result.stdout.strip()
    return private_key, public_key


def generate_psk() -> str:
    """Generate a WireGuard preshared key."""
    result = subprocess.run(
        ["wg", "genpsk"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
