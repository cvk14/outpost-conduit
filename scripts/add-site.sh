#!/bin/bash
set -euo pipefail

# wg-mcast: Add a new site to the inventory and regenerate configs.
# Usage: ./add-site.sh <name> <type> [wan_ip]
#   <name>    = site name (e.g., "site-05-west")
#   <type>    = "glinet" or "cradlepoint"
#   [wan_ip]  = WAN IP or "dynamic" (default: dynamic)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INVENTORY="${WG_MCAST_INVENTORY:-sites.yaml}"
OUTPUT_DIR="${WG_MCAST_OUTPUT:-output}"

NAME="${1:?Usage: $0 <name> <type> [wan_ip]}"
TYPE="${2:?Usage: $0 <name> <type> [wan_ip]}"
WAN_IP="${3:-dynamic}"

if [ "$TYPE" != "glinet" ] && [ "$TYPE" != "cradlepoint" ]; then
    echo "Error: type must be 'glinet' or 'cradlepoint'" >&2
    exit 1
fi

if [ ! -f "$INVENTORY" ]; then
    echo "Error: inventory file '$INVENTORY' not found" >&2
    echo "Set WG_MCAST_INVENTORY to override" >&2
    exit 1
fi

# Find next available tunnel IP
LAST_OCTET=$(python3 -c "
import yaml
with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)
used = set()
for s in inv.get('sites', []):
    parts = s['tunnel_ip'].split('.')
    used.add(int(parts[2]))
# Find first available octet starting from 1
octet = 1
while octet in used:
    octet += 1
print(octet)
")

if [ "$LAST_OCTET" -gt 254 ]; then
    echo "Error: no available tunnel IPs (max 254 sites)" >&2
    exit 1
fi

TUNNEL_IP="172.27.${LAST_OCTET}.1"

echo "Adding site: $NAME"
echo "  Type:      $TYPE"
echo "  Tunnel IP: $TUNNEL_IP"
echo "  WAN IP:    $WAN_IP"

# Append to inventory
python3 -c "
import yaml

with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)

inv['sites'].append({
    'name': '$NAME',
    'type': '$TYPE',
    'tunnel_ip': '$TUNNEL_IP',
    'wan_ip': '$WAN_IP',
    'description': ''
})

with open('$INVENTORY', 'w') as f:
    yaml.dump(inv, f, default_flow_style=False, sort_keys=False)
"

echo "Inventory updated. Regenerating configs..."
python3 "$SCRIPT_DIR/generate_configs.py" -i "$INVENTORY" -o "$OUTPUT_DIR"

echo ""
echo "Site '$NAME' added. Config at: $OUTPUT_DIR/$NAME/"
echo "Next steps:"
echo "  1. Copy $OUTPUT_DIR/$NAME/ to the remote device"
if [ "$TYPE" = "glinet" ]; then
    echo "  2. Run: ./glinet-setup.sh <config-dir>"
else
    echo "  2. Run: sudo ./pi-setup.sh <config-dir>"
fi
echo "  3. Update hub: sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-bridge"
