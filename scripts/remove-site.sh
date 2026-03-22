#!/bin/bash
set -euo pipefail

# wg-mcast: Remove a site from the inventory and regenerate configs.
# Usage: ./remove-site.sh <name>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INVENTORY="${WG_MCAST_INVENTORY:-sites.yaml}"
OUTPUT_DIR="${WG_MCAST_OUTPUT:-output}"

NAME="${1:?Usage: $0 <name>}"

if [ ! -f "$INVENTORY" ]; then
    echo "Error: inventory file '$INVENTORY' not found" >&2
    exit 1
fi

# Verify site exists
python3 -c "
import yaml, sys
with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)
names = [s['name'] for s in inv.get('sites', [])]
if '$NAME' not in names:
    print(f\"Error: site '$NAME' not found in inventory\", file=sys.stderr)
    print(f'Available sites: {names}', file=sys.stderr)
    sys.exit(1)
"

echo "Removing site: $NAME"

# Remove from inventory
python3 -c "
import yaml

with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)

inv['sites'] = [s for s in inv['sites'] if s['name'] != '$NAME']

with open('$INVENTORY', 'w') as f:
    yaml.dump(inv, f, default_flow_style=False, sort_keys=False)
"

# Remove generated config directory
if [ -d "$OUTPUT_DIR/$NAME" ]; then
    rm -rf "$OUTPUT_DIR/$NAME"
    echo "Removed $OUTPUT_DIR/$NAME/"
fi

echo "Inventory updated. Regenerating configs..."
python3 "$SCRIPT_DIR/generate_configs.py" -i "$INVENTORY" -o "$OUTPUT_DIR"

echo ""
echo "Site '$NAME' removed."
echo "Next steps:"
echo "  1. Update hub: sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-bridge"
echo "  2. Decommission the remote device"
