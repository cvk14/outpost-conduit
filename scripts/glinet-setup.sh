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

# --- Install prerequisites ---
echo "[1/5] Installing prerequisites..."
opkg update 2>/dev/null || echo "Warning: opkg update failed (some repos may be unavailable)"

# Install kmod-gre for GRETAP support
if ! lsmod | grep -q ip_gre; then
    echo "Installing kmod-gre..."
    opkg install kmod-gre 2>/dev/null || echo "Warning: kmod-gre install failed — install manually via LuCI if needed"
fi

# Install WireGuard if needed
if ! command -v wg >/dev/null 2>&1; then
    echo "Installing WireGuard..."
    opkg install wireguard-tools kmod-wireguard 2>/dev/null || echo "Warning: WireGuard install failed"
fi

# Install LuCI if needed
if [ ! -d /www/luci-static ]; then
    echo "Installing LuCI..."
    opkg install luci 2>/dev/null || echo "Warning: LuCI install failed"
fi

# --- Install WireGuard config ---
echo "[2/5] Configuring WireGuard..."
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
echo "[3/5] Restarting network (connection may drop briefly)..."
/etc/init.d/network restart

# Wait for WireGuard to come up
echo "[4/7] Waiting for WireGuard handshake..."
sleep 10

# --- Install GRETAP setup script ---
echo "[5/7] Installing GRETAP..."
cp "$CONFIG_DIR/setup-gretap.sh" /usr/bin/wg-mcast-gretap-up
chmod 755 /usr/bin/wg-mcast-gretap-up

# --- Install multicast relay (socat-based) ---
# GRETAP RX works (hub→site) but TX is broken on SiFlower kernel 4.14.
# The relay forwards local mDNS multicast as unicast to the hub.
echo "[6/7] Installing multicast relay..."

# Parse hub tunnel IP from wg0.conf
HUB_IP=$(grep "^AllowedIPs" "$CONFIG_DIR/wg0.conf" | awk '{print $3}' | cut -d/ -f1 | head -1)
# AllowedIPs is the hub network; hub IP is always .0.1
HUB_IP="172.27.0.1"

cat > /usr/bin/wg-mcast-relay.sh << RELAYEOF
#!/bin/sh
# Outpost Conduit multicast relay (site mode)
# Captures mDNS on br-lan, forwards as unicast to hub relay port
HUB=${HUB_IP}

# Kill any existing relay
killall socat 2>/dev/null || true
sleep 1

# LAN multicast -> unicast to hub
socat -u UDP4-RECVFROM:5353,ip-add-membership=224.0.0.251:0.0.0.0,reuseaddr,fork UDP4-SENDTO:\${HUB}:5350 &

# Unicast from hub -> multicast on LAN
socat -u UDP4-RECVFROM:5350,reuseaddr,fork UDP4-DATAGRAM:224.0.0.251:5353,bind=:0 &

echo "Multicast relay running"
RELAYEOF
chmod 755 /usr/bin/wg-mcast-relay.sh

# Create init script for GRETAP + relay
echo "[7/7] Installing init scripts..."
cat > /etc/init.d/wg-mcast-gretap << 'INITSCRIPT'
#!/bin/sh /etc/rc.common

START=99
STOP=10

start() {
    # Wait for WireGuard handshake
    sleep 5
    /usr/bin/wg-mcast-gretap-up
    /usr/bin/wg-mcast-relay.sh
}

stop() {
    killall socat 2>/dev/null || true
    ip link del gretap0 2>/dev/null || true
}
INITSCRIPT

chmod 755 /etc/init.d/wg-mcast-gretap
/etc/init.d/wg-mcast-gretap enable

# Start everything
/usr/bin/wg-mcast-gretap-up
/usr/bin/wg-mcast-relay.sh

echo ""
echo "=== GL.iNet setup complete ==="
echo "WireGuard: wg show"
echo "GRETAP:    ip link show gretap0"
echo "Relay:     ps | grep socat"
