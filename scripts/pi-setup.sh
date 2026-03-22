#!/bin/bash
set -euo pipefail

# wg-mcast: Raspberry Pi sidecar setup script
# Run on the Pi at Cradlepoint sites.
# Usage: sudo ./pi-setup.sh <config-dir>
#   <config-dir> = path to generated site config (output/site-XX/)

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

if [ ! -f "$CONFIG_DIR/wg0.conf" ]; then
    echo "Error: $CONFIG_DIR/wg0.conf not found" >&2
    exit 1
fi

echo "=== wg-mcast Pi Sidecar Setup ==="

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

# --- Install GRETAP setup script ---
echo "[3/5] Installing GRETAP script..."
cp "$CONFIG_DIR/setup-gretap.sh" /usr/local/bin/wg-mcast-gretap-up
chmod 755 /usr/local/bin/wg-mcast-gretap-up

# --- Create systemd service for GRETAP + bridge ---
echo "[4/5] Creating GRETAP systemd service..."
cat > /etc/systemd/system/wg-mcast-gretap.service << 'UNIT'
[Unit]
Description=wg-mcast GRETAP Bridge
After=wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/wg-mcast-gretap-up
ExecStop=/bin/sh -c "ip link del br0 2>/dev/null; ip link del gretap0 2>/dev/null"

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable wg-mcast-gretap
systemctl start wg-mcast-gretap

# --- Verify ---
echo "[5/5] Verifying..."
wg show wg0
ip link show gretap0 2>/dev/null || echo "Warning: GRETAP not yet active"
bridge link show br0 2>/dev/null || echo "Warning: bridge not yet active"

echo ""
echo "=== Pi sidecar setup complete ==="
echo "WireGuard: systemctl status wg-quick@wg0"
echo "GRETAP:    systemctl status wg-mcast-gretap"
