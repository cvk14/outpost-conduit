# Outpost Conduit Web UI — Design Spec

## Problem

Managing 20+ WireGuard/GRETAP sites requires SSH access to the hub VM and manual command-line operations. There is no visibility into site health, traffic, or bridge status without running shell commands. Deploying configs to remote GL.iNet and Raspberry Pi devices requires manual SCP and SSH.

## Solution

A web-based management UI running on the hub VM that provides:
1. **Dashboard** — real-time health display with site status, bridge state, and summary metrics
2. **Traffic Monitor** — per-peer WireGuard transfer stats and per-port bridge counters
3. **Config Management** — CRUD for sites, config generation, and downloadable config bundles
4. **Remote Management** — SSH-based deploy, restart, status check, and reboot for GL.iNet and Pi devices

## Tech Stack

- **Backend:** Python 3.12 + FastAPI (async), uvicorn, asyncssh, bcrypt, PyJWT
- **Frontend:** Vanilla JS SPA, dark theme, no build step
- **Auth:** Single admin user, bcrypt-hashed password in `.env`, JWT tokens
- **Data:** `sites.yaml` as source of truth (no database), live stats from shell commands
- **Deployment:** systemd service on the hub VM, port 8080

## Architecture

### Data Sources

All data comes from local shell commands on the hub VM — no external APIs:

| Source | Command | Data | Poll Interval |
|---|---|---|---|
| WireGuard peers | `wg show wg0 dump` | Peer pubkey, endpoint, last handshake, TX/RX bytes | 5s |
| Bridge ports | `bridge -s link show br-mcast` | Per-port state, packet/byte counters | 5s |
| Interface stats | `ip -s link show <iface>` | Errors, drops | 5s |
| Site inventory | `sites.yaml` (file read) | Name, type, tunnel IP, WAN IP, SSH config | On demand |

### API Endpoints

**Auth:**
- `POST /api/auth/login` — username + password → JWT token
- All other endpoints require `Authorization: Bearer <token>` header

**Status (read-only):**
- `GET /api/status` — full hub status: WireGuard peers + bridge ports merged with site inventory
- `WS /api/ws/stats` — WebSocket streaming live stats every 5s (requires token as query param)

**Site management (CRUD):**
- `GET /api/sites` — list all sites
- `POST /api/sites` — add a new site
- `PUT /api/sites/{name}` — update a site
- `DELETE /api/sites/{name}` — remove a site

**Config operations:**
- `POST /api/sites/{name}/generate` — generate configs for a site (calls generate_configs.py)
- `GET /api/sites/{name}/download` — download site config bundle as zip
- `POST /api/hub/regenerate` — regenerate all configs + restart hub WireGuard and bridge services

**Remote management (SSH):**
- `POST /api/sites/{name}/deploy` — SCP configs + run setup script on remote device
- `POST /api/sites/{name}/restart` — restart WireGuard + GRETAP on remote device
- `POST /api/sites/{name}/status` — check WireGuard/GRETAP/bridge status on remote device
- `POST /api/sites/{name}/reboot` — reboot remote device
- `WS /api/ws/ssh/{name}` — WebSocket streaming SSH command output in real-time

### Stats Collector

A background async task that runs every 5 seconds:

1. Runs `wg show wg0 dump` — parses peer public keys, endpoints, last handshake timestamps, TX/RX bytes
2. Runs `bridge -s link show br-mcast` — parses per-port state and traffic counters
3. Merges with site inventory (matches peers to sites by tunnel IP → public key mapping)
4. Broadcasts merged state to all connected WebSocket clients

The collector is a singleton — one polling loop regardless of how many clients are connected.

### SSH Manager

Uses `asyncssh` for non-blocking SSH connections through the WireGuard tunnel.

**Per-site SSH config** (optional section in `sites.yaml`):
```yaml
sites:
  - name: "site-01-north"
    type: "glinet"
    tunnel_ip: "172.27.1.1"
    wan_ip: "198.51.100.1"
    description: "North district station"
    ssh:
      host: "172.27.1.1"
      user: "root"
      key: "~/.ssh/id_ed25519"
```

- `host` defaults to `tunnel_ip` if omitted
- `user` defaults to `root` for glinet, `pi` for cradlepoint
- `key` defaults to `~/.ssh/id_ed25519`

**Commands by site type:**

| Action | GL.iNet (OpenWrt) | Raspberry Pi |
|---|---|---|
| Status | `wg show; ip link show gretap0; bridge link` | `wg show; ip link show gretap0; bridge link show br0` |
| Restart | `/etc/init.d/wg-mcast-gretap restart` | `systemctl restart wg-quick@wg0 wg-mcast-gretap` |
| Deploy | SCP config dir + `./glinet-setup.sh <dir>` | SCP config dir + `sudo ./pi-setup.sh <dir>` |
| Reboot | `reboot` | `sudo reboot` |

**Safety:**
- Deploy and reboot require confirmation in the UI
- All SSH commands run with a 30-second timeout
- SSH output is streamed to the frontend via WebSocket in real-time

### Authentication

- Single admin user defined in `.env` file
- `ADMIN_USER` and `ADMIN_PASSWORD_HASH` (bcrypt)
- Login returns a JWT token (HS256, 24h expiry)
- JWT secret from `JWT_SECRET` in `.env`
- All API endpoints except `/api/auth/login` require valid JWT
- WebSocket auth via `?token=<jwt>` query parameter

## Frontend

### Structure

Single-page app with client-side routing. No framework, no build step.

```
web/
  static/
    css/style.css          # Dark theme from mockup
    js/app.js              # Router, auth manager, WebSocket manager
    js/dashboard.js        # Dashboard view (summary + sites table + bridge)
    js/sites.js            # Sites CRUD (add/edit/delete forms)
    js/traffic.js          # Traffic monitor (per-peer + per-port stats)
    js/deploy.js           # Deploy/remote management (action selector + live log)
  templates/
    index.html             # App shell (nav + content container)
    login.html             # Login form
```

### Views

**Dashboard:**
- 4 summary cards: total sites, online, stale, offline
- Sites table with columns: name, type badge, status badge, tunnel IP, endpoint, TX/RX, last seen, action buttons
- Bridge status panel: per-port name, state, TX/RX/errors
- All data updates live via WebSocket (no manual refresh)

**Sites:**
- Table of all sites with edit/delete buttons
- "Add Site" form: name, type (dropdown), tunnel IP (auto-suggested next available), WAN IP, description, SSH host/user/key
- Edit form: same fields, pre-populated
- Delete with confirmation modal
- After add/edit/delete: regenerates configs in the background (does NOT restart hub services — user must explicitly click "Apply to Hub" to restart WireGuard + bridge)

**Traffic:**
- Per-site bandwidth bars showing TX/RX bytes (live-updating)
- Per-bridge-port stats table with packet/byte counters and error counts
- Data from the same WebSocket stream as dashboard

**Deploy:**
- Site selector (checkboxes for bulk operations)
- Action dropdown: Push Config, Run Setup, Restart WireGuard, Reboot
- "Execute" button with confirmation for destructive actions
- Live output log panel showing SSH command output streamed via WebSocket (`/api/ws/ssh/{name}`)
- Bulk operations run sequentially (one site at a time)

**Deploy actions explained:**
- **Push Config:** SCP the generated output files (`wg0.conf`, `setup-gretap.sh`) to the remote device's config directory. Does NOT re-run the full initial setup script.
- **Run Setup:** Re-runs the full setup script (`glinet-setup.sh` or `pi-setup.sh`). Only needed for first-time setup or major reconfiguration. Confirmation required.
- **Restart WireGuard:** Restarts WireGuard + GRETAP services on the remote device.
- **Reboot:** Reboots the remote device. Confirmation required.

### Design

- Dark theme (colors from mockup: `#0f1117` background, `#1a1d28` cards, `#2563eb` primary blue)
- Status badges: green (online), yellow (stale), red (offline)
- Type badges: blue (glinet), purple (cradlepoint)
- Monospace font for IPs, stats, and terminal output
- Responsive but desktop-first (not mobile-optimized)

## Deployment

### Systemd Service

```ini
[Unit]
Description=Outpost Conduit Web UI
After=wg-quick@wg0.service wg-mcast-bridge.service

[Service]
WorkingDirectory=/home/chris/outpost-conduit
ExecStart=/home/chris/outpost-conduit/venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8080
Restart=always
EnvironmentFile=/home/chris/outpost-conduit/.env

[Install]
WantedBy=multi-user.target
```

### Environment File (`.env`)

```
ADMIN_USER=admin
ADMIN_PASSWORD_HASH=<bcrypt hash>
JWT_SECRET=<generated 32-byte hex>
```

### Setup Script (`scripts/web-setup.sh`)

1. Creates Python venv at `./venv/`
2. Installs: `fastapi`, `uvicorn[standard]`, `asyncssh`, `bcrypt`, `pyjwt`, `pyyaml`
3. Prompts for admin password, bcrypt-hashes it, writes `.env`
4. Installs systemd service file
5. Enables and starts the service
6. Prints the access URL

### Access

- `http://<hub-ip>:8080` from the local network
- No HTTPS (add via nginx reverse proxy later if needed)

## File Changes to Existing Code

### `scripts/generate_configs.py`

The web backend imports and calls `generate_all()`, `load_inventory()`, `validate_inventory()` directly. These are synchronous functions (file I/O + `subprocess.run()` for `wg genkey`), so the backend wraps them with `asyncio.to_thread()` to avoid blocking the event loop. No refactoring of the existing module is needed.

The web server's `PYTHONPATH` must include the project root so `from scripts.generate_configs import generate_all` works. The systemd unit sets `WorkingDirectory` to the project root; the backend adds it to `sys.path` at startup.

### `sites.yaml` Write Strategy

The web backend owns all writes to `sites.yaml`. To prevent corruption:
- **Atomic writes:** Write to a temp file in the same directory, then `os.replace()` to atomically swap.
- **File lock:** Use `fcntl.flock()` to serialize writes. The stats collector reads the file without locking (reads are safe against atomic replace).
- **Validation:** `validate_inventory()` runs on the new state before writing. If validation fails, the write is rejected and the API returns an error.

### `sites.yaml` Schema

Add optional `ssh` section to each site. Backward-compatible — existing sites without `ssh` work fine (defaults are used).

## Dependencies (All Open Source)

| Component | License | Purpose |
|---|---|---|
| FastAPI | MIT | Web framework |
| uvicorn | BSD | ASGI server |
| asyncssh | EPL-2.0 | Async SSH client |
| bcrypt | Apache-2.0 | Password hashing |
| PyJWT | MIT | JWT token generation/validation |
| PyYAML | MIT | Already used by config generator |

## Deliverables

1. **Backend** — `web/app.py`, `web/auth.py`, `web/stats.py`, `web/ssh_manager.py`, `web/routes/status.py`, `web/routes/sites.py`, `web/routes/deploy.py`
2. **Frontend** — `web/static/css/style.css`, `web/static/js/app.js`, `web/static/js/dashboard.js`, `web/static/js/sites.js`, `web/static/js/traffic.js`, `web/static/js/deploy.js`, `web/templates/index.html`, `web/templates/login.html`
3. **Setup script** — `scripts/web-setup.sh`
4. **Tests** — `tests/test_stats.py`, `tests/test_auth.py`, `tests/test_routes.py`

## Out of Scope

- HTTPS/TLS (add via reverse proxy)
- Multi-user / role-based access control
- Historical traffic data / time-series database
- Mobile-optimized responsive layout
- WebSocket-based interactive SSH terminal (just command output streaming)
