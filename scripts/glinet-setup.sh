#!/bin/sh
set -e

# wg-mcast: GL.iNet (OpenWrt) setup script
# Run on the GL.iNet router.
# Usage: ./glinet-setup.sh <config-dir>
#   <config-dir> = path to generated site config (output/site-XX/)

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"

if [ ! -f "$CONFIG_DIR/wg0.conf" ]; then
    echo "Error: $CONFIG_DIR/wg0.conf not found" >&2
    exit 1
fi

echo "=== wg-mcast GL.iNet Setup ==="

# --- Install WireGuard if needed ---
echo "[1/4] Checking WireGuard..."
if ! command -v wg >/dev/null 2>&1; then
    echo "Installing WireGuard..."
    opkg update
    opkg install wireguard-tools kmod-wireguard
fi

# --- Install WireGuard config ---
echo "[2/4] Configuring WireGuard..."
mkdir -p /etc/wireguard
cp "$CONFIG_DIR/wg0.conf" /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# --- Configure WireGuard interface via UCI ---
# Parse values from wg0.conf
WG_PRIVKEY=$(grep "^PrivateKey" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')
WG_ADDR=$(grep "^Address" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')
PEER_PUBKEY=$(grep "^PublicKey" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')
PEER_PSK=$(grep "^PresharedKey" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')
PEER_ENDPOINT=$(grep "^Endpoint" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')
PEER_ALLOWED=$(grep "^AllowedIPs" "$CONFIG_DIR/wg0.conf" | awk '{print $3}')

# Create WireGuard interface
uci set network.wgmcast=interface
uci set network.wgmcast.proto='wireguard'
uci set network.wgmcast.private_key="$WG_PRIVKEY"
uci set network.wgmcast.addresses="$WG_ADDR"
uci set network.wgmcast.mtu='1420'

# Add peer
uci set network.wgmcast_peer=wireguard_wgmcast
uci set network.wgmcast_peer.public_key="$PEER_PUBKEY"
uci set network.wgmcast_peer.preshared_key="$PEER_PSK"
uci set network.wgmcast_peer.endpoint_host="$(echo "$PEER_ENDPOINT" | cut -d: -f1)"
uci set network.wgmcast_peer.endpoint_port="$(echo "$PEER_ENDPOINT" | cut -d: -f2)"
uci set network.wgmcast_peer.persistent_keepalive='25'
uci add_list network.wgmcast_peer.allowed_ips="$PEER_ALLOWED"
uci set network.wgmcast_peer.route_allowed_ips='1'

uci commit network

# --- Firewall: allow WireGuard traffic ---
uci set firewall.wgmcast=zone
uci set firewall.wgmcast.name='wgmcast'
uci set firewall.wgmcast.input='ACCEPT'
uci set firewall.wgmcast.output='ACCEPT'
uci set firewall.wgmcast.forward='ACCEPT'
uci set firewall.wgmcast.network='wgmcast'

uci set firewall.wgmcast_lan=forwarding
uci set firewall.wgmcast_lan.src='wgmcast'
uci set firewall.wgmcast_lan.dest='lan'

uci set firewall.lan_wgmcast=forwarding
uci set firewall.lan_wgmcast.src='lan'
uci set firewall.lan_wgmcast.dest='wgmcast'

uci commit firewall

# Restart networking
/etc/init.d/network restart

# --- Install GRETAP setup script ---
echo "[3/4] Installing GRETAP script..."
cp "$CONFIG_DIR/setup-gretap.sh" /usr/local/bin/wg-mcast-gretap-up
chmod 755 /usr/local/bin/wg-mcast-gretap-up

# Create init script for GRETAP (runs after WireGuard is up)
cat > /etc/init.d/wg-mcast-gretap << 'INITSCRIPT'
#!/bin/sh /etc/rc.common

START=99
STOP=10

start() {
    # Wait briefly for WireGuard handshake
    sleep 5
    /usr/local/bin/wg-mcast-gretap-up
}

stop() {
    ip link del gretap0 2>/dev/null || true
}
INITSCRIPT

chmod 755 /etc/init.d/wg-mcast-gretap
/etc/init.d/wg-mcast-gretap enable

# --- Start GRETAP ---
echo "[4/4] Starting GRETAP..."
/etc/init.d/wg-mcast-gretap start

echo ""
echo "=== GL.iNet setup complete ==="
echo "WireGuard: wg show"
echo "GRETAP:    ip link show gretap0"
echo "Bridge:    bridge link show"
