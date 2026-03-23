# Outpost Conduit — Build Session Log

**Date:** 2026-03-22 to 2026-03-23
**Duration:** ~12 hours continuous session

---

## Phase 1: Design & Planning

### Brainstorming
- **Goal:** Multicast over WireGuard for Motorola APX Radio Management (OTAP)
- **Topology:** Hub-and-spoke, 20+ remote sites
- **Hub:** Windows 11 Pro (later changed to Proxmox Ubuntu VM)
- **Remote routers:** GL.iNet SFT1200 (OpenWrt) + Cradlepoint with Pi sidecar
- **Approach chosen:** GRETAP Layer 2 overlay inside WireGuard tunnels

### Design Decisions
- GRETAP over WireGuard (Approach A) — most transparent to Radio Management
- `172.27.0.0/16` tunnel network (user requested, avoids 10.x conflicts)
- Python config generator + shell setup scripts
- MIT license, open source, no closed-source dependencies

### Spec & Plan
- Design spec: `docs/superpowers/specs/2026-03-22-multicast-over-wireguard-design.md`
- Implementation plan: `docs/superpowers/plans/2026-03-22-wg-mcast-implementation.md`
- 12 tasks, TDD approach, 40 tests

## Phase 2: Core Implementation

### Config Generator (Tasks 1-5)
- Python script reads `sites.yaml`, generates WireGuard configs + GRETAP scripts + keys
- Key preservation on re-run (won't invalidate deployed configs)
- Gap-aware tunnel IP allocation
- 40 tests passing, shellcheck clean on all scripts

### Setup Scripts (Tasks 6-10)
- Hub VM setup with systemd services
- GL.iNet setup via UCI (WireGuard + GRETAP + bridge)
- Raspberry Pi setup with systemd
- Day-2 add/remove site scripts
- Health check monitor

### Deployment to Hub VM
- Proxmox Ubuntu 24.04 VM (`leakycauldron`, 10.0.0.36)
- Required second NIC (ens19) for multicast bridge — caught before bricking the VM
- WireGuard + bridge + GRETAP running as systemd services

## Phase 3: Web UI

### Backend (FastAPI)
- Auth (JWT + bcrypt), stats collector, inventory manager
- Sites CRUD with config generation
- SSH remote management (asyncssh)
- Deploy routes, diagnostics, health monitor
- 113+ tests

### Frontend (Vanilla JS SPA)
- Dashboard with live stats via WebSocket
- Sites CRUD with install command modal
- Diagnostics with live progress log
- Settings (health interval, SMTP alerts)
- User accounts with passkey/WebAuthn support
- Live multicast traffic capture with mDNS decoding
- Radio traffic detection and persistent logging
- Dark theme, no build step

### CLI Enrollment
- One-liner: `curl <hub>/api/enroll/script?... | sh`
- Auto-installs prerequisites, generates configs, applies to hub
- Web UI shows install command per site with copy button

## Phase 4: First Site Enrollments

### HempsteadArmory (GL.iNet SFT1200)
- First enrollment via CLI one-liner
- **Issue:** `kmod-gre` not installed — installed via LuCI
- **Issue:** GRETAP had zeroed MAC address — assigned deterministic MAC
- **Issue:** `/usr/local/bin/` doesn't exist on OpenWrt — use `/usr/bin/`
- **Issue:** Hub config not auto-applied after enrollment — fixed enrollment endpoint
- Successfully connected, GRETAP bridged, multicast verified with socat

### Burke (GL.iNet SFT1200)
- Enrolled, connected
- Multicast relay installed (socat not pre-installed — had to install)

### 2500marcus (GL.iNet SFT1200)
- Enrolled, connected
- Space in name caused URL issues — learned to avoid spaces

## Phase 5: GRETAP TX Bug Discovery

### Problem
- GL.iNet SFT1200 runs kernel 4.14.90 (SiFlower MT7628)
- GRETAP **RX works** (hub → site)
- GRETAP **TX broken** — 1M+ TX errors/overruns, zero packets reach hub
- No VXLAN support either on this kernel

### Solution: Multicast Relay
- **Site side:** socat captures mDNS (224.0.0.251:5353) on br-lan, forwards as unicast UDP to hub:5350
- **Hub side:** Python relay receives unicast, re-broadcasts as multicast on br-mcast
- **Site-to-site:** Hub relay forwards incoming packets to all other sites (critical fix added later)
- Installed as init scripts on routers, systemd service on hub

## Phase 6: APX Radio Testing

### Radio Discovery
- APX 8000 (serial 581CWB0147) connected to Burke's "CEMS_RM" WiFi
- MAC: `4c:cc:34:9f:c9:a0` (Motorola Solutions OUI confirmed)
- Got DHCP lease on Burke's LAN

### WiFi Contention Issue
- Burke's GL.iNet was in WiFi repeater mode — AP and client on same radio/channel
- 900ms+ latency, 66% packet loss to radio
- **Fix:** Plugged Burke's WAN into ethernet, freed WiFi for radio-only AP

### Subnet Discovery
- APX OTAP **requires /24 subnet mask** — won't announce on /16
- Tested: changed all sites to `10.3.0.0/16` → radio went completely silent
- Reverted to `192.168.8.0/24` → radio immediately announced `_otap._tcp.local.`

### OTAP Announcement Captured
```
PTR APX 8000_581CWB0147._otap._tcp.local.
SRV APX 8000_581CWB0147.local.:52010
TXT "txtvers=1" "mn=APX 8000" "sn=581CWB0147" "key=0" "tlsPsk=true"
```

### Relay Chain Issues
1. **socat vs avahi conflict** on port 5353 — both listening, avahi won. Fixed with `so-bindtodevice=br-lan`
2. **Hub relay didn't forward site-to-site** — only re-broadcast on br-mcast. Fixed: added unicast forwarding to all other sites
3. **GRETAP dropped from bridge** after network restart — had to re-add `ip link set gretap0 master br-lan`
4. **DHCP lease caching** — radio reuses cached lease, skips OTAP announcement. Only fires on fresh DHCP Discover

### Current Status
- Full relay chain proven: Burke → hub → 2500marcus (RM's OTAP query arrives at Burke, radio's announcement forwarded to 2500marcus)
- RM Device Programmer not yet seeing radio — timing issue with relay latency
- **Next step:** Move RM computer to hub network for direct GRETAP delivery (sub-ms latency)

## Network Configuration (Final State)

### All sites on `192.168.8.0/24`
| Site | Router IP | DHCP Range | Lease | Tunnel IP |
|---|---|---|---|---|
| Hub (br-mcast) | 192.168.8.254 | — | — | 172.27.0.1 |
| 2500marcus | 192.168.8.1 | .10-.24 | 4h | 172.27.3.1 |
| HempsteadArmory | 192.168.8.2 | .30-.44 | 4h | 172.27.2.1 |
| Burke | 192.168.8.1 | .50-.64 | 4h | 172.27.1.1 |

### Hub Services
| Service | Status | Unit |
|---|---|---|
| WireGuard | active | `wg-quick@wg0` |
| GRETAP Bridge | active | `wg-mcast-bridge` |
| Multicast Relay | active | `outpost-conduit-relay` |
| Web UI | active | `outpost-conduit-web` |
| Cloudflare Tunnel | active | `cloudflared` |

### Router SSH Access (from hub)
```bash
# Burke
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -i ~/.ssh/id_rsa root@172.27.1.1

# HempsteadArmory
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -i ~/.ssh/id_rsa root@172.27.2.1

# 2500marcus
ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -i ~/.ssh/id_rsa root@172.27.3.1
```

### UniFi Router Static Routes Needed
- `192.168.8.0/24` → `10.0.0.36` (for VNC/access to remote sites)
- `10.3.0.0/16` → `10.0.0.36` (legacy, may be removed)

## Key Learnings

1. **GL.iNet SFT1200 kernel 4.14 has broken GRETAP TX** — must use socat multicast relay
2. **APX radios require /24 subnet for OTAP** — won't work on /16 or other masks
3. **APX OTAP announces once on fresh DHCP** — cached leases skip announcement
4. **WiFi repeater mode causes massive latency** — use ethernet WAN when possible
5. **OpenWrt uses `/usr/bin/` not `/usr/local/bin/`**
6. **Dropbear (OpenWrt SSH) only supports RSA keys** — not ed25519
7. **WireGuard AllowedIPs can't overlap** between peers — use L2 bridging for shared subnets
8. **mDNS is link-local (TTL=1)** — requires same L2 broadcast domain
9. **socat and avahi-daemon conflict** on port 5353 — use `so-bindtodevice` to fix
10. **Hub relay must forward site-to-site** — not just bridge re-broadcast

## TODO (Next Session)
- [ ] Move RM computer to hub network (direct GRETAP, no relay latency)
- [ ] Test OTAP discovery with RM on br-mcast
- [ ] Program a radio remotely via OTAP
- [ ] Make GRETAP re-add to bridge persistent across network restarts
- [ ] Update glinet-setup.sh to handle DHCP range for /24 with proper offsets
- [ ] Add more SFT1200 routers for ambulance testing
- [ ] Test Cradlepoint + Pi sidecar deployment
- [ ] Configure SMTP alerts
- [ ] Stress test with multiple radios
