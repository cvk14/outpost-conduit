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


def generate_hub_wg_config(hub: dict, sites: list[dict], hub_private_key: str) -> str:
    """Generate the hub's wg0.conf content."""
    lines = [
        "[Interface]",
        f"Address = {hub['tunnel_ip']}/16",
        f"ListenPort = {hub['listen_port']}",
        f"PrivateKey = {hub_private_key}",
        "MTU = 1420",
        "",
    ]
    for site in sites:
        lines.append(f"# {site['name']}")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {site['public_key']}")
        lines.append(f"PresharedKey = {site['psk']}")
        lines.append(f"AllowedIPs = {site['tunnel_ip']}/32")
        if site["wan_ip"] != "dynamic":
            lines.append(f"Endpoint = {site['wan_ip']}:{hub['listen_port']}")
        lines.append("PersistentKeepalive = 25")
        lines.append("")
    return "\n".join(lines)


def generate_site_wg_config(hub: dict, site: dict) -> str:
    """Generate a remote site's wg0.conf content."""
    lines = [
        "[Interface]",
        f"Address = {site['tunnel_ip']}/32",
        f"PrivateKey = {site['private_key']}",
        "MTU = 1420",
        "",
        "[Peer]",
        f"PublicKey = {hub['public_key']}",
        f"PresharedKey = {site['psk']}",
        f"Endpoint = {hub['wan_ip']}:{hub['listen_port']}",
        "AllowedIPs = 172.27.0.0/16",
        "PersistentKeepalive = 25",
        "",
    ]
    return "\n".join(lines)


def _sanitize_name(name: str) -> str:
    """Sanitize site name for use in interface names (max 15 chars for Linux)."""
    sanitized = name.replace(" ", "-").replace("_", "-")
    return sanitized[:8]


def generate_hub_bridge_script(hub_tunnel_ip: str, sites: list[dict], mcast_nic: str) -> str:
    """Generate the hub's bridge + GRETAP setup script."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# wg-mcast: Hub bridge + GRETAP setup",
        "# Auto-generated — do not edit manually",
        "",
        "# Create bridge",
        "ip link add br-mcast type bridge",
        "ip link set br-mcast type bridge stp_state 1",
        "ip link set br-mcast mtu 1380",
        "ip link set br-mcast up",
        "",
        f"# Add multicast NIC to bridge",
        f"ip link set {mcast_nic} master br-mcast",
        f"ip link set {mcast_nic} up",
        "",
        "# Create GRETAP tunnels",
    ]
    for site in sites:
        iface = f"gretap-{_sanitize_name(site['name'])}"
        lines.extend([
            f"# {site['name']}",
            f"ip link add {iface} type gretap local {hub_tunnel_ip} remote {site['tunnel_ip']}",
            f"ip link set {iface} mtu 1380",
            f"ip link set {iface} master br-mcast",
            f"ip link set {iface} up",
            "",
        ])
    lines.append('echo "Hub bridge setup complete."')
    return "\n".join(lines)


def generate_hub_teardown_script(sites: list[dict]) -> str:
    """Generate the hub's bridge teardown script."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# wg-mcast: Hub bridge teardown",
        "",
    ]
    for site in sites:
        iface = f"gretap-{_sanitize_name(site['name'])}"
        lines.append(f"ip link del {iface} 2>/dev/null || true")
    lines.extend([
        "",
        "ip link del br-mcast 2>/dev/null || true",
        "",
        'echo "Hub bridge teardown complete."',
    ])
    return "\n".join(lines)


def generate_glinet_gretap_script(site_tunnel_ip: str, hub_tunnel_ip: str) -> str:
    """Generate a GL.iNet (OpenWrt) GRETAP + bridge setup script."""
    # Generate a deterministic MAC from the tunnel IP octets
    # Format: 02:0c:XX:XX:XX:01 where XX comes from tunnel IP
    parts = site_tunnel_ip.split(".")
    mac = f"02:0c:{int(parts[0]):02x}:{int(parts[1]):02x}:{int(parts[2]):02x}:{int(parts[3]):02x}"
    return f"""#!/bin/sh
set -e

# wg-mcast: GL.iNet GRETAP + bridge setup
# Run after WireGuard is up and tunnel is established.

# Load GRE kernel module if needed
modprobe ip_gre 2>/dev/null || true

# Create GRETAP tunnel (ignore "exists" error on re-run)
ip link add gretap0 type gretap local {site_tunnel_ip} remote {hub_tunnel_ip} 2>/dev/null || true

# Assign a deterministic MAC (some OpenWrt devices have zeroed MACs on gretap)
ip link set dev gretap0 address {mac}
ip link set gretap0 mtu 1380
ip link set gretap0 up

# Add GRETAP to existing LAN bridge
ip link set gretap0 master br-lan 2>/dev/null || true

echo "GL.iNet GRETAP setup complete."
"""


def generate_pi_gretap_script(site_tunnel_ip: str, hub_tunnel_ip: str) -> str:
    """Generate a Raspberry Pi GRETAP + bridge setup script."""
    return f"""#!/bin/bash
set -e

# wg-mcast: Raspberry Pi GRETAP + bridge setup
# Run after WireGuard is up and tunnel is established.

# Create GRETAP tunnel
ip link add gretap0 type gretap local {site_tunnel_ip} remote {hub_tunnel_ip}
ip link set gretap0 mtu 1380
ip link set gretap0 up

# Create bridge and add GRETAP + eth0
ip link add br0 type bridge
ip link set br0 mtu 1380
ip link set br0 up

ip link set gretap0 master br0
ip link set eth0 master br0

echo "Pi GRETAP + bridge setup complete."
"""


def _write_file(path: str, content: str, mode: int = 0o644) -> None:
    """Write content to file with given permissions."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)


def generate_all(inventory_path: str, output_dir: str) -> None:
    """Main orchestration: load inventory, generate all configs and keys.

    Preserves existing keys if they already exist in the output directory.
    """
    inv = load_inventory(inventory_path)
    validate_inventory(inv)

    hub = inv["hub"]
    sites = inv["sites"]

    # Generate or load hub keys
    hub_pk_path = os.path.join(output_dir, "hub", "keys", "privatekey")
    hub_pub_path = os.path.join(output_dir, "hub", "keys", "publickey")

    if os.path.isfile(hub_pk_path) and os.path.isfile(hub_pub_path):
        with open(hub_pk_path) as f:
            hub_private = f.read().strip()
        with open(hub_pub_path) as f:
            hub_public = f.read().strip()
    else:
        hub_private, hub_public = generate_keypair()

    hub_keys_dir = os.path.join(output_dir, "hub", "keys")
    _write_file(os.path.join(hub_keys_dir, "privatekey"), hub_private + "\n", 0o600)
    _write_file(os.path.join(hub_keys_dir, "publickey"), hub_public + "\n")

    # Generate per-site keys and collect metadata
    site_configs = []
    for site in sites:
        site_keys_dir = os.path.join(output_dir, site["name"], "keys")
        site_pk_path = os.path.join(site_keys_dir, "privatekey")
        site_pub_path = os.path.join(site_keys_dir, "publickey")
        psk_path = os.path.join(site_keys_dir, "presharedkey")

        if os.path.isfile(site_pk_path) and os.path.isfile(site_pub_path):
            with open(site_pk_path) as f:
                site_private = f.read().strip()
            with open(site_pub_path) as f:
                site_public = f.read().strip()
        else:
            site_private, site_public = generate_keypair()

        if os.path.isfile(psk_path):
            with open(psk_path) as f:
                psk = f.read().strip()
        else:
            psk = generate_psk()

        _write_file(os.path.join(site_keys_dir, "privatekey"), site_private + "\n", 0o600)
        _write_file(os.path.join(site_keys_dir, "publickey"), site_public + "\n")
        _write_file(os.path.join(site_keys_dir, "presharedkey"), psk + "\n", 0o600)

        site_configs.append({
            **site,
            "private_key": site_private,
            "public_key": site_public,
            "psk": psk,
        })

    # Generate hub WireGuard config
    hub_wg = generate_hub_wg_config(hub, site_configs, hub_private)
    _write_file(os.path.join(output_dir, "hub", "wg0.conf"), hub_wg, 0o600)

    # Generate hub bridge scripts
    mcast_nic = hub.get("mcast_nic", "eth1")
    bridge_script = generate_hub_bridge_script(hub["tunnel_ip"], site_configs, mcast_nic)
    _write_file(os.path.join(output_dir, "hub", "setup-bridge.sh"), bridge_script, 0o755)

    teardown_script = generate_hub_teardown_script(site_configs)
    _write_file(os.path.join(output_dir, "hub", "teardown-bridge.sh"), teardown_script, 0o755)

    # Generate per-site configs
    hub_meta = {**hub, "public_key": hub_public}
    for sc in site_configs:
        site_name = sc["name"]
        site_wg = generate_site_wg_config(hub_meta, sc)
        _write_file(os.path.join(output_dir, site_name, "wg0.conf"), site_wg, 0o600)

        if sc["type"] == "glinet":
            gretap = generate_glinet_gretap_script(sc["tunnel_ip"], hub["tunnel_ip"])
        else:
            gretap = generate_pi_gretap_script(sc["tunnel_ip"], hub["tunnel_ip"])

        _write_file(os.path.join(output_dir, site_name, "setup-gretap.sh"), gretap, 0o755)

    print(f"Generated configs for {len(site_configs)} sites in {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="wg-mcast config generator")
    parser.add_argument("--inventory", "-i", required=True, help="Path to sites.yaml inventory file")
    parser.add_argument("--output", "-o", default="output", help="Output directory (default: output/)")
    args = parser.parse_args()

    try:
        generate_all(args.inventory, args.output)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
