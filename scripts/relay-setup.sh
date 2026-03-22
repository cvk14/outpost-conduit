#!/bin/bash
set -euo pipefail

# Outpost Conduit: Install multicast relay as systemd service on the hub.
# Reads site tunnel IPs from sites.yaml and configures the relay.
# Usage: sudo ./scripts/relay-setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INVENTORY="${PROJECT_DIR}/sites.yaml"
RELAY_SCRIPT="${PROJECT_DIR}/scripts/mcast-relay.py"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

if [ ! -f "$INVENTORY" ]; then
    echo "Error: $INVENTORY not found" >&2
    exit 1
fi

# Extract site tunnel IPs from inventory
SITE_IPS=$(python3 -c "
import yaml
with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)
ips = [s['tunnel_ip'] for s in inv.get('sites', [])]
print(','.join(ips))
")

if [ -z "$SITE_IPS" ]; then
    echo "Error: no sites found in inventory" >&2
    exit 1
fi

echo "=== Multicast Relay Setup ==="
echo "Sites: $SITE_IPS"

# Install systemd service
cat > /etc/systemd/system/outpost-conduit-relay.service << UNIT
[Unit]
Description=Outpost Conduit Multicast Relay
After=wg-quick@wg0.service wg-mcast-bridge.service
Requires=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -u ${RELAY_SCRIPT} --mode hub --iface br-mcast --sites ${SITE_IPS}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# Kill any existing relay processes
killall -f mcast-relay.py 2>/dev/null || true

systemctl daemon-reload
systemctl enable outpost-conduit-relay
systemctl restart outpost-conduit-relay

sleep 2
if systemctl is-active outpost-conduit-relay >/dev/null; then
    echo "Relay service running"
    echo "Service: systemctl status outpost-conduit-relay"
else
    echo "ERROR: Relay service failed to start"
    systemctl status outpost-conduit-relay
    exit 1
fi
