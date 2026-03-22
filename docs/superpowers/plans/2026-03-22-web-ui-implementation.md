# Outpost Conduit Web UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web-based management UI for Outpost Conduit that provides real-time health monitoring, traffic stats, site CRUD with config generation/download, and SSH-based remote management of GL.iNet and Raspberry Pi devices.

**Architecture:** FastAPI backend on the hub VM serves a vanilla JS SPA. A background stats collector polls WireGuard and bridge state every 5s and broadcasts to WebSocket clients. Site inventory lives in `sites.yaml` with atomic write-back. Remote management uses asyncssh through WireGuard tunnels.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, asyncssh, bcrypt, PyJWT, vanilla JS (no build step)

**Spec:** `docs/superpowers/specs/2026-03-22-web-ui-design.md`

---

## File Structure

```
web/
  __init__.py                    # Package init, adds project root to sys.path
  app.py                         # FastAPI app, lifespan, static file mounts
  auth.py                        # JWT + bcrypt auth (login, token verify, dependency)
  stats.py                       # Stats collector (wg show + bridge parsing, WebSocket broadcast)
  inventory.py                   # sites.yaml read/write with atomic writes + flock
  ssh_manager.py                 # asyncssh wrapper for remote commands
  routes/
    __init__.py
    auth_routes.py               # POST /api/auth/login
    status_routes.py             # GET /api/status, WS /api/ws/stats
    sites_routes.py              # CRUD /api/sites, generate, download, hub regenerate
    deploy_routes.py             # SSH actions: push, setup, restart, status, reboot, WS ssh
  static/
    css/style.css                # Dark theme
    js/app.js                    # Router, auth, WebSocket manager
    js/dashboard.js              # Dashboard view
    js/sites.js                  # Sites CRUD view
    js/traffic.js                # Traffic monitor view
    js/deploy.js                 # Deploy/remote management view
  templates/
    index.html                   # App shell
    login.html                   # Login page
scripts/
  web-setup.sh                   # Provisions venv, deps, .env, systemd service
tests/
  test_auth.py                   # Auth tests
  test_stats.py                  # Stats parser tests
  test_inventory.py              # (existing — may need updates for ssh field)
  test_routes.py                 # API route integration tests
```

---

### Task 1: Backend App Shell + Auth

**Files:**
- Create: `web/__init__.py`
- Create: `web/app.py`
- Create: `web/auth.py`
- Create: `web/routes/__init__.py`
- Create: `web/routes/auth_routes.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write auth tests**

Create `tests/test_auth.py`:

```python
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from web.auth import hash_password, verify_password, create_token, decode_token


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("testpass123")
        assert verify_password("testpass123", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("testpass123")
        assert not verify_password("wrongpass", hashed)

    def test_hash_is_bcrypt_format(self):
        hashed = hash_password("test")
        assert hashed.startswith("$2b$")


class TestJWT:
    def test_create_and_decode(self):
        token = create_token("admin", secret="testsecret")
        payload = decode_token(token, secret="testsecret")
        assert payload["sub"] == "admin"

    def test_expired_token_raises(self):
        import jwt as pyjwt

        token = create_token("admin", secret="testsecret", expire_hours=-1)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(token, secret="testsecret")

    def test_invalid_token_raises(self):
        import jwt as pyjwt

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_token("garbage.token.here", secret="testsecret")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_auth.py -v`
Expected: ImportError — `web.auth` not found

- [ ] **Step 3: Install backend dependencies in venv**

```bash
source .venv/bin/activate
pip install fastapi "uvicorn[standard]" asyncssh bcrypt pyjwt
```

- [ ] **Step 4: Create web package init**

Create `web/__init__.py`:

```python
"""Outpost Conduit Web UI."""
import os
import sys

# Ensure project root is on sys.path so we can import scripts.generate_configs
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
```

- [ ] **Step 5: Implement auth module**

Create `web/auth.py`:

```python
"""Authentication: bcrypt password hashing + JWT tokens."""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(
    username: str, secret: str, expire_hours: int = 24
) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
```

- [ ] **Step 6: Run auth tests — all should pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_auth.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Create auth routes**

Create `web/routes/__init__.py` (empty) and `web/routes/auth_routes.py`:

```python
"""Auth API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.auth import verify_password, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    from web.app import get_settings

    settings = get_settings()
    if req.username != settings["admin_user"]:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(req.password, settings["admin_password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(req.username, settings["jwt_secret"])
    return LoginResponse(token=token)
```

- [ ] **Step 8: Create FastAPI app**

Create `web/app.py`:

```python
"""Outpost Conduit Web UI — FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from web.auth import decode_token
from web.routes.auth_routes import router as auth_router

_settings: dict = {}


def get_settings() -> dict:
    return _settings


def require_auth(request: Request) -> dict:
    """FastAPI dependency: extract and verify JWT from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = auth[7:]
    try:
        return decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        raise HTTPException(401, "Invalid token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load settings from environment on startup."""
    _settings.update({
        "admin_user": os.environ.get("ADMIN_USER", "admin"),
        "admin_password_hash": os.environ.get("ADMIN_PASSWORD_HASH", ""),
        "jwt_secret": os.environ.get("JWT_SECRET", "dev-secret-change-me"),
        "inventory_path": os.environ.get("INVENTORY_PATH", "sites.yaml"),
        "output_dir": os.environ.get("OUTPUT_DIR", "output"),
    })
    yield


app = FastAPI(title="Outpost Conduit", lifespan=lifespan)
app.include_router(auth_router)

# Static files
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "templates", "index.html"))


@app.get("/login")
async def login_page():
    return FileResponse(os.path.join(WEB_DIR, "templates", "login.html"))
```

- [ ] **Step 9: Commit**

```bash
git add web/ tests/test_auth.py
git commit -m "feat(web): add FastAPI app shell with JWT + bcrypt auth"
```

---

### Task 2: Stats Collector (WireGuard + Bridge Parsing)

**Files:**
- Create: `web/stats.py`
- Create: `tests/test_stats.py`

- [ ] **Step 1: Write stats parser tests**

Create `tests/test_stats.py`:

```python
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from web.stats import parse_wg_dump, parse_bridge_stats, merge_stats


# Real output format from `wg show wg0 dump`
WG_DUMP = """wg0\tPRIVKEY=\t51820\toff
BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI=\tPSK=\t198.51.100.1:51820\t172.27.1.1/32\t1711900000\t142300000\t89700000\t25"""

# Real output format from `bridge -s link show br-mcast`
BRIDGE_STATS = """3: ens19: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br-mcast state forwarding priority 32 cost 100
    RX:  bytes packets errors
    890000000 1200000 0
    TX:  bytes packets errors
    1200000000 1500000 0
9: gretap-test-sit@NONE: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1380 master br-mcast state forwarding priority 32 cost 100
    RX:  bytes packets errors
    89700000 120000 0
    TX:  bytes packets errors
    142300000 150000 0"""

SITE_INVENTORY = [
    {
        "name": "test-site-01",
        "type": "glinet",
        "tunnel_ip": "172.27.1.1",
        "wan_ip": "198.51.100.1",
        "public_key": "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI=",
    }
]


class TestParseWgDump:
    def test_parses_peer(self):
        peers = parse_wg_dump(WG_DUMP)
        assert len(peers) == 1
        p = peers[0]
        assert p["public_key"] == "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI="
        assert p["endpoint"] == "198.51.100.1:51820"
        assert p["allowed_ips"] == "172.27.1.1/32"
        assert p["tx_bytes"] == 142300000
        assert p["rx_bytes"] == 89700000
        assert p["last_handshake"] == 1711900000

    def test_empty_dump(self):
        peers = parse_wg_dump("")
        assert peers == []

    def test_skips_interface_line(self):
        # First line is the interface, not a peer
        peers = parse_wg_dump(WG_DUMP)
        for p in peers:
            assert "public_key" in p


class TestParseBridgeStats:
    def test_parses_ports(self):
        ports = parse_bridge_stats(BRIDGE_STATS)
        assert len(ports) == 2
        ens19 = next(p for p in ports if p["name"] == "ens19")
        assert ens19["state"] == "forwarding"
        assert ens19["rx_bytes"] == 890000000
        assert ens19["tx_bytes"] == 1200000000

    def test_parses_gretap_port(self):
        ports = parse_bridge_stats(BRIDGE_STATS)
        gretap = next(p for p in ports if "gretap" in p["name"])
        assert gretap["rx_bytes"] == 89700000
        assert gretap["tx_packets"] == 150000


class TestMergeStats:
    def test_merges_peer_with_site(self):
        peers = parse_wg_dump(WG_DUMP)
        ports = parse_bridge_stats(BRIDGE_STATS)
        merged = merge_stats(SITE_INVENTORY, peers, ports)

        assert len(merged["sites"]) == 1
        site = merged["sites"][0]
        assert site["name"] == "test-site-01"
        assert site["status"] in ("online", "stale", "offline")
        assert site["tx_bytes"] == 142300000

    def test_includes_bridge_ports(self):
        peers = parse_wg_dump(WG_DUMP)
        ports = parse_bridge_stats(BRIDGE_STATS)
        merged = merge_stats(SITE_INVENTORY, peers, ports)
        assert len(merged["bridge_ports"]) == 2

    def test_includes_summary(self):
        peers = parse_wg_dump(WG_DUMP)
        ports = parse_bridge_stats(BRIDGE_STATS)
        merged = merge_stats(SITE_INVENTORY, peers, ports)
        assert "total" in merged["summary"]
        assert "online" in merged["summary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_stats.py -v`
Expected: ImportError

- [ ] **Step 3: Implement stats parsers**

Create `web/stats.py`:

```python
"""Stats collector: parses WireGuard and bridge output, merges with inventory."""

import asyncio
import json
import re
import time
from typing import Any


def parse_wg_dump(output: str) -> list[dict]:
    """Parse `wg show wg0 dump` output into list of peer dicts."""
    peers = []
    for line in output.strip().splitlines():
        fields = line.split("\t")
        # Interface line has 4 fields, peer lines have 9
        if len(fields) < 8:
            continue
        peers.append({
            "public_key": fields[0],
            "endpoint": fields[2] if fields[2] != "(none)" else None,
            "allowed_ips": fields[3],
            "last_handshake": int(fields[4]),
            "tx_bytes": int(fields[5]),
            "rx_bytes": int(fields[6]),
            "keepalive": int(fields[7]) if fields[7] != "off" else 0,
        })
    return peers


def parse_bridge_stats(output: str) -> list[dict]:
    """Parse `bridge -s link show br-mcast` output into port stats."""
    ports = []
    lines = output.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Port header line: "N: name: <flags> ... master br-mcast state STATE ..."
        match = re.match(r"^\d+:\s+(\S+?)(?:@\S+)?:\s+.*state\s+(\w+)", line)
        if match:
            port = {
                "name": match.group(1),
                "state": match.group(2),
                "rx_bytes": 0, "rx_packets": 0, "rx_errors": 0,
                "tx_bytes": 0, "tx_packets": 0, "tx_errors": 0,
            }
            # Next lines: RX header, RX values, TX header, TX values
            if i + 2 < len(lines) and "RX:" in lines[i + 1]:
                rx_vals = lines[i + 2].split()
                if len(rx_vals) >= 3:
                    port["rx_bytes"] = int(rx_vals[0])
                    port["rx_packets"] = int(rx_vals[1])
                    port["rx_errors"] = int(rx_vals[2])
            if i + 4 < len(lines) and "TX:" in lines[i + 3]:
                tx_vals = lines[i + 4].split()
                if len(tx_vals) >= 3:
                    port["tx_bytes"] = int(tx_vals[0])
                    port["tx_packets"] = int(tx_vals[1])
                    port["tx_errors"] = int(tx_vals[2])
            ports.append(port)
            i += 5
            continue
        i += 1
    return ports


def merge_stats(
    sites: list[dict], peers: list[dict], bridge_ports: list[dict]
) -> dict[str, Any]:
    """Merge site inventory with live WireGuard and bridge data."""
    now = int(time.time())

    # Index peers by public_key
    peer_map = {p["public_key"]: p for p in peers}

    merged_sites = []
    online = stale = offline = 0

    for site in sites:
        pub_key = site.get("public_key", "")
        peer = peer_map.get(pub_key)

        entry = {
            "name": site["name"],
            "type": site["type"],
            "tunnel_ip": site["tunnel_ip"],
            "wan_ip": site.get("wan_ip", ""),
            "description": site.get("description", ""),
        }

        if peer:
            age = now - peer["last_handshake"] if peer["last_handshake"] > 0 else None
            if age is None:
                status = "offline"
                offline += 1
            elif age <= 300:
                status = "online"
                online += 1
            else:
                status = "stale"
                stale += 1

            entry.update({
                "status": status,
                "endpoint": peer["endpoint"],
                "tx_bytes": peer["tx_bytes"],
                "rx_bytes": peer["rx_bytes"],
                "last_handshake": peer["last_handshake"],
                "last_handshake_age": age,
            })
        else:
            entry.update({
                "status": "offline",
                "endpoint": None,
                "tx_bytes": 0,
                "rx_bytes": 0,
                "last_handshake": 0,
                "last_handshake_age": None,
            })
            offline += 1

        merged_sites.append(entry)

    return {
        "summary": {
            "total": len(sites),
            "online": online,
            "stale": stale,
            "offline": offline,
        },
        "sites": merged_sites,
        "bridge_ports": bridge_ports,
        "timestamp": now,
    }


class StatsCollector:
    """Background task that polls WireGuard + bridge and broadcasts to WebSocket clients."""

    def __init__(self, inventory_loader):
        self.inventory_loader = inventory_loader
        self.clients: set = set()
        self.latest: dict = {}
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _run_cmd(self, cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()

    async def _poll_loop(self):
        while True:
            try:
                wg_out = await self._run_cmd("wg show wg0 dump")
                br_out = await self._run_cmd("bridge -s link show br-mcast")

                peers = parse_wg_dump(wg_out)
                ports = parse_bridge_stats(br_out)

                inv = self.inventory_loader()
                # Attach public keys to inventory sites
                sites_with_keys = self._attach_keys(inv.get("sites", []))

                self.latest = merge_stats(sites_with_keys, peers, ports)

                # Broadcast to connected WebSocket clients
                msg = json.dumps(self.latest)
                dead = set()
                for ws in self.clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                self.clients -= dead

            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Don't crash the poll loop

            await asyncio.sleep(5)

    def _attach_keys(self, sites: list[dict]) -> list[dict]:
        """Read public keys from output directory and attach to site dicts."""
        import os
        output_dir = os.environ.get("OUTPUT_DIR", "output")
        result = []
        for site in sites:
            pub_path = os.path.join(output_dir, site["name"], "keys", "publickey")
            pub_key = ""
            if os.path.isfile(pub_path):
                with open(pub_path) as f:
                    pub_key = f.read().strip()
            result.append({**site, "public_key": pub_key})
        return result
```

- [ ] **Step 4: Run stats tests — all should pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_stats.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/stats.py tests/test_stats.py
git commit -m "feat(web): add stats collector with WireGuard + bridge parsers"
```

---

### Task 3: Inventory Manager (Atomic YAML Read/Write)

**Files:**
- Create: `web/inventory.py`
- Create: `tests/test_inventory_web.py`

- [ ] **Step 1: Write inventory manager tests**

Create `tests/test_inventory_web.py`:

```python
import os
import sys
import yaml
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from web.inventory import InventoryManager


@pytest.fixture
def inv_manager(tmp_path):
    inv_file = tmp_path / "sites.yaml"
    inv_file.write_text(yaml.dump({
        "hub": {"wan_ip": "1.2.3.4", "tunnel_ip": "172.27.0.1", "listen_port": 51820},
        "sites": [
            {"name": "site-01", "type": "glinet", "tunnel_ip": "172.27.1.1", "wan_ip": "dynamic"},
        ],
    }))
    return InventoryManager(str(inv_file))


class TestRead:
    def test_loads_inventory(self, inv_manager):
        inv = inv_manager.load()
        assert inv["hub"]["tunnel_ip"] == "172.27.0.1"
        assert len(inv["sites"]) == 1

    def test_get_sites(self, inv_manager):
        sites = inv_manager.get_sites()
        assert sites[0]["name"] == "site-01"

    def test_get_site_by_name(self, inv_manager):
        site = inv_manager.get_site("site-01")
        assert site["type"] == "glinet"

    def test_get_missing_site_returns_none(self, inv_manager):
        assert inv_manager.get_site("nonexistent") is None


class TestWrite:
    def test_add_site(self, inv_manager):
        inv_manager.add_site({
            "name": "site-02", "type": "cradlepoint",
            "tunnel_ip": "172.27.2.1", "wan_ip": "dynamic",
        })
        sites = inv_manager.get_sites()
        assert len(sites) == 2
        assert sites[1]["name"] == "site-02"

    def test_add_duplicate_raises(self, inv_manager):
        with pytest.raises(ValueError, match="exists"):
            inv_manager.add_site({
                "name": "site-01", "type": "glinet",
                "tunnel_ip": "172.27.3.1", "wan_ip": "dynamic",
            })

    def test_update_site(self, inv_manager):
        inv_manager.update_site("site-01", {"wan_ip": "5.6.7.8"})
        site = inv_manager.get_site("site-01")
        assert site["wan_ip"] == "5.6.7.8"

    def test_update_nonexistent_raises(self, inv_manager):
        with pytest.raises(ValueError, match="not found"):
            inv_manager.update_site("nope", {"wan_ip": "1.1.1.1"})

    def test_delete_site(self, inv_manager):
        inv_manager.delete_site("site-01")
        assert inv_manager.get_sites() == []

    def test_delete_nonexistent_raises(self, inv_manager):
        with pytest.raises(ValueError, match="not found"):
            inv_manager.delete_site("nope")

    def test_atomic_write(self, inv_manager):
        """File should be updated on disk after add."""
        inv_manager.add_site({
            "name": "site-99", "type": "glinet",
            "tunnel_ip": "172.27.99.1", "wan_ip": "dynamic",
        })
        # Read file directly (bypass cache)
        with open(inv_manager.path) as f:
            raw = yaml.safe_load(f)
        assert any(s["name"] == "site-99" for s in raw["sites"])

    def test_next_tunnel_ip(self, inv_manager):
        ip = inv_manager.next_tunnel_ip()
        assert ip == "172.27.2.1"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement inventory manager**

Create `web/inventory.py`:

```python
"""Inventory manager: atomic read/write for sites.yaml."""

import fcntl
import os
import tempfile

import yaml

from scripts.generate_configs import validate_inventory


class InventoryManager:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        with open(self.path) as f:
            return yaml.safe_load(f)

    def _save(self, inv: dict) -> None:
        validate_inventory(inv)
        dir_name = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                yaml.dump(inv, f, default_flow_style=False, sort_keys=False)
                fcntl.flock(f, fcntl.LOCK_UN)
            os.replace(tmp_path, self.path)
        except Exception:
            os.unlink(tmp_path)
            raise

    def get_sites(self) -> list[dict]:
        return self.load().get("sites", [])

    def get_site(self, name: str) -> dict | None:
        for s in self.get_sites():
            if s["name"] == name:
                return s
        return None

    def add_site(self, site: dict) -> None:
        inv = self.load()
        if any(s["name"] == site["name"] for s in inv["sites"]):
            raise ValueError(f"Site '{site['name']}' already exists")
        inv["sites"].append(site)
        self._save(inv)

    def update_site(self, name: str, updates: dict) -> None:
        inv = self.load()
        for s in inv["sites"]:
            if s["name"] == name:
                s.update(updates)
                self._save(inv)
                return
        raise ValueError(f"Site '{name}' not found")

    def delete_site(self, name: str) -> None:
        inv = self.load()
        before = len(inv["sites"])
        inv["sites"] = [s for s in inv["sites"] if s["name"] != name]
        if len(inv["sites"]) == before:
            raise ValueError(f"Site '{name}' not found")
        self._save(inv)

    def next_tunnel_ip(self) -> str:
        sites = self.get_sites()
        used = set()
        for s in sites:
            parts = s["tunnel_ip"].split(".")
            used.add(int(parts[2]))
        octet = 1
        while octet in used:
            octet += 1
        return f"172.27.{octet}.1"
```

- [ ] **Step 4: Run tests — all should pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_inventory_web.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/inventory.py tests/test_inventory_web.py
git commit -m "feat(web): add inventory manager with atomic YAML read/write"
```

---

### Task 4: Status + Stats WebSocket Routes

**Files:**
- Create: `web/routes/status_routes.py`
- Modify: `web/app.py` (add status router, start stats collector in lifespan)

- [ ] **Step 1: Create status routes**

Create `web/routes/status_routes.py`:

```python
"""Status API routes: GET /api/status, WS /api/ws/stats."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query

from web.app import require_auth
from web.auth import decode_token

router = APIRouter(tags=["status"], dependencies=[Depends(require_auth)])


@router.get("/api/status")
async def get_status():
    from web.app import get_collector
    return get_collector().latest


@router.websocket("/api/ws/stats")
async def ws_stats(ws: WebSocket, token: str = Query(...)):
    from web.app import get_settings, get_collector

    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        return

    collector = get_collector()
    await ws.accept()
    collector.clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # Keep alive
    except WebSocketDisconnect:
        collector.clients.discard(ws)
```

- [ ] **Step 2: Update app.py — add status router, inventory manager, stats collector to lifespan**

Add to `web/app.py` imports and lifespan:

```python
# Add imports
from web.inventory import InventoryManager
from web.stats import StatsCollector
from web.routes.status_routes import router as status_router

# Module-level singletons
_inventory: InventoryManager | None = None
_collector: StatsCollector | None = None

def get_inventory() -> InventoryManager:
    return _inventory

def get_collector() -> StatsCollector:
    return _collector

# In lifespan, after settings update:
    global _inventory, _collector
    _inventory = InventoryManager(_settings["inventory_path"])
    _collector = StatsCollector(lambda: _inventory.load())
    await _collector.start()
    yield
    await _collector.stop()

# Register router
app.include_router(status_router)
```

- [ ] **Step 3: Verify the app starts**

```bash
source .venv/bin/activate
ADMIN_USER=admin ADMIN_PASSWORD_HASH='$2b$12$test' JWT_SECRET=devsecret \
  timeout 3 python -m uvicorn web.app:app --port 8080 || true
```

Expected: App starts, then timeout kills it. No crash.

- [ ] **Step 4: Commit**

```bash
git add web/routes/status_routes.py web/app.py
git commit -m "feat(web): add status API and stats WebSocket endpoint"
```

---

### Task 5: Sites CRUD + Config Routes

**Files:**
- Create: `web/routes/sites_routes.py`
- Modify: `web/app.py` (register router)

- [ ] **Step 1: Create sites routes**

Create `web/routes/sites_routes.py`:

```python
"""Sites CRUD + config generation/download routes."""

import asyncio
import io
import os
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.app import get_inventory, get_settings, require_auth

router = APIRouter(prefix="/api/sites", tags=["sites"], dependencies=[Depends(require_auth)])


class SiteCreate(BaseModel):
    name: str
    type: str
    tunnel_ip: str = ""
    wan_ip: str = "dynamic"
    description: str = ""
    ssh: dict | None = None


class SiteUpdate(BaseModel):
    type: str | None = None
    tunnel_ip: str | None = None
    wan_ip: str | None = None
    description: str | None = None
    ssh: dict | None = None


@router.get("/next-ip")
async def next_tunnel_ip():
    return {"tunnel_ip": get_inventory().next_tunnel_ip()}


@router.get("")
async def list_sites():
    return get_inventory().get_sites()


@router.post("")
async def add_site(site: SiteCreate):
    inv = get_inventory()
    data = site.model_dump(exclude_none=True)
    if not data.get("tunnel_ip"):
        data["tunnel_ip"] = inv.next_tunnel_ip()
    try:
        inv.add_site(data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Generate configs in background
    settings = get_settings()
    from scripts.generate_configs import generate_all
    await asyncio.to_thread(
        generate_all, settings["inventory_path"], settings["output_dir"]
    )
    return {"status": "ok", "site": data}


@router.put("/{name}")
async def update_site(name: str, updates: SiteUpdate):
    try:
        get_inventory().update_site(
            name, updates.model_dump(exclude_none=True)
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    settings = get_settings()
    from scripts.generate_configs import generate_all
    await asyncio.to_thread(
        generate_all, settings["inventory_path"], settings["output_dir"]
    )
    return {"status": "ok"}


@router.delete("/{name}")
async def delete_site(name: str):
    try:
        get_inventory().delete_site(name)
    except ValueError as e:
        raise HTTPException(404, str(e))

    settings = get_settings()
    from scripts.generate_configs import generate_all
    await asyncio.to_thread(
        generate_all, settings["inventory_path"], settings["output_dir"]
    )
    return {"status": "ok"}


@router.post("/{name}/generate")
async def generate_site(name: str):
    if get_inventory().get_site(name) is None:
        raise HTTPException(404, f"Site '{name}' not found")
    settings = get_settings()
    from scripts.generate_configs import generate_all
    await asyncio.to_thread(
        generate_all, settings["inventory_path"], settings["output_dir"]
    )
    return {"status": "ok"}


@router.get("/{name}/download")
async def download_site(name: str):
    if get_inventory().get_site(name) is None:
        raise HTTPException(404, f"Site '{name}' not found")
    settings = get_settings()
    site_dir = os.path.join(settings["output_dir"], name)
    if not os.path.isdir(site_dir):
        raise HTTPException(404, "Configs not generated yet")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(site_dir):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, os.path.dirname(site_dir))
                zf.write(full, arc)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={name}.zip"},
    )


@router.post("/hub/regenerate")
async def hub_regenerate():
    settings = get_settings()
    from scripts.generate_configs import generate_all
    await asyncio.to_thread(
        generate_all, settings["inventory_path"], settings["output_dir"]
    )
    # Restart hub services
    proc = await asyncio.create_subprocess_shell(
        "sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-bridge",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(500, f"Hub restart failed: {stderr.decode()}")
    return {"status": "ok"}
```

- [ ] **Step 2: Register router in app.py**

```python
from web.routes.sites_routes import router as sites_router
app.include_router(sites_router)
```

Note: The `/api/sites/hub/regenerate` path must be registered before `/{name}` routes to avoid path conflicts. Move the `hub_regenerate` endpoint to use prefix `/api/hub` instead:

The route is already `@router.post("/hub/regenerate")` which maps to `/api/sites/hub/regenerate`. Move it to a separate path by defining it with the full path. Actually, the spec says `POST /api/hub/regenerate` — so register it on the app directly or in a separate router. Add to `sites_routes.py`:

```python
hub_router = APIRouter(prefix="/api/hub", tags=["hub"], dependencies=[Depends(require_auth)])

@hub_router.post("/regenerate")
async def hub_regenerate():
    # ... (same implementation as above)
```

Register both `router` and `hub_router` in `app.py`.

- [ ] **Step 3: Commit**

```bash
git add web/routes/sites_routes.py web/app.py
git commit -m "feat(web): add sites CRUD, config generation, download, hub regenerate"
```

---

### Task 6: SSH Manager

**Files:**
- Create: `web/ssh_manager.py`
- Create: `web/routes/deploy_routes.py`
- Modify: `web/app.py` (register deploy router)

- [ ] **Step 1: Implement SSH manager**

Create `web/ssh_manager.py`:

```python
"""SSH manager: async SSH commands to remote GL.iNet and Pi devices."""

import asyncio
import os
from typing import AsyncIterator

import asyncssh


COMMANDS = {
    "glinet": {
        "status": "wg show 2>/dev/null; ip link show gretap0 2>/dev/null; bridge link 2>/dev/null",
        "restart": "/etc/init.d/wg-mcast-gretap restart",
        "reboot": "reboot",
    },
    "cradlepoint": {
        "status": "wg show 2>/dev/null; ip link show gretap0 2>/dev/null; bridge link show br0 2>/dev/null",
        "restart": "sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-gretap",
        "reboot": "sudo reboot",
    },
}


def _ssh_config(site: dict) -> dict:
    """Extract SSH connection config from a site dict."""
    ssh = site.get("ssh", {})
    site_type = site.get("type", "glinet")
    default_user = "root" if site_type == "glinet" else "pi"
    return {
        "host": ssh.get("host", site["tunnel_ip"]),
        "user": ssh.get("user", default_user),
        "key": os.path.expanduser(ssh.get("key", "~/.ssh/id_ed25519")),
    }


async def run_ssh_command(site: dict, command: str, timeout: int = 30) -> str:
    """Run a command on a remote site via SSH. Returns combined output."""
    cfg = _ssh_config(site)
    async with asyncssh.connect(
        cfg["host"],
        username=cfg["user"],
        client_keys=[cfg["key"]],
        known_hosts=None,
        connect_timeout=timeout,
    ) as conn:
        result = await asyncio.wait_for(
            conn.run(command, check=False), timeout=timeout
        )
        return (result.stdout or "") + (result.stderr or "")


async def stream_ssh_command(
    site: dict, command: str, timeout: int = 30
) -> AsyncIterator[str]:
    """Stream SSH command output line by line."""
    cfg = _ssh_config(site)
    async with asyncssh.connect(
        cfg["host"],
        username=cfg["user"],
        client_keys=[cfg["key"]],
        known_hosts=None,
        connect_timeout=timeout,
    ) as conn:
        async with conn.create_process(command) as proc:
            async for line in proc.stdout:
                yield line


async def scp_directory(site: dict, local_dir: str, remote_dir: str) -> str:
    """SCP a local directory to the remote site."""
    cfg = _ssh_config(site)
    async with asyncssh.connect(
        cfg["host"],
        username=cfg["user"],
        client_keys=[cfg["key"]],
        known_hosts=None,
    ) as conn:
        await asyncssh.scp(local_dir, (conn, remote_dir), recurse=True)
    return f"Copied {local_dir} to {cfg['host']}:{remote_dir}"


def get_command(site_type: str, action: str) -> str:
    """Get the shell command for a given site type and action."""
    cmds = COMMANDS.get(site_type, COMMANDS["cradlepoint"])
    if action not in cmds:
        raise ValueError(f"Unknown action: {action}")
    return cmds[action]
```

- [ ] **Step 2: Create deploy routes**

Create `web/routes/deploy_routes.py`:

```python
"""Deploy/remote management routes."""

import os

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query

from web.app import get_inventory, get_settings, require_auth
from web.auth import decode_token
import asyncssh
from web.ssh_manager import run_ssh_command, stream_ssh_command, scp_directory, get_command, _ssh_config

router = APIRouter(prefix="/api/sites", tags=["deploy"], dependencies=[Depends(require_auth)])


@router.post("/{name}/push")
async def push_config(name: str):
    """SCP generated configs AND the appropriate setup script to the remote device."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")
    settings = get_settings()
    local_dir = os.path.join(settings["output_dir"], name)
    if not os.path.isdir(local_dir):
        raise HTTPException(400, "Configs not generated yet")
    try:
        result = await scp_directory(site, local_dir, f"/tmp/{name}")
        # Also push the setup script
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        site_type = site.get("type", "glinet")
        if site_type == "glinet":
            script = os.path.join(project_root, "scripts", "glinet-setup.sh")
        else:
            script = os.path.join(project_root, "scripts", "pi-setup.sh")
        cfg = _ssh_config(site)
        async with asyncssh.connect(
            cfg["host"], username=cfg["user"], client_keys=[cfg["key"]], known_hosts=None
        ) as conn:
            await asyncssh.scp(script, (conn, f"/tmp/{name}/"))
        return {"status": "ok", "output": result + f"\nCopied setup script to /tmp/{name}/"}
    except Exception as e:
        raise HTTPException(500, f"SCP failed: {e}")


@router.post("/{name}/setup")
async def run_setup(name: str):
    """Run the full setup script (glinet-setup.sh or pi-setup.sh) on the remote device.
    Assumes configs have been pushed to /tmp/{name}/ first via the push endpoint."""
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")
    site_type = site.get("type", "glinet")
    if site_type == "glinet":
        cmd = f"cd /tmp/{name} && sh /tmp/{name}/glinet-setup.sh /tmp/{name}"
    else:
        cmd = f"cd /tmp/{name} && sudo bash /tmp/{name}/pi-setup.sh /tmp/{name}"
    try:
        output = await run_ssh_command(site, cmd, timeout=120)
        return {"status": "ok", "output": output}
    except Exception as e:
        raise HTTPException(500, f"Setup failed: {e}")


@router.post("/{name}/restart")
async def restart_site(name: str):
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")
    cmd = get_command(site.get("type", "glinet"), "restart")
    try:
        output = await run_ssh_command(site, cmd)
        return {"status": "ok", "output": output}
    except Exception as e:
        raise HTTPException(500, f"Restart failed: {e}")


@router.post("/{name}/status")
async def site_status(name: str):
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")
    cmd = get_command(site.get("type", "glinet"), "status")
    try:
        output = await run_ssh_command(site, cmd)
        return {"status": "ok", "output": output}
    except Exception as e:
        raise HTTPException(500, f"Status check failed: {e}")


@router.post("/{name}/reboot")
async def reboot_site(name: str):
    site = get_inventory().get_site(name)
    if not site:
        raise HTTPException(404, f"Site '{name}' not found")
    cmd = get_command(site.get("type", "glinet"), "reboot")
    try:
        output = await run_ssh_command(site, cmd, timeout=10)
        return {"status": "ok", "output": output}
    except Exception as e:
        # Reboot may disconnect before response — that's OK
        return {"status": "ok", "output": f"Reboot initiated (connection closed: {e})"}


ssh_ws_router = APIRouter(tags=["deploy"])


@ssh_ws_router.websocket("/api/ws/ssh/{name}")
async def ws_ssh(ws: WebSocket, name: str, token: str = Query(...)):
    from web.app import get_settings
    try:
        decode_token(token, get_settings()["jwt_secret"])
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        return

    site = get_inventory().get_site(name)
    if not site:
        await ws.close(code=1008, reason="Site not found")
        return

    await ws.accept()
    try:
        # Wait for command from client
        data = await ws.receive_json()
        cmd = data.get("command", "")
        async for line in stream_ssh_command(site, cmd):
            await ws.send_text(line)
        await ws.send_json({"done": True})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_json({"error": str(e), "done": True})
```

- [ ] **Step 3: Register deploy routers in app.py**

```python
from web.routes.deploy_routes import router as deploy_router, ssh_ws_router
app.include_router(deploy_router)
app.include_router(ssh_ws_router)
```

- [ ] **Step 4: Commit**

```bash
git add web/ssh_manager.py web/routes/deploy_routes.py web/app.py
git commit -m "feat(web): add SSH manager and deploy/remote management routes"
```

---

### Task 7: Frontend — Login + App Shell

**Files:**
- Create: `web/templates/login.html`
- Create: `web/templates/index.html`
- Create: `web/static/css/style.css`
- Create: `web/static/js/app.js`

- [ ] **Step 1: Create login page**

Create `web/templates/login.html` — simple form with dark theme, posts to `/api/auth/login`, stores JWT in localStorage, redirects to `/`.

- [ ] **Step 2: Create app shell**

Create `web/templates/index.html` — nav bar (Dashboard, Sites, Traffic, Deploy), content div, script tags for all JS files.

- [ ] **Step 3: Create CSS**

Create `web/static/css/style.css` — full dark theme from the mockup (all the styles from the dashboard mockup HTML, extracted and organized).

- [ ] **Step 4: Create app.js**

Create `web/static/js/app.js`:
- Auth manager: stores/reads JWT from localStorage, redirects to `/login` if missing
- Router: hash-based routing (`#dashboard`, `#sites`, `#traffic`, `#deploy`)
- WebSocket manager: connects to `/api/ws/stats?token=<jwt>`, auto-reconnects
- API helper: `api(method, path, body)` that adds auth header
- Format helpers: `formatBytes()`, `formatAge()`

- [ ] **Step 5: Create empty view JS files as stubs**

Create `web/static/js/dashboard.js`, `web/static/js/sites.js`, `web/static/js/traffic.js`, `web/static/js/deploy.js` — each exports a `render(container)` function that shows a placeholder.

- [ ] **Step 6: Verify the app loads in a browser**

```bash
source .venv/bin/activate
ADMIN_USER=admin ADMIN_PASSWORD_HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode())") JWT_SECRET=devsecret \
  python -m uvicorn web.app:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080/login`, log in with admin/admin, verify redirect to dashboard.

- [ ] **Step 7: Commit**

```bash
git add web/templates/ web/static/
git commit -m "feat(web): add login page, app shell, dark theme CSS, client-side router"
```

---

### Task 8: Frontend — Dashboard View

**Files:**
- Modify: `web/static/js/dashboard.js`

- [ ] **Step 1: Implement dashboard view**

Replace stub in `web/static/js/dashboard.js` with:
- Summary cards (total, online, stale, offline) — populated from WebSocket data
- Sites table with all columns from mockup (name, type badge, status badge, tunnel IP, endpoint, TX/RX, last seen, action buttons)
- Bridge status panel with per-port stats
- Auto-updates when WebSocket pushes new data (re-renders on each message)

Action buttons:
- SSH terminal icon → navigates to `#deploy` with site pre-selected
- Restart icon → calls `POST /api/sites/{name}/restart`
- Download icon → opens `GET /api/sites/{name}/download`

- [ ] **Step 2: Verify dashboard shows live data**

Open `http://<hub-ip>:8080`, log in, verify dashboard shows the test-site-01 peer and bridge ports.

- [ ] **Step 3: Commit**

```bash
git add web/static/js/dashboard.js
git commit -m "feat(web): implement dashboard with live stats, sites table, bridge status"
```

---

### Task 9: Frontend — Sites CRUD View

**Files:**
- Modify: `web/static/js/sites.js`

- [ ] **Step 1: Implement sites view**

Replace stub in `web/static/js/sites.js` with:
- Sites table with edit/delete buttons
- "Add Site" button opens a form: name, type dropdown (glinet/cradlepoint), tunnel IP (pre-filled with next available from API), WAN IP, description, SSH fields (host, user, key)
- Edit button opens same form pre-populated
- Delete button shows confirmation modal
- All operations call the REST API and refresh the table
- "Apply to Hub" button calls `POST /api/hub/regenerate`

- [ ] **Step 2: Test add/edit/delete through the UI**

- [ ] **Step 3: Commit**

```bash
git add web/static/js/sites.js
git commit -m "feat(web): implement sites CRUD view with add/edit/delete forms"
```

---

### Task 10: Frontend — Traffic View

**Files:**
- Modify: `web/static/js/traffic.js`

- [ ] **Step 1: Implement traffic view**

Replace stub in `web/static/js/traffic.js` with:
- Per-site bandwidth bars showing TX (green) / RX (blue) bytes with labels
- Per-bridge-port stats table: port name, state, RX bytes/packets/errors, TX bytes/packets/errors
- Data from the same WebSocket stream — auto-updates

- [ ] **Step 2: Commit**

```bash
git add web/static/js/traffic.js
git commit -m "feat(web): implement traffic monitor with per-site and per-port stats"
```

---

### Task 11: Frontend — Deploy View

**Files:**
- Modify: `web/static/js/deploy.js`

- [ ] **Step 1: Implement deploy view**

Replace stub in `web/static/js/deploy.js` with:
- Site selector with checkboxes (populated from inventory)
- Action dropdown: Push Config, Run Setup, Restart WireGuard, Reboot
- "Execute" button — confirmation modal for destructive actions (Run Setup, Reboot)
- Live output log panel (monospace, dark background, scrolls to bottom)
- For each selected site, sequentially: call the REST endpoint, stream output to the log panel
- For actions that support WebSocket streaming, connect to `/api/ws/ssh/{name}` and stream output

- [ ] **Step 2: Commit**

```bash
git add web/static/js/deploy.js
git commit -m "feat(web): implement deploy view with bulk actions and live output log"
```

---

### Task 12: Web Setup Script

**Files:**
- Create: `scripts/web-setup.sh`

- [ ] **Step 1: Write setup script**

Create `scripts/web-setup.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Outpost Conduit Web UI setup
# Usage: sudo ./scripts/web-setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
SERVICE_USER="${SUDO_USER:-$(whoami)}"

echo "=== Outpost Conduit Web UI Setup ==="

# --- Create venv ---
echo "[1/5] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q fastapi "uvicorn[standard]" asyncssh bcrypt pyjwt pyyaml

# --- Create .env ---
if [ ! -f "$ENV_FILE" ]; then
    echo "[2/5] Configuring admin credentials..."
    read -rp "Admin username [admin]: " ADMIN_USER
    ADMIN_USER="${ADMIN_USER:-admin}"
    read -rsp "Admin password: " ADMIN_PASS
    echo
    ADMIN_HASH=$("$VENV_DIR/bin/python3" -c "import bcrypt; print(bcrypt.hashpw(b'$ADMIN_PASS', bcrypt.gensalt()).decode())")
    JWT_SECRET=$(openssl rand -hex 32)

    cat > "$ENV_FILE" << EOF
ADMIN_USER=$ADMIN_USER
ADMIN_PASSWORD_HASH=$ADMIN_HASH
JWT_SECRET=$JWT_SECRET
INVENTORY_PATH=$PROJECT_DIR/sites.yaml
OUTPUT_DIR=$PROJECT_DIR/output
EOF
    chmod 600 "$ENV_FILE"
    echo "  Credentials saved to $ENV_FILE"
else
    echo "[2/5] .env already exists, skipping..."
fi

# --- Install systemd service ---
echo "[3/5] Installing systemd service..."
cat > /etc/systemd/system/outpost-conduit-web.service << UNIT
[Unit]
Description=Outpost Conduit Web UI
After=wg-quick@wg0.service wg-mcast-bridge.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/uvicorn web.app:app --host 0.0.0.0 --port 8080
Restart=always
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
UNIT

# --- Enable and start ---
echo "[4/5] Starting service..."
systemctl daemon-reload
systemctl enable outpost-conduit-web
systemctl start outpost-conduit-web

# --- Done ---
echo "[5/5] Verifying..."
sleep 2
if systemctl is-active outpost-conduit-web >/dev/null; then
    echo ""
    echo "=== Web UI is running ==="
    echo "URL: http://$(hostname -I | awk '{print $1}'):8080"
    echo "Service: systemctl status outpost-conduit-web"
else
    echo "ERROR: Service failed to start"
    systemctl status outpost-conduit-web
    exit 1
fi
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/web-setup.sh
git add scripts/web-setup.sh
git commit -m "feat(web): add web UI setup script with venv, credentials, and systemd"
```

---

### Task 13: Integration Test + Final Cleanup

**Files:**
- Create: `tests/test_routes.py`
- Modify: `.gitignore` (add `venv/`, `.env`)

- [ ] **Step 1: Write integration tests**

Create `tests/test_routes.py` using FastAPI's `TestClient`:

```python
import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["ADMIN_USER"] = "admin"
os.environ["JWT_SECRET"] = "testsecret"

from web.auth import hash_password
os.environ["ADMIN_PASSWORD_HASH"] = hash_password("testpass")

from web.app import app

client = TestClient(app)


class TestAuth:
    def test_login_success(self):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "testpass"})
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_bad_password(self):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_protected_route_no_token(self):
        r = client.get("/api/status")
        assert r.status_code == 401

    def test_protected_route_with_token(self):
        login = client.post("/api/auth/login", json={"username": "admin", "password": "testpass"})
        token = login.json()["token"]
        r = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
```

- [ ] **Step 2: Update .gitignore**

Append:
```
venv/
.env
```

- [ ] **Step 3: Run full test suite**

```bash
source .venv/bin/activate && python -m pytest tests/ -v
```

Expected: All tests pass (existing 40 + new auth/stats/inventory/route tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_routes.py .gitignore
git commit -m "feat(web): add integration tests and update gitignore"
```

- [ ] **Step 5: Push to GitHub**

```bash
git push
```
