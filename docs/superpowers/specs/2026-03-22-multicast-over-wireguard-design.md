# wg-mcast — Multicast over WireGuard

## Problem

Many applications rely on IP multicast (224.0.0.0/4) for device discovery and management on the local network. WireGuard operates at Layer 3 and only carries unicast IP packets — multicast and broadcast traffic is silently dropped. This makes it impossible to use multicast-dependent applications (such as radio management, AV control, mDNS/Bonjour, SSDP/UPnP) across WireGuard tunnels.

## Solution

A Layer 2 overlay using GRETAP tunnels inside WireGuard, bridged together at the hub to create a single flat multicast domain spanning all sites. The tooling automates configuration for hub-and-spoke deployments at scale.

## License

MIT — see LICENSE file.

## Constraints

- **Hub:** Windows or Linux host. When using Windows (e.g., Windows 11 Pro), a Hyper-V Linux VM provides the bridging and tunnel termination since Windows lacks native GRETAP/bridge support. On a Linux host, the hub runs natively.
- **Remote routers (OpenWrt-based, e.g., GL.iNet):** Full Linux flexibility for WireGuard, GRETAP, and bridging.
- **Remote routers (locked-down firmware, e.g., Cradlepoint):** Cannot run custom tunneling. Requires a Linux sidecar (e.g., Raspberry Pi) on the LAN to handle WireGuard + GRETAP + bridging.
- **Scale:** 20+ sites. Manual configuration is unsustainable — automation required.
- **Multicast applications:** Any application using IP multicast for discovery or data (e.g., radio management, AV systems, IoT).

## Architecture

### Topology

```
                     ┌──────────────────────────────────────┐
                     │         HUB (Windows 11 Pro)         │
                     │                                      │
                     │  ┌─────────────┐  ┌───────────────┐  │
                     │  │ Radio Mgmt  │  │ Hyper-V Linux  │  │
                     │  │ Application ◄──► VM             │  │
                     │  └─────────────┘  │                │  │
                     │  Hyper-V vSwitch   │ br-mcast       │  │
                     │                   │ ├─ gretap1     │  │
                     │                   │ ├─ gretap2     │  │
                     │                   │ ├─ gretapN     │  │
                     │                   │ wg0 (all peers)│  │
                     │                   └───────┬────────┘  │
                     └───────────────────────────┼───────────┘
                                                 │
                         WireGuard (encrypted L3, UDP:51820)
                                                 │
              ┌──────────────────┬───────────────┼──────────────┐
              │                  │               │              │
    ┌─────────▼────────┐ ┌──────▼───────┐ ┌─────▼──────────────▼─┐
    │ GL.iNet (OpenWrt) │ │ GL.iNet      │ │ Cradlepoint site     │
    │ wg0 → gretap0    │ │ wg0 → gretap0│ │ Cradlepoint = WAN    │
    │ br-lan (bridged)  │ │ br-lan       │ │ Pi: wg0 → gretap0   │
    │ eth0 → APX radios │ │ eth0 → APX   │ │ br-lan → eth0 → APX │
    └──────────────────┘ └──────────────┘ └──────────────────────┘
```

### IP Addressing

| Component | Address |
|---|---|
| WireGuard tunnel network | `172.27.0.0/16` |
| Hub tunnel IP | `172.27.0.1` |
| Site N tunnel IP | `172.27.N.1` (e.g., site 1 = `172.27.1.1`) |
| WireGuard listen port | `51820/udp` |
| GRETAP endpoints | Use WireGuard tunnel IPs (no extra addressing) |
| Bridge (br-mcast) | Carries the multicast application's existing subnet |

This scheme supports up to 255 sites.

### Hub Side: Hyper-V Linux VM

**VM specs:** Lightweight Linux (Ubuntu Server 24.04 or Alpine). 1-2 vCPUs, 512MB-1GB RAM. Two virtual NICs:
1. **Management NIC** — for SSH access and WireGuard's UDP endpoint (bridged to the physical NIC / WAN)
2. **Multicast NIC** — connected to an internal Hyper-V vSwitch shared with the Windows host. This carries the bridged L2 traffic so the multicast application (e.g., Motorola Radio Management) sees all remote devices.

**Network stack on the VM:**

```
wg0 (WireGuard interface, all peers)
  ├── Peer: site1 (172.27.1.1/32, endpoint: <site1-wan-ip>:51820)
  ├── Peer: site2 (172.27.2.1/32, endpoint: <site2-wan-ip>:51820)
  └── Peer: siteN ...

gretap1 (GRETAP tunnel: local 172.27.0.1, remote 172.27.1.1)
gretap2 (GRETAP tunnel: local 172.27.0.1, remote 172.27.2.1)
gretapN ...

br-mcast (Linux bridge)
  ├── gretap1
  ├── gretap2
  ├── gretapN
  └── eth1 (Multicast NIC → Hyper-V vSwitch → Windows host)
```

**Bridge configuration:**
- STP enabled to prevent loops
- Storm control: cap broadcast/multicast at 1 Mbps per port
- Bridge MTU: 1380

### GL.iNet Remote Sites (OpenWrt)

```
wg0 (WireGuard interface)
  └── Peer: hub (172.27.0.1/32, endpoint: <hub-wan-ip>:51820)

gretap0 (GRETAP tunnel: local 172.27.X.1, remote 172.27.0.1)

br-lan (existing OpenWrt LAN bridge)
  ├── gretap0 (added to existing bridge)
  └── eth0 (LAN port — APX radios connected here)
```

- WireGuard and GRETAP configured via UCI (OpenWrt's config system)
- GRETAP interface added to `br-lan` so multicast reaches the LAN natively
- MTU: WireGuard = 1420, GRETAP/bridge = 1380

### Cradlepoint Remote Sites (Pi Sidecar)

The Cradlepoint router handles WAN/cellular connectivity only. A Raspberry Pi on the LAN handles all VPN and multicast:

```
Cradlepoint
  └── LAN port → switch → Pi eth0 + APX radios

Raspberry Pi:
  wg0 (WireGuard interface)
    └── Peer: hub (172.27.0.1/32, endpoint: <hub-wan-ip>:51820)

  gretap0 (GRETAP tunnel: local 172.27.X.1, remote 172.27.0.1)

  br0 (bridge)
    ├── gretap0
    └── eth0 (Pi's ethernet — on same LAN as radios)
```

- Pi runs Raspberry Pi OS Lite (headless)
- WireGuard traffic exits via Cradlepoint's default gateway
- Pi's eth0 is bridged (not routed) — it becomes transparent to the LAN
- Systemd services for WireGuard + GRETAP + bridge auto-start on boot

## Encapsulation & MTU

```
Original multicast frame              ~100-1380 bytes
  + GRETAP header (GRE + Ethernet)     24 bytes
  + WireGuard overhead                  60 bytes
  + Outer UDP/IP                        28 bytes
                                       ≈ 112 bytes overhead
```

| Interface | MTU |
|---|---|
| WAN (physical) | 1500 |
| WireGuard (wg0) | 1420 |
| GRETAP (gretapN) | 1380 |
| Bridge (br-mcast / br-lan) | 1380 |

Setting the bridge/GRETAP MTU to 1380 prevents fragmentation across the entire path.

## Security

### Key Management

- Each site gets a unique WireGuard key pair, generated on the device or by the config generator
- Hub's public key is distributed to all sites; site public keys are registered on the hub
- **Preshared keys (PSK):** One PSK per hub↔site pair for post-quantum resistance
- Private keys are stored only in the site's local config. Never committed to version control.
- The config generator outputs private keys to per-site directories; these are transferred securely (e.g., SCP, USB) and deleted from the generator host.

### Firewall

- Hub VM: only `51820/udp` (WireGuard) exposed to WAN. Bridge interfaces are internal-only.
- GL.iNet/Pi: only outbound `51820/udp` to hub. No inbound ports needed (WireGuard is peer-initiated from the spoke side).
- The bridge carries only multicast/L2 traffic. General site traffic routes normally via WireGuard Layer 3 (if needed) or via the Cradlepoint/GL.iNet's own WAN.

### Bridge Isolation

The GRETAP bridge is dedicated to multicast traffic. It does NOT carry general internet or inter-site traffic. This limits the blast radius of any bridge-level issue (broadcast storm, misconfiguration) to the multicast domain only.

## Resilience & Monitoring

### Auto-Recovery

- **Hub VM:** Systemd services for WireGuard, GRETAP tunnels, and bridge. `Restart=always` ensures recovery from crashes.
- **GL.iNet:** OpenWrt init scripts with procd supervision.
- **Pi:** Systemd services with `Restart=always`.

### Keepalives

`PersistentKeepalive = 25` on all peers. Critical for:
- Cradlepoint cellular uplinks (carrier NAT)
- GL.iNet sites behind NAT
- Ensuring the hub always has a current endpoint for each peer

### Health Monitoring

A health check script on the hub VM that runs periodically (cron, every 5 minutes):
1. `wg show wg0 latest-handshakes` — flag any peer with handshake older than 5 minutes
2. Ping each site's GRETAP endpoint (bridge IP) — verify L2 path is up
3. Check bridge port state (`bridge link show`)
4. Log results; alert via webhook/email if a site is unreachable

### Storm Control

The hub bridge (`br-mcast`) applies per-port storm control:
- Broadcast rate limit: 1 Mbps per port
- Multicast rate limit: 1 Mbps per port
- This prevents a single misbehaving site from flooding the entire bridge

## Automation & Configuration Management

### Site Inventory

A YAML file (`sites.yaml`) defines all sites:

```yaml
hub:
  wan_ip: "203.0.113.10"          # or dynamic DNS hostname
  tunnel_ip: "172.27.0.1"
  listen_port: 51820

sites:
  - name: "site-01-north"
    type: "glinet"                 # or "cradlepoint"
    tunnel_ip: "172.27.1.1"
    wan_ip: "198.51.100.1"         # or "dynamic" for DDNS/NAT
    description: "North district station"

  - name: "site-02-south"
    type: "cradlepoint"
    tunnel_ip: "172.27.2.1"
    wan_ip: "dynamic"
    description: "South district mobile unit"
```

### Config Generator

A Python script (`generate_configs.py`) reads `sites.yaml` and outputs:

```
output/
  hub/
    wg0.conf              # WireGuard config with all peers
    setup-bridge.sh        # Creates br-mcast + all GRETAP tunnels
    teardown-bridge.sh     # Removes bridge + tunnels
  site-01-north/
    wg0.conf              # WireGuard client config
    setup-gretap.sh        # Creates GRETAP + bridges to br-lan
    keys/
      privatekey           # Generated WireGuard private key
      publickey            # Corresponding public key
      presharedkey         # PSK for this site↔hub pair
  site-02-south/
    wg0.conf
    setup-gretap.sh
    keys/
      ...
```

### Day-2 Operations

- **`add-site.sh <name> <type> [wan_ip]`** — adds a site to `sites.yaml`, regenerates hub config, outputs new site config
- **`remove-site.sh <name>`** — removes site from inventory, tears down hub-side GRETAP, regenerates hub config

## Deliverables

1. **Hub VM setup script** (`scripts/hub-setup.sh`) — installs WireGuard, configures bridge, GRETAP tunnels, systemd services, STP, storm control
2. **GL.iNet setup script** (`scripts/glinet-setup.sh`) — OpenWrt shell script: WireGuard + GRETAP + bridge via UCI
3. **Pi setup script** (`scripts/pi-setup.sh`) — Raspberry Pi OS: WireGuard + GRETAP + bridge via systemd
4. **Config generator** (`scripts/generate_configs.py`) — reads `sites.yaml`, outputs all configs and keys
5. **Site inventory template** (`sites.yaml`) — YAML defining all sites
6. **Add/remove site scripts** (`scripts/add-site.sh`, `scripts/remove-site.sh`)
7. **Health monitor** (`scripts/health-check.sh`) — cron-based tunnel and bridge health checks
8. **Setup guide** (`docs/setup-guide.md`) — step-by-step deployment instructions

## Dependencies (All Open Source)

| Component | License | Purpose |
|---|---|---|
| WireGuard (kernel module + `wg` tools) | GPLv2 | Encrypted tunnel |
| iproute2 (`ip link`, `bridge`) | GPLv2 | GRETAP + bridge management |
| Python 3 + PyYAML | PSF / MIT | Config generator |
| OpenWrt (GL.iNet firmware) | GPLv2 | Remote site OS |
| Raspberry Pi OS Lite | Various FOSS | Cradlepoint sidecar OS |
| systemd | LGPLv2.1 | Service management |

No closed-source dependencies. The project works with any multicast application — Motorola APX Radio Management is the primary use case but is not a dependency of the tooling itself.

## Out of Scope

- General inter-site routing (sites don't need to reach each other, only the hub)
- Multicast application (e.g., Motorola Radio Management) installation or configuration
- Cradlepoint WAN/cellular configuration
- DNS, DHCP, or other LAN services at remote sites
- Automated firmware updates for GL.iNet or Pi devices
