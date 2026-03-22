#!/bin/bash
set -euo pipefail

# wg-mcast: Health check for hub tunnel and bridge status.
# Run via cron every 5 minutes:
#   */5 * * * * /usr/local/bin/wg-mcast-health-check >> /var/log/wg-mcast-health.log 2>&1
#
# Optional: set WG_MCAST_WEBHOOK to a URL for alerts.

WG_INTERFACE="${WG_MCAST_INTERFACE:-wg0}"
BRIDGE="${WG_MCAST_BRIDGE:-br-mcast}"
STALE_THRESHOLD=300  # seconds (5 minutes)
WEBHOOK_URL="${WG_MCAST_WEBHOOK:-}"
LOG_PREFIX="[wg-mcast-health]"

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "$(timestamp) $LOG_PREFIX $1"
}

alert() {
    log "ALERT: $1"
    if [ -n "$WEBHOOK_URL" ]; then
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"wg-mcast ALERT: $1\"}" \
            >/dev/null 2>&1 || true
    fi
}

# --- Check WireGuard interface exists ---
if ! ip link show "$WG_INTERFACE" >/dev/null 2>&1; then
    alert "WireGuard interface $WG_INTERFACE is DOWN"
    exit 1
fi

# --- Check bridge exists ---
if ! ip link show "$BRIDGE" >/dev/null 2>&1; then
    alert "Bridge $BRIDGE is DOWN"
    exit 1
fi

# --- Check peer handshakes ---
NOW=$(date +%s)
STALE_PEERS=""
TOTAL_PEERS=0
HEALTHY_PEERS=0

while IFS=$'\t' read -r peer_pubkey last_handshake; do
    TOTAL_PEERS=$((TOTAL_PEERS + 1))

    if [ "$last_handshake" -eq 0 ]; then
        STALE_PEERS="${STALE_PEERS}  - ${peer_pubkey:0:8}... (never connected)\n"
        continue
    fi

    AGE=$((NOW - last_handshake))
    if [ "$AGE" -gt "$STALE_THRESHOLD" ]; then
        STALE_PEERS="${STALE_PEERS}  - ${peer_pubkey:0:8}... (last seen ${AGE}s ago)\n"
    else
        HEALTHY_PEERS=$((HEALTHY_PEERS + 1))
    fi
done < <(wg show "$WG_INTERFACE" latest-handshakes)

if [ -n "$STALE_PEERS" ]; then
    STALE_COUNT=$((TOTAL_PEERS - HEALTHY_PEERS))
    alert "$STALE_COUNT/$TOTAL_PEERS peers stale:\n$STALE_PEERS"
fi

# --- Check bridge ports ---
BRIDGE_PORTS=$(bridge link show | grep -c "$BRIDGE" || true)
if [ "$BRIDGE_PORTS" -eq 0 ]; then
    alert "Bridge $BRIDGE has no ports"
fi

log "OK: $HEALTHY_PEERS/$TOTAL_PEERS peers healthy, $BRIDGE_PORTS bridge ports"
