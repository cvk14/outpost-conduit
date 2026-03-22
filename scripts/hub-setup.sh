#!/bin/bash
set -euo pipefail

# wg-mcast: Hub VM setup script
# Run on the Linux VM (Ubuntu Server 24.04 recommended).
# Usage: sudo ./hub-setup.sh <config-dir>
#   <config-dir> = path to generated hub config (output/hub/)

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

if [ ! -f "$CONFIG_DIR/wg0.conf" ]; then
    echo "Error: $CONFIG_DIR/wg0.conf not found" >&2
    exit 1
fi

echo "=== wg-mcast Hub Setup ==="

# --- Install dependencies ---
echo "[1/5] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools iproute2 bridge-utils

# --- Install WireGuard config ---
echo "[2/5] Configuring WireGuard..."
cp "$CONFIG_DIR/wg0.conf" /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Enable and start WireGuard
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# --- Install bridge setup scripts ---
echo "[3/5] Installing bridge scripts..."
cp "$CONFIG_DIR/setup-bridge.sh" /usr/local/bin/wg-mcast-bridge-up
cp "$CONFIG_DIR/teardown-bridge.sh" /usr/local/bin/wg-mcast-bridge-down
chmod 755 /usr/local/bin/wg-mcast-bridge-up /usr/local/bin/wg-mcast-bridge-down

# --- Create systemd service for bridge ---
echo "[4/5] Creating bridge systemd service..."
cat > /etc/systemd/system/wg-mcast-bridge.service << 'UNIT'
[Unit]
Description=wg-mcast GRETAP Bridge
After=wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/wg-mcast-bridge-up
ExecStop=/usr/local/bin/wg-mcast-bridge-down

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable wg-mcast-bridge
systemctl start wg-mcast-bridge

# --- Verify ---
echo "[5/5] Verifying..."
wg show wg0
bridge link show br-mcast 2>/dev/null || echo "Warning: bridge not yet active (peers may not be connected)"

echo ""
echo "=== Hub setup complete ==="
echo "WireGuard: systemctl status wg-quick@wg0"
echo "Bridge:    systemctl status wg-mcast-bridge"
