# Outpost Conduit

**Multicast over WireGuard using GRETAP Layer 2 overlay.**

Outpost Conduit tunnels IP multicast (224.0.0.0/4) across encrypted WireGuard VPN tunnels in a hub-and-spoke topology. It solves the fundamental problem that WireGuard is Layer 3 only and silently drops multicast/broadcast traffic.

Built for managing Motorola APX P25 radios via Radio Management over WireGuard, but works with any multicast-dependent application (mDNS/Bonjour, SSDP/UPnP, AV control, IoT discovery).

## How It Works

```
                         HUB (Linux VM)
                    ┌─────────────────────┐
                    │  br-mcast (bridge)   │
                    │  ├─ gretap-site1     │
                    │  ├─ gretap-site2     │    Multicast app sees
                    │  ├─ gretap-siteN     │◄── a flat L2 network
                    │  └─ eth1 (mcast NIC) │    with all remote devices
                    │                      │
                    │  wg0 (WireGuard)     │
                    └──────────┬───────────┘
                               │
              Encrypted WireGuard tunnels (UDP)
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
   │  GL.iNet    │     │  GL.iNet    │     │  Raspberry  │
   │  (OpenWrt)  │     │  (OpenWrt)  │     │  Pi sidecar │
   │  wg + gretap│     │  wg + gretap│     │  wg + gretap│
   │  → br-lan   │     │  → br-lan   │     │  → br0      │
   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
          │                    │                    │
     Local LAN            Local LAN            Local LAN
    (APX radios)         (APX radios)         (APX radios)
```

1. A GRETAP tunnel (Layer 2) runs inside each WireGuard tunnel (Layer 3)
2. All GRETAP endpoints are bridged together at the hub into `br-mcast`
3. The multicast application connects to this bridge via a Hyper-V virtual switch
4. Multicast traffic flows transparently — devices at remote sites appear to be on the same LAN

## Supported Remote Sites

| Router Type | How It Works |
|---|---|
| **GL.iNet / OpenWrt** | WireGuard + GRETAP configured directly on the router |
| **Cradlepoint / locked firmware** | Raspberry Pi sidecar on the LAN handles WireGuard + GRETAP; Cradlepoint provides WAN only |

## Quick Start

### 1. Install dependencies

```bash
# macOS (build machine)
brew install wireguard-tools
pip3 install pyyaml

# Hub VM (Ubuntu)
apt install wireguard wireguard-tools iproute2 bridge-utils
```

### 2. Create your site inventory

```bash
cp sites.yaml.example sites.yaml
```

Edit `sites.yaml` with your hub WAN IP and remote sites:

```yaml
hub:
  wan_ip: "203.0.113.10"
  tunnel_ip: "172.27.0.1"
  listen_port: 51820

sites:
  - name: "north-station"
    type: "glinet"
    tunnel_ip: "172.27.1.1"
    wan_ip: "198.51.100.1"
    description: "North district"

  - name: "south-mobile"
    type: "cradlepoint"
    tunnel_ip: "172.27.2.1"
    wan_ip: "dynamic"
    description: "South district mobile unit"
```

### 3. Generate configs

```bash
python3 scripts/generate_configs.py -i sites.yaml -o output/
```

This creates WireGuard configs, GRETAP bridge scripts, and key material for the hub and every remote site:

```
output/
  hub/
    wg0.conf            # WireGuard config (all peers)
    setup-bridge.sh      # Creates br-mcast + GRETAP tunnels
    teardown-bridge.sh   # Removes bridge + tunnels
    keys/
  north-station/
    wg0.conf            # WireGuard client config
    setup-gretap.sh      # Creates GRETAP + bridges to br-lan
    keys/
  south-mobile/
    wg0.conf
    setup-gretap.sh      # Creates GRETAP + br0 + bridges eth0
    keys/
```

Re-running the generator **preserves existing keys** — it won't invalidate deployed configs.

### 4. Deploy

```bash
# Hub VM
sudo ./scripts/hub-setup.sh output/hub/

# GL.iNet sites (SCP config dir to router first)
./scripts/glinet-setup.sh output/north-station/

# Cradlepoint sites (SCP config dir to Pi first)
sudo ./scripts/pi-setup.sh output/south-mobile/
```

### 5. Verify

```bash
# On the hub VM
wg show wg0                        # Check peer handshakes
bridge link show br-mcast          # Check bridge ports
```

See [docs/setup-guide.md](docs/setup-guide.md) for the complete deployment guide including Hyper-V VM setup, multicast verification, and troubleshooting.

## Day-2 Operations

```bash
# Add a new site
./scripts/add-site.sh site-03-east glinet 198.51.100.3

# Remove a site
./scripts/remove-site.sh site-03-east
```

Both scripts update the inventory and regenerate configs. After running, restart the hub services and deploy the new site config.

## Health Monitoring

Install on the hub VM as a cron job:

```bash
# Check every 5 minutes, alert via webhook
sudo cp scripts/health-check.sh /usr/local/bin/wg-mcast-health-check
echo "*/5 * * * * WG_MCAST_WEBHOOK=https://hooks.example.com/alert /usr/local/bin/wg-mcast-health-check >> /var/log/wg-mcast-health.log 2>&1" | sudo crontab -
```

Monitors WireGuard peer handshakes, bridge port status, and sends alerts for stale or disconnected sites.

## Network Details

| Parameter | Value |
|---|---|
| Tunnel network | `172.27.0.0/16` (supports 254 sites) |
| WireGuard port | `51820/udp` |
| WireGuard MTU | 1420 |
| GRETAP / bridge MTU | 1380 |
| Overhead per packet | ~112 bytes |
| Keepalive interval | 25 seconds |

## Project Structure

```
scripts/
  generate_configs.py   # Config generator (Python)
  hub-setup.sh          # Hub VM provisioning
  glinet-setup.sh       # GL.iNet (OpenWrt) provisioning
  pi-setup.sh           # Raspberry Pi provisioning
  add-site.sh           # Add a remote site
  remove-site.sh        # Remove a remote site
  health-check.sh       # Hub health monitoring
tests/                  # 40 tests (pytest)
docs/
  setup-guide.md        # Full deployment guide
```

## Dependencies

All open source:

| Component | License | Purpose |
|---|---|---|
| WireGuard | GPLv2 | Encrypted tunnels |
| iproute2 | GPLv2 | GRETAP + bridge management |
| Python 3 + PyYAML | PSF / MIT | Config generator |
| systemd | LGPLv2.1 | Service management |

## License

MIT — see [LICENSE](LICENSE).
