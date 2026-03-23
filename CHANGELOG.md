# Outpost Conduit — Changelog

## v1.0.0 — 2026-03-22/23

### Core Infrastructure
- **WireGuard VPN** hub-and-spoke topology with `172.27.0.0/16` tunnel network
- **GRETAP Layer 2 overlay** inside WireGuard for multicast bridging
- **Multicast relay** (socat + Python) to work around broken GRETAP TX on GL.iNet SFT1200 kernel 4.14
- **Site-to-site relay** via hub — packets from any site are forwarded to all other sites
- Hub VM on Proxmox (Ubuntu 24.04, `leakycauldron`, 10.0.0.36)
- Cloudflare Tunnel for web UI access at `mcast.cvk.io`

### Config Generator (`scripts/generate_configs.py`)
- Reads `sites.yaml` inventory, generates WireGuard configs + GRETAP scripts + keys
- Preserves existing keys on re-run (won't invalidate deployed configs)
- Supports GL.iNet (OpenWrt) and Cradlepoint (Pi sidecar) site types
- 40 unit tests (TDD)

### Setup Scripts
- `hub-setup.sh` — provisions hub VM with WireGuard, bridge, GRETAP, systemd services
- `glinet-setup.sh` — configures GL.iNet via UCI, installs GRETAP + multicast relay + init scripts
- `pi-setup.sh` — configures Raspberry Pi sidecar with systemd services
- `web-setup.sh` — provisions web UI with venv, credentials, systemd service
- `relay-setup.sh` — installs hub multicast relay as systemd service
- `add-site.sh` / `remove-site.sh` — day-2 site management

### CLI Enrollment
- One-liner enrollment: `curl <hub>/api/enroll/script?name=X&token=T&hub=URL | sh`
- Auto-installs prerequisites (kmod-gre, curl, unzip) on GL.iNet
- Generates configs, pushes to hub, restarts hub services automatically
- Install command modal in web UI with copy-to-clipboard

### Web UI (FastAPI + Vanilla JS)
- **Dashboard** — real-time site status (online/stale/offline), summary cards
- **Health Monitor** — periodic ping + multicast tests on all sites with configurable interval
- **Live Multicast Capture** — streams tcpdump via WebSocket, decodes mDNS payloads
  - Color-coded protocols (mDNS green, SSDP yellow, Relay purple)
  - Motorola/APX radio detection with green highlighting + RADIO badge
  - Pause/Resume, Export .md, 1200px viewport
- **Radio Traffic Log** — persistent server-side logging of detected radio packets
  - Table with time, IP, MAC, device info, services, hostnames
  - Export .md button, auto-logged during capture
- **Sites Management** — CRUD with add/edit/delete, install command modal
- **Diagnostics** — per-site ping, MTU path test, multicast hub→site and site→hub tests
  - Live progress log with animated spinner
- **Settings** — health check interval, SMTP email alerts, test email button
- **User Accounts** — multi-admin with password + WebAuthn passkey support
- **Authentication** — JWT tokens, bcrypt passwords, passkey login
- WebSocket stats streaming (5s interval)
- Dark theme, no build step

### Network Architecture

#### Addressing (current test deployment)
| Site | Router IP | DHCP Range | Tunnel IP |
|---|---|---|---|
| Hub (br-mcast) | 192.168.8.254 | — | 172.27.0.1 |
| 2500marcus | 192.168.8.1 | .10-.24 | 172.27.3.1 |
| HempsteadArmory | 192.168.8.2 | .30-.44 | 172.27.2.1 |
| Burke | 192.168.8.1 | .50-.64 | 172.27.1.1 |

All sites on `192.168.8.0/24` for mDNS compatibility with APX radios.

#### Multicast Flow
```
Hub → Site (GRETAP, works):
  Hub br-mcast → GRETAP encapsulate → WireGuard → site gretap0 → br-lan

Site → Hub (socat relay, workaround for broken GRETAP TX):
  br-lan mDNS → socat captures → unicast UDP:5350 → WireGuard → hub relay

Site → Site (hub relay forwards):
  Site A socat → hub:5350 → hub relay → unicast to Site B:5350 → socat → br-lan multicast
```

#### APX Radio OTAP Discovery
- Radio announces `_otap._tcp.local.` via mDNS (224.0.0.251:5353) on boot
- Announcement contains: model (APX 8000), serial, SRV port (52010), TXT records
- Only fires during fresh DHCP Discover, not cached lease reuse
- Requires `/24` subnet mask — radio won't announce on `/16`
- RM queries `_otap._tcp.local.` periodically from Device Programmer
- **Current status:** relay chain proven working, timing-sensitive — RM needs to be on same L2 segment as radio for reliable discovery

### Known Issues / Limitations
1. **GL.iNet SFT1200 kernel 4.14** — GRETAP TX path broken (overrun errors). Workaround: socat multicast relay
2. **APX OTAP timing** — radio announces once on boot, brief window. Relay adds latency. Fix: move RM to hub network for direct GRETAP delivery
3. **APX requires /24 subnet** — OTAP won't activate on /16 networks
4. **DHCP lease caching** — radio reuses cached lease across battery pulls, skipping OTAP announcement. Need to clear leases on router before boot
5. **Dropbear SSH** — GL.iNet uses RSA keys only (no ed25519). SSH manager tries RSA first

### Services (on hub VM)
| Service | Port | systemd unit |
|---|---|---|
| WireGuard | 51820/udp | `wg-quick@wg0` |
| GRETAP Bridge | — | `wg-mcast-bridge` |
| Multicast Relay | 5350/udp | `outpost-conduit-relay` |
| Web UI | 8080/tcp | `outpost-conduit-web` |
| Cloudflare Tunnel | — | `cloudflared` |

### Dependencies (all open source)
| Component | License | Purpose |
|---|---|---|
| WireGuard | GPLv2 | Encrypted tunnels |
| iproute2 | GPLv2 | GRETAP + bridge management |
| Python 3 + FastAPI | PSF / MIT | Web UI + config generator |
| uvicorn | BSD | ASGI server |
| asyncssh | EPL-2.0 | Remote SSH management |
| socat | GPLv2 | Multicast relay on routers |
| py-webauthn | BSD | Passkey authentication |
| PyYAML | MIT | Config parsing |
| bcrypt + PyJWT | Apache/MIT | Auth |
