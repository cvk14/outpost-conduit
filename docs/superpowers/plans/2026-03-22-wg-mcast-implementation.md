# wg-mcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build tooling that creates and manages GRETAP-over-WireGuard tunnels in a hub-and-spoke topology, enabling IP multicast across all sites.

**Architecture:** A Python config generator reads a YAML site inventory and outputs WireGuard configs, GRETAP/bridge setup scripts, and key material for the hub and each remote site. Shell scripts provision the hub VM, GL.iNet (OpenWrt) routers, and Raspberry Pi sidecars. A health monitor checks tunnel status.

**Tech Stack:** Python 3 + PyYAML (config generator), Bash/shell (setup scripts), WireGuard + iproute2 + bridge-utils (networking), systemd (service management)

**Spec:** `docs/superpowers/specs/2026-03-22-multicast-over-wireguard-design.md`

---

## File Structure

```
wg-multicast/
├── LICENSE                          # MIT license
├── sites.yaml.example               # Annotated site inventory template
├── scripts/
│   ├── generate_configs.py          # Config generator — reads sites.yaml, outputs all configs + keys
│   ├── hub-setup.sh                 # Hub VM provisioning (installs deps, applies generated configs)
│   ├── glinet-setup.sh              # GL.iNet (OpenWrt) provisioning
│   ├── pi-setup.sh                  # Raspberry Pi provisioning
│   ├── add-site.sh                  # Day-2: add a site to inventory + regenerate
│   ├── remove-site.sh               # Day-2: remove a site from inventory + regenerate
│   └── health-check.sh              # Hub-side tunnel + bridge health monitor
├── tests/
│   ├── conftest.py                  # Shared fixtures (sample sites.yaml, temp dirs)
│   ├── test_inventory.py            # YAML parsing + validation tests
│   ├── test_keygen.py               # WireGuard key generation tests
│   ├── test_wg_configs.py           # WireGuard config file generation tests
│   ├── test_gretap_scripts.py       # GRETAP/bridge setup script generation tests
│   └── test_cli.py                  # CLI argument parsing + end-to-end output tests
├── docs/
│   ├── setup-guide.md               # Step-by-step deployment guide
│   └── superpowers/
│       ├── specs/...
│       └── plans/...
└── output/                          # Generated configs (gitignored)
```

**Key design decisions:**
- Templates are embedded as Python multiline strings in `generate_configs.py` — no Jinja2 dependency, no separate template files. The configs are simple enough that f-strings work well.
- Single generator script rather than a package. Under ~500 lines. If it grows, split later.
- Shell scripts are thin — they install dependencies and apply the generated configs. The generator does the heavy lifting.
- TDD for the Python config generator. Shell scripts are validated via shellcheck and manual testing on target hardware.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `LICENSE`
- Create: `sites.yaml.example`
- Modify: `.gitignore` (add `output/` directory)

- [ ] **Step 1: Create MIT LICENSE file**

```
MIT License

Copyright (c) 2026 wg-mcast contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Create sites.yaml.example**

```yaml
# wg-mcast site inventory
# Copy to sites.yaml and edit for your deployment.

hub:
  # WAN IP or hostname where remote sites connect
  # Use a static IP or dynamic DNS hostname
  wan_ip: "203.0.113.10"
  tunnel_ip: "172.27.0.1"
  listen_port: 51820

sites:
  - name: "site-01-example"
    # Site type: "glinet" (OpenWrt router) or "cradlepoint" (Pi sidecar)
    type: "glinet"
    # Tunnel IP — must be unique per site, format: 172.27.N.1
    tunnel_ip: "172.27.1.1"
    # WAN IP of the remote router, or "dynamic" if behind NAT/DHCP
    wan_ip: "198.51.100.1"
    description: "Example GL.iNet site"

  - name: "site-02-example"
    type: "cradlepoint"
    tunnel_ip: "172.27.2.1"
    wan_ip: "dynamic"
    description: "Example Cradlepoint + Pi site"
```

- [ ] **Step 3: Update .gitignore**

Append to existing `.gitignore`:
```
output/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Create directory structure**

```bash
mkdir -p scripts tests docs
```

- [ ] **Step 5: Commit**

```bash
git add LICENSE sites.yaml.example .gitignore
git commit -m "scaffold: add LICENSE, site inventory template, gitignore"
```

---

### Task 2: Config Generator — Inventory Parsing & Key Generation

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_inventory.py`
- Create: `tests/test_keygen.py`
- Create: `scripts/generate_configs.py` (partial — inventory + keygen modules)

- [ ] **Step 1: Create test fixtures**

Create `tests/conftest.py`:

```python
import os
import pytest
import tempfile
import yaml


@pytest.fixture
def sample_inventory():
    """Minimal valid site inventory."""
    return {
        "hub": {
            "wan_ip": "203.0.113.10",
            "tunnel_ip": "172.27.0.1",
            "listen_port": 51820,
        },
        "sites": [
            {
                "name": "site-01",
                "type": "glinet",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "198.51.100.1",
                "description": "Test GL.iNet site",
            },
            {
                "name": "site-02",
                "type": "cradlepoint",
                "tunnel_ip": "172.27.2.1",
                "wan_ip": "dynamic",
                "description": "Test Cradlepoint site",
            },
        ],
    }


@pytest.fixture
def sample_inventory_file(sample_inventory, tmp_path):
    """Write sample inventory to a temp YAML file."""
    path = tmp_path / "sites.yaml"
    path.write_text(yaml.dump(sample_inventory))
    return str(path)


@pytest.fixture
def output_dir(tmp_path):
    """Temp output directory for generated configs."""
    out = tmp_path / "output"
    out.mkdir()
    return str(out)
```

- [ ] **Step 2: Write inventory parsing tests**

Create `tests/test_inventory.py`:

```python
import pytest
import yaml
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import load_inventory, validate_inventory


class TestLoadInventory:
    def test_loads_valid_yaml(self, sample_inventory_file):
        inv = load_inventory(sample_inventory_file)
        assert inv["hub"]["tunnel_ip"] == "172.27.0.1"
        assert len(inv["sites"]) == 2

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_inventory("/nonexistent/sites.yaml")


class TestValidateInventory:
    def test_valid_inventory_passes(self, sample_inventory):
        validate_inventory(sample_inventory)  # should not raise

    def test_missing_hub_raises(self, sample_inventory):
        del sample_inventory["hub"]
        with pytest.raises(ValueError, match="hub"):
            validate_inventory(sample_inventory)

    def test_missing_hub_tunnel_ip_raises(self, sample_inventory):
        del sample_inventory["hub"]["tunnel_ip"]
        with pytest.raises(ValueError, match="tunnel_ip"):
            validate_inventory(sample_inventory)

    def test_missing_site_name_raises(self, sample_inventory):
        del sample_inventory["sites"][0]["name"]
        with pytest.raises(ValueError, match="name"):
            validate_inventory(sample_inventory)

    def test_invalid_site_type_raises(self, sample_inventory):
        sample_inventory["sites"][0]["type"] = "cisco"
        with pytest.raises(ValueError, match="type"):
            validate_inventory(sample_inventory)

    def test_duplicate_tunnel_ip_raises(self, sample_inventory):
        sample_inventory["sites"][1]["tunnel_ip"] = "172.27.1.1"
        with pytest.raises(ValueError, match="duplicate"):
            validate_inventory(sample_inventory)

    def test_duplicate_site_name_raises(self, sample_inventory):
        sample_inventory["sites"][1]["name"] = "site-01"
        with pytest.raises(ValueError, match="duplicate"):
            validate_inventory(sample_inventory)

    def test_no_sites_raises(self, sample_inventory):
        sample_inventory["sites"] = []
        with pytest.raises(ValueError, match="sites"):
            validate_inventory(sample_inventory)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_inventory.py -v`
Expected: ImportError — `generate_configs` module not found

- [ ] **Step 4: Implement inventory loading and validation**

Create `scripts/generate_configs.py` (first section):

```python
#!/usr/bin/env python3
"""wg-mcast config generator.

Reads a sites.yaml inventory and generates WireGuard configs,
GRETAP/bridge setup scripts, and key material for all sites.
"""

import argparse
import os
import subprocess
import sys
import yaml

VALID_SITE_TYPES = {"glinet", "cradlepoint"}
HUB_REQUIRED_FIELDS = {"wan_ip", "tunnel_ip", "listen_port"}
SITE_REQUIRED_FIELDS = {"name", "type", "tunnel_ip", "wan_ip"}


def load_inventory(path: str) -> dict:
    """Load and return the YAML site inventory."""
    with open(path) as f:
        return yaml.safe_load(f)


def validate_inventory(inv: dict) -> None:
    """Validate inventory structure. Raises ValueError on problems."""
    if "hub" not in inv:
        raise ValueError("Missing required 'hub' section")

    for field in HUB_REQUIRED_FIELDS:
        if field not in inv["hub"]:
            raise ValueError(f"Hub missing required field: {field}")

    if "sites" not in inv or not inv["sites"]:
        raise ValueError("Must define at least one entry in 'sites'")

    seen_names = set()
    seen_ips = {inv["hub"]["tunnel_ip"]}

    for i, site in enumerate(inv["sites"]):
        for field in SITE_REQUIRED_FIELDS:
            if field not in site:
                raise ValueError(
                    f"Site at index {i} missing required field: {field}"
                )

        if site["type"] not in VALID_SITE_TYPES:
            raise ValueError(
                f"Site '{site['name']}' has invalid type '{site['type']}'. "
                f"Must be one of: {VALID_SITE_TYPES}"
            )

        if site["name"] in seen_names:
            raise ValueError(f"Duplicate site name: '{site['name']}'")
        seen_names.add(site["name"])

        if site["tunnel_ip"] in seen_ips:
            raise ValueError(
                f"Duplicate tunnel_ip: '{site['tunnel_ip']}' "
                f"in site '{site['name']}'"
            )
        seen_ips.add(site["tunnel_ip"])
```

- [ ] **Step 5: Run inventory tests to verify they pass**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_inventory.py -v`
Expected: All 9 tests PASS

- [ ] **Step 6: Write key generation tests**

Create `tests/test_keygen.py`:

```python
import os
import sys
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import generate_keypair, generate_psk


class TestGenerateKeypair:
    def test_returns_private_and_public(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, str)
        assert isinstance(pub, str)

    def test_keys_are_base64_44_chars(self):
        priv, pub = generate_keypair()
        # WireGuard keys are 32 bytes base64-encoded = 44 chars with =
        assert len(priv) == 44
        assert len(pub) == 44
        # Should be valid base64
        base64.b64decode(priv)
        base64.b64decode(pub)

    def test_keypairs_are_unique(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestGeneratePsk:
    def test_returns_base64_string(self):
        psk = generate_psk()
        assert len(psk) == 44
        base64.b64decode(psk)

    def test_psks_are_unique(self):
        psk1 = generate_psk()
        psk2 = generate_psk()
        assert psk1 != psk2
```

- [ ] **Step 7: Run keygen tests to verify they fail**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_keygen.py -v`
Expected: ImportError — `generate_keypair` not found

- [ ] **Step 8: Implement key generation**

Append to `scripts/generate_configs.py`:

```python
def generate_keypair() -> tuple[str, str]:
    """Generate a WireGuard key pair. Returns (private_key, public_key)."""
    result = subprocess.run(
        ["wg", "genkey"], capture_output=True, text=True, check=True
    )
    private_key = result.stdout.strip()

    result = subprocess.run(
        ["wg", "pubkey"],
        input=private_key,
        capture_output=True,
        text=True,
        check=True,
    )
    public_key = result.stdout.strip()
    return private_key, public_key


def generate_psk() -> str:
    """Generate a WireGuard preshared key."""
    result = subprocess.run(
        ["wg", "genpsk"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
```

- [ ] **Step 9: Run keygen tests to verify they pass**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_keygen.py -v`
Expected: All 5 tests PASS

Note: Requires `wg` (wireguard-tools) installed on the build machine. If not available, these tests will be skipped or fail with a clear error. Install via: `brew install wireguard-tools` (macOS) or `apt install wireguard-tools` (Linux).

- [ ] **Step 10: Commit**

```bash
git add scripts/generate_configs.py tests/conftest.py tests/test_inventory.py tests/test_keygen.py
git commit -m "feat: add inventory parsing, validation, and key generation"
```

---

### Task 3: Config Generator — WireGuard Config Output

**Files:**
- Create: `tests/test_wg_configs.py`
- Modify: `scripts/generate_configs.py` (add WireGuard config generation)

- [ ] **Step 1: Write WireGuard config generation tests**

Create `tests/test_wg_configs.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import generate_hub_wg_config, generate_site_wg_config


class TestHubWgConfig:
    def test_contains_interface_section(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [
            {
                "name": "site-01",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "198.51.100.1",
                "public_key": "SITE01PUBKEY=",
                "psk": "SITE01PSK=",
            }
        ]
        config = generate_hub_wg_config(hub, sites, "HUBPRIVKEY=")
        assert "[Interface]" in config
        assert "Address = 172.27.0.1/16" in config
        assert "ListenPort = 51820" in config
        assert "PrivateKey = HUBPRIVKEY=" in config

    def test_contains_peer_per_site(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [
            {
                "name": "s1",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "1.2.3.4",
                "public_key": "PUB1=",
                "psk": "PSK1=",
            },
            {
                "name": "s2",
                "tunnel_ip": "172.27.2.1",
                "wan_ip": "dynamic",
                "public_key": "PUB2=",
                "psk": "PSK2=",
            },
        ]
        config = generate_hub_wg_config(hub, sites, "HUBPK=")
        assert config.count("[Peer]") == 2
        assert "PublicKey = PUB1=" in config
        assert "PublicKey = PUB2=" in config
        assert "PresharedKey = PSK1=" in config
        assert "AllowedIPs = 172.27.1.1/32" in config
        assert "AllowedIPs = 172.27.2.1/32" in config

    def test_static_endpoint_included(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [
            {
                "name": "s1",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "1.2.3.4",
                "public_key": "PUB=",
                "psk": "PSK=",
            }
        ]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "Endpoint = 1.2.3.4:51820" in config

    def test_dynamic_endpoint_omitted(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [
            {
                "name": "s1",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "dynamic",
                "public_key": "PUB=",
                "psk": "PSK=",
            }
        ]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "Endpoint" not in config

    def test_persistent_keepalive_on_all_peers(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [
            {
                "name": "s1",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "1.2.3.4",
                "public_key": "PUB=",
                "psk": "PSK=",
            }
        ]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "PersistentKeepalive = 25" in config


class TestSiteWgConfig:
    def test_site_config_structure(self):
        hub = {
            "wan_ip": "203.0.113.10",
            "tunnel_ip": "172.27.0.1",
            "listen_port": 51820,
            "public_key": "HUBPUB=",
        }
        site = {
            "name": "site-01",
            "tunnel_ip": "172.27.1.1",
            "private_key": "SITEPK=",
            "psk": "PSK=",
        }
        config = generate_site_wg_config(hub, site)
        assert "[Interface]" in config
        assert "Address = 172.27.1.1/32" in config
        assert "PrivateKey = SITEPK=" in config
        assert "[Peer]" in config
        assert "PublicKey = HUBPUB=" in config
        assert "Endpoint = 203.0.113.10:51820" in config
        assert "AllowedIPs = 172.27.0.0/16" in config
        assert "PersistentKeepalive = 25" in config

    def test_mtu_set_to_1420(self):
        hub = {
            "wan_ip": "203.0.113.10",
            "tunnel_ip": "172.27.0.1",
            "listen_port": 51820,
            "public_key": "HUBPUB=",
        }
        site = {
            "name": "s1",
            "tunnel_ip": "172.27.1.1",
            "private_key": "PK=",
            "psk": "PSK=",
        }
        config = generate_site_wg_config(hub, site)
        assert "MTU = 1420" in config
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_wg_configs.py -v`
Expected: ImportError — functions not found

- [ ] **Step 3: Implement WireGuard config generators**

Append to `scripts/generate_configs.py`:

```python
def generate_hub_wg_config(
    hub: dict, sites: list[dict], hub_private_key: str
) -> str:
    """Generate the hub's wg0.conf content."""
    lines = [
        "[Interface]",
        f"Address = {hub['tunnel_ip']}/16",
        f"ListenPort = {hub['listen_port']}",
        f"PrivateKey = {hub_private_key}",
        "MTU = 1420",
        "",
    ]

    for site in sites:
        lines.append(f"# {site['name']}")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {site['public_key']}")
        lines.append(f"PresharedKey = {site['psk']}")
        lines.append(f"AllowedIPs = {site['tunnel_ip']}/32")
        if site["wan_ip"] != "dynamic":
            lines.append(
                f"Endpoint = {site['wan_ip']}:{hub['listen_port']}"
            )
        lines.append("PersistentKeepalive = 25")
        lines.append("")

    return "\n".join(lines)


def generate_site_wg_config(hub: dict, site: dict) -> str:
    """Generate a remote site's wg0.conf content."""
    lines = [
        "[Interface]",
        f"Address = {site['tunnel_ip']}/32",
        f"PrivateKey = {site['private_key']}",
        "MTU = 1420",
        "",
        "[Peer]",
        f"PublicKey = {hub['public_key']}",
        f"PresharedKey = {site['psk']}",
        f"Endpoint = {hub['wan_ip']}:{hub['listen_port']}",
        "AllowedIPs = 172.27.0.0/16",
        "PersistentKeepalive = 25",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_wg_configs.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_wg_configs.py scripts/generate_configs.py
git commit -m "feat: add WireGuard config generation for hub and sites"
```

---

### Task 4: Config Generator — GRETAP/Bridge Script Output

**Files:**
- Create: `tests/test_gretap_scripts.py`
- Modify: `scripts/generate_configs.py` (add GRETAP script generators)

- [ ] **Step 1: Write GRETAP script generation tests**

Create `tests/test_gretap_scripts.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import (
    generate_hub_bridge_script,
    generate_hub_teardown_script,
    generate_glinet_gretap_script,
    generate_pi_gretap_script,
)


class TestHubBridgeScript:
    def test_creates_bridge(self):
        sites = [
            {"name": "s1", "tunnel_ip": "172.27.1.1"},
            {"name": "s2", "tunnel_ip": "172.27.2.1"},
        ]
        script = generate_hub_bridge_script("172.27.0.1", sites, "eth1")
        assert "ip link add br-mcast type bridge" in script
        assert "stp_state 1" in script

    def test_creates_gretap_per_site(self):
        sites = [
            {"name": "s1", "tunnel_ip": "172.27.1.1"},
            {"name": "s2", "tunnel_ip": "172.27.2.1"},
        ]
        script = generate_hub_bridge_script("172.27.0.1", sites, "eth1")
        assert "gretap_s1" in script or "gretap-s1" in script
        assert "remote 172.27.1.1" in script
        assert "remote 172.27.2.1" in script
        assert "local 172.27.0.1" in script

    def test_sets_mtu_1380(self):
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1"}]
        script = generate_hub_bridge_script("172.27.0.1", sites, "eth1")
        assert "mtu 1380" in script

    def test_bridges_eth1(self):
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1"}]
        script = generate_hub_bridge_script("172.27.0.1", sites, "eth1")
        assert "master br-mcast" in script
        assert "eth1" in script

    def test_has_shebang_and_set_e(self):
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1"}]
        script = generate_hub_bridge_script("172.27.0.1", sites, "eth1")
        assert script.startswith("#!/bin/bash")
        assert "set -e" in script


class TestHubTeardownScript:
    def test_deletes_bridge_and_gretaps(self):
        sites = [
            {"name": "s1", "tunnel_ip": "172.27.1.1"},
            {"name": "s2", "tunnel_ip": "172.27.2.1"},
        ]
        script = generate_hub_teardown_script(sites)
        assert "ip link del br-mcast" in script
        assert "gretap_s1" in script or "gretap-s1" in script


class TestGlinetGretapScript:
    def test_creates_gretap_and_bridges_to_br_lan(self):
        script = generate_glinet_gretap_script(
            "172.27.1.1", "172.27.0.1"
        )
        assert "gretap" in script
        assert "local 172.27.1.1" in script
        assert "remote 172.27.0.1" in script
        assert "br-lan" in script
        assert "mtu 1380" in script

    def test_uses_uci_for_openwrt(self):
        script = generate_glinet_gretap_script(
            "172.27.1.1", "172.27.0.1"
        )
        # Should use ip commands (UCI is for WireGuard, GRETAP via ip link)
        assert "ip link add" in script


class TestPiGretapScript:
    def test_creates_gretap_and_bridge(self):
        script = generate_pi_gretap_script("172.27.2.1", "172.27.0.1")
        assert "gretap" in script
        assert "local 172.27.2.1" in script
        assert "remote 172.27.0.1" in script
        assert "br0" in script
        assert "eth0" in script
        assert "mtu 1380" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_gretap_scripts.py -v`
Expected: ImportError — functions not found

- [ ] **Step 3: Implement GRETAP script generators**

Append to `scripts/generate_configs.py`:

```python
def _sanitize_name(name: str) -> str:
    """Sanitize site name for use in interface names (max 15 chars for Linux)."""
    sanitized = name.replace(" ", "-").replace("_", "-")
    # Linux interface names max 15 chars, prefix "gretap-" = 7, leaves 8
    return sanitized[:8]


def generate_hub_bridge_script(
    hub_tunnel_ip: str, sites: list[dict], mcast_nic: str
) -> str:
    """Generate the hub's bridge + GRETAP setup script."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# wg-mcast: Hub bridge + GRETAP setup",
        f"# Auto-generated — do not edit manually",
        "",
        "# Create bridge",
        "ip link add br-mcast type bridge",
        "ip link set br-mcast type bridge stp_state 1",
        "ip link set br-mcast mtu 1380",
        "ip link set br-mcast up",
        "",
        f"# Add multicast NIC to bridge",
        f"ip link set {mcast_nic} master br-mcast",
        f"ip link set {mcast_nic} up",
        "",
        "# Create GRETAP tunnels",
    ]

    for site in sites:
        iface = f"gretap-{_sanitize_name(site['name'])}"
        lines.extend([
            f"# {site['name']}",
            f"ip link add {iface} type gretap local {hub_tunnel_ip} remote {site['tunnel_ip']}",
            f"ip link set {iface} mtu 1380",
            f"ip link set {iface} master br-mcast",
            f"ip link set {iface} up",
            "",
        ])

    lines.append('echo "Hub bridge setup complete."')
    return "\n".join(lines)


def generate_hub_teardown_script(sites: list[dict]) -> str:
    """Generate the hub's bridge teardown script."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# wg-mcast: Hub bridge teardown",
        "",
    ]

    for site in sites:
        iface = f"gretap-{_sanitize_name(site['name'])}"
        lines.append(f"ip link del {iface} 2>/dev/null || true")

    lines.extend([
        "",
        "ip link del br-mcast 2>/dev/null || true",
        "",
        'echo "Hub bridge teardown complete."',
    ])
    return "\n".join(lines)


def generate_glinet_gretap_script(
    site_tunnel_ip: str, hub_tunnel_ip: str
) -> str:
    """Generate a GL.iNet (OpenWrt) GRETAP + bridge setup script."""
    return f"""#!/bin/sh
set -e

# wg-mcast: GL.iNet GRETAP + bridge setup
# Run after WireGuard is up and tunnel is established.

# Create GRETAP tunnel
ip link add gretap0 type gretap local {site_tunnel_ip} remote {hub_tunnel_ip}
ip link set gretap0 mtu 1380
ip link set gretap0 up

# Add GRETAP to existing LAN bridge
ip link set gretap0 master br-lan

echo "GL.iNet GRETAP setup complete."
"""


def generate_pi_gretap_script(
    site_tunnel_ip: str, hub_tunnel_ip: str
) -> str:
    """Generate a Raspberry Pi GRETAP + bridge setup script."""
    return f"""#!/bin/bash
set -e

# wg-mcast: Raspberry Pi GRETAP + bridge setup
# Run after WireGuard is up and tunnel is established.

# Create GRETAP tunnel
ip link add gretap0 type gretap local {site_tunnel_ip} remote {hub_tunnel_ip}
ip link set gretap0 mtu 1380
ip link set gretap0 up

# Create bridge and add GRETAP + eth0
ip link add br0 type bridge
ip link set br0 mtu 1380
ip link set br0 up

ip link set gretap0 master br0
ip link set eth0 master br0

echo "Pi GRETAP + bridge setup complete."
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_gretap_scripts.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gretap_scripts.py scripts/generate_configs.py
git commit -m "feat: add GRETAP/bridge script generation for hub, glinet, and pi"
```

---

### Task 5: Config Generator — CLI & End-to-End Output

**Files:**
- Create: `tests/test_cli.py`
- Modify: `scripts/generate_configs.py` (add CLI + orchestration + `main()`)

- [ ] **Step 1: Write CLI / end-to-end tests**

Create `tests/test_cli.py`:

```python
import os
import sys
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import generate_all


class TestGenerateAll:
    def test_creates_output_directory_structure(
        self, sample_inventory_file, output_dir
    ):
        generate_all(sample_inventory_file, output_dir)

        # Hub directory
        assert os.path.isdir(os.path.join(output_dir, "hub"))
        assert os.path.isfile(os.path.join(output_dir, "hub", "wg0.conf"))
        assert os.path.isfile(
            os.path.join(output_dir, "hub", "setup-bridge.sh")
        )
        assert os.path.isfile(
            os.path.join(output_dir, "hub", "teardown-bridge.sh")
        )

        # Site directories
        assert os.path.isdir(os.path.join(output_dir, "site-01"))
        assert os.path.isfile(
            os.path.join(output_dir, "site-01", "wg0.conf")
        )
        assert os.path.isfile(
            os.path.join(output_dir, "site-01", "setup-gretap.sh")
        )

        assert os.path.isdir(os.path.join(output_dir, "site-02"))

    def test_creates_key_files(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)

        # Hub keys
        assert os.path.isfile(
            os.path.join(output_dir, "hub", "keys", "privatekey")
        )
        assert os.path.isfile(
            os.path.join(output_dir, "hub", "keys", "publickey")
        )

        # Site keys
        for site_name in ["site-01", "site-02"]:
            keys_dir = os.path.join(output_dir, site_name, "keys")
            assert os.path.isfile(os.path.join(keys_dir, "privatekey"))
            assert os.path.isfile(os.path.join(keys_dir, "publickey"))
            assert os.path.isfile(os.path.join(keys_dir, "presharedkey"))

    def test_key_files_have_restricted_permissions(
        self, sample_inventory_file, output_dir
    ):
        generate_all(sample_inventory_file, output_dir)
        pk_path = os.path.join(output_dir, "hub", "keys", "privatekey")
        mode = oct(os.stat(pk_path).st_mode)[-3:]
        assert mode == "600"

    def test_setup_scripts_are_executable(
        self, sample_inventory_file, output_dir
    ):
        generate_all(sample_inventory_file, output_dir)
        bridge_sh = os.path.join(output_dir, "hub", "setup-bridge.sh")
        assert os.access(bridge_sh, os.X_OK)

    def test_glinet_gets_glinet_script(
        self, sample_inventory_file, output_dir
    ):
        generate_all(sample_inventory_file, output_dir)
        script = open(
            os.path.join(output_dir, "site-01", "setup-gretap.sh")
        ).read()
        # GL.iNet script adds to br-lan
        assert "br-lan" in script

    def test_cradlepoint_gets_pi_script(
        self, sample_inventory_file, output_dir
    ):
        generate_all(sample_inventory_file, output_dir)
        script = open(
            os.path.join(output_dir, "site-02", "setup-gretap.sh")
        ).read()
        # Pi script creates br0 + bridges eth0
        assert "br0" in script
        assert "eth0" in script


class TestCli:
    def test_cli_runs_successfully(
        self, sample_inventory_file, output_dir
    ):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_configs.py",
                "--inventory",
                sample_inventory_file,
                "--output",
                output_dir,
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0
        assert os.path.isfile(os.path.join(output_dir, "hub", "wg0.conf"))

    def test_cli_fails_on_bad_inventory(self, output_dir):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_configs.py",
                "--inventory",
                "/nonexistent.yaml",
                "--output",
                output_dir,
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/test_cli.py -v`
Expected: ImportError — `generate_all` not found

- [ ] **Step 3: Implement orchestration and CLI**

Append to `scripts/generate_configs.py`:

```python
def _write_file(path: str, content: str, mode: int = 0o644) -> None:
    """Write content to file with given permissions."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)


def generate_all(inventory_path: str, output_dir: str) -> None:
    """Main orchestration: load inventory, generate all configs and keys."""
    inv = load_inventory(inventory_path)
    validate_inventory(inv)

    hub = inv["hub"]
    sites = inv["sites"]

    # Generate hub keys
    hub_private, hub_public = generate_keypair()
    hub_keys_dir = os.path.join(output_dir, "hub", "keys")
    _write_file(
        os.path.join(hub_keys_dir, "privatekey"), hub_private + "\n", 0o600
    )
    _write_file(os.path.join(hub_keys_dir, "publickey"), hub_public + "\n")

    # Generate per-site keys and collect metadata
    site_configs = []
    for site in sites:
        site_private, site_public = generate_keypair()
        psk = generate_psk()

        site_dir = os.path.join(output_dir, site["name"], "keys")
        _write_file(
            os.path.join(site_dir, "privatekey"), site_private + "\n", 0o600
        )
        _write_file(os.path.join(site_dir, "publickey"), site_public + "\n")
        _write_file(
            os.path.join(site_dir, "presharedkey"), psk + "\n", 0o600
        )

        site_configs.append({
            **site,
            "private_key": site_private,
            "public_key": site_public,
            "psk": psk,
        })

    # Generate hub WireGuard config
    hub_wg = generate_hub_wg_config(hub, site_configs, hub_private)
    _write_file(os.path.join(output_dir, "hub", "wg0.conf"), hub_wg, 0o600)

    # Generate hub bridge scripts
    mcast_nic = hub.get("mcast_nic", "eth1")
    bridge_script = generate_hub_bridge_script(
        hub["tunnel_ip"], site_configs, mcast_nic
    )
    _write_file(
        os.path.join(output_dir, "hub", "setup-bridge.sh"),
        bridge_script,
        0o755,
    )

    teardown_script = generate_hub_teardown_script(site_configs)
    _write_file(
        os.path.join(output_dir, "hub", "teardown-bridge.sh"),
        teardown_script,
        0o755,
    )

    # Generate per-site configs
    hub_meta = {**hub, "public_key": hub_public}
    for sc in site_configs:
        site_name = sc["name"]

        # WireGuard config
        site_wg = generate_site_wg_config(hub_meta, sc)
        _write_file(
            os.path.join(output_dir, site_name, "wg0.conf"),
            site_wg,
            0o600,
        )

        # GRETAP script (type-specific)
        if sc["type"] == "glinet":
            gretap = generate_glinet_gretap_script(
                sc["tunnel_ip"], hub["tunnel_ip"]
            )
        else:
            gretap = generate_pi_gretap_script(
                sc["tunnel_ip"], hub["tunnel_ip"]
            )

        _write_file(
            os.path.join(output_dir, site_name, "setup-gretap.sh"),
            gretap,
            0o755,
        )

    print(f"Generated configs for {len(site_configs)} sites in {output_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="wg-mcast config generator"
    )
    parser.add_argument(
        "--inventory",
        "-i",
        required=True,
        help="Path to sites.yaml inventory file",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output",
        help="Output directory (default: output/)",
    )
    args = parser.parse_args()

    try:
        generate_all(args.inventory, args.output)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd /Users/chrisvklein/wg-multicast && python -m pytest tests/ -v`
Expected: All tests PASS (inventory, keygen, wg_configs, gretap_scripts, cli)

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py scripts/generate_configs.py
git commit -m "feat: add CLI orchestration and end-to-end config generation"
```

---

### Task 6: Hub Setup Script

**Files:**
- Create: `scripts/hub-setup.sh`

- [ ] **Step 1: Write hub setup script**

Create `scripts/hub-setup.sh`:

```bash
#!/bin/bash
set -euo pipefail

# wg-mcast: Hub VM setup script
# Run on the Linux VM (Ubuntu Server 24.04 recommended).
# Usage: sudo ./hub-setup.sh <config-dir>
#   <config-dir> = path to generated hub config (output/hub/)

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

if [ ! -f "$CONFIG_DIR/wg0.conf" ]; then
    echo "Error: $CONFIG_DIR/wg0.conf not found" >&2
    exit 1
fi

echo "=== wg-mcast Hub Setup ==="

# --- Install dependencies ---
echo "[1/5] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools iproute2 bridge-utils

# --- Install WireGuard config ---
echo "[2/5] Configuring WireGuard..."
cp "$CONFIG_DIR/wg0.conf" /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Enable and start WireGuard
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# --- Install bridge setup scripts ---
echo "[3/5] Installing bridge scripts..."
cp "$CONFIG_DIR/setup-bridge.sh" /usr/local/bin/wg-mcast-bridge-up
cp "$CONFIG_DIR/teardown-bridge.sh" /usr/local/bin/wg-mcast-bridge-down
chmod 755 /usr/local/bin/wg-mcast-bridge-up /usr/local/bin/wg-mcast-bridge-down

# --- Create systemd service for bridge ---
echo "[4/5] Creating bridge systemd service..."
cat > /etc/systemd/system/wg-mcast-bridge.service << 'UNIT'
[Unit]
Description=wg-mcast GRETAP Bridge
After=wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/wg-mcast-bridge-up
ExecStop=/usr/local/bin/wg-mcast-bridge-down

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable wg-mcast-bridge
systemctl start wg-mcast-bridge

# --- Verify ---
echo "[5/5] Verifying..."
wg show wg0
bridge link show br-mcast 2>/dev/null || echo "Warning: bridge not yet active (peers may not be connected)"

echo ""
echo "=== Hub setup complete ==="
echo "WireGuard: systemctl status wg-quick@wg0"
echo "Bridge:    systemctl status wg-mcast-bridge"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/hub-setup.sh
git add scripts/hub-setup.sh
git commit -m "feat: add hub VM setup script with systemd services"
```

---

### Task 7: GL.iNet Setup Script

**Files:**
- Create: `scripts/glinet-setup.sh`

- [ ] **Step 1: Write GL.iNet setup script**

Create `scripts/glinet-setup.sh`:

```bash
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
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/glinet-setup.sh
git add scripts/glinet-setup.sh
git commit -m "feat: add GL.iNet (OpenWrt) setup script with UCI config"
```

---

### Task 8: Pi Setup Script

**Files:**
- Create: `scripts/pi-setup.sh`

- [ ] **Step 1: Write Raspberry Pi setup script**

Create `scripts/pi-setup.sh`:

```bash
#!/bin/bash
set -euo pipefail

# wg-mcast: Raspberry Pi sidecar setup script
# Run on the Pi at Cradlepoint sites.
# Usage: sudo ./pi-setup.sh <config-dir>
#   <config-dir> = path to generated site config (output/site-XX/)

CONFIG_DIR="${1:?Usage: $0 <config-dir>}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

if [ ! -f "$CONFIG_DIR/wg0.conf" ]; then
    echo "Error: $CONFIG_DIR/wg0.conf not found" >&2
    exit 1
fi

echo "=== wg-mcast Pi Sidecar Setup ==="

# --- Install dependencies ---
echo "[1/5] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools iproute2 bridge-utils

# --- Install WireGuard config ---
echo "[2/5] Configuring WireGuard..."
cp "$CONFIG_DIR/wg0.conf" /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

# Enable and start WireGuard
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# --- Install GRETAP setup script ---
echo "[3/5] Installing GRETAP script..."
cp "$CONFIG_DIR/setup-gretap.sh" /usr/local/bin/wg-mcast-gretap-up
chmod 755 /usr/local/bin/wg-mcast-gretap-up

# --- Create systemd service for GRETAP + bridge ---
echo "[4/5] Creating GRETAP systemd service..."
cat > /etc/systemd/system/wg-mcast-gretap.service << 'UNIT'
[Unit]
Description=wg-mcast GRETAP Bridge
After=wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/wg-mcast-gretap-up
ExecStop=/bin/sh -c "ip link del br0 2>/dev/null; ip link del gretap0 2>/dev/null"

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable wg-mcast-gretap
systemctl start wg-mcast-gretap

# --- Verify ---
echo "[5/5] Verifying..."
wg show wg0
ip link show gretap0 2>/dev/null || echo "Warning: GRETAP not yet active"
bridge link show br0 2>/dev/null || echo "Warning: bridge not yet active"

echo ""
echo "=== Pi sidecar setup complete ==="
echo "WireGuard: systemctl status wg-quick@wg0"
echo "GRETAP:    systemctl status wg-mcast-gretap"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/pi-setup.sh
git add scripts/pi-setup.sh
git commit -m "feat: add Raspberry Pi sidecar setup script with systemd"
```

---

### Task 9: Day-2 Operations Scripts

**Files:**
- Create: `scripts/add-site.sh`
- Create: `scripts/remove-site.sh`

- [ ] **Step 1: Write add-site script**

Create `scripts/add-site.sh`:

```bash
#!/bin/bash
set -euo pipefail

# wg-mcast: Add a new site to the inventory and regenerate configs.
# Usage: ./add-site.sh <name> <type> [wan_ip]
#   <name>    = site name (e.g., "site-05-west")
#   <type>    = "glinet" or "cradlepoint"
#   [wan_ip]  = WAN IP or "dynamic" (default: dynamic)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INVENTORY="${WG_MCAST_INVENTORY:-sites.yaml}"
OUTPUT_DIR="${WG_MCAST_OUTPUT:-output}"

NAME="${1:?Usage: $0 <name> <type> [wan_ip]}"
TYPE="${2:?Usage: $0 <name> <type> [wan_ip]}"
WAN_IP="${3:-dynamic}"

if [ "$TYPE" != "glinet" ] && [ "$TYPE" != "cradlepoint" ]; then
    echo "Error: type must be 'glinet' or 'cradlepoint'" >&2
    exit 1
fi

if [ ! -f "$INVENTORY" ]; then
    echo "Error: inventory file '$INVENTORY' not found" >&2
    echo "Set WG_MCAST_INVENTORY to override" >&2
    exit 1
fi

# Find next available tunnel IP
LAST_OCTET=$(python3 -c "
import yaml
with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)
octets = []
for s in inv.get('sites', []):
    parts = s['tunnel_ip'].split('.')
    octets.append(int(parts[2]))
print(max(octets) + 1 if octets else 1)
")

if [ "$LAST_OCTET" -gt 254 ]; then
    echo "Error: no available tunnel IPs (max 254 sites)" >&2
    exit 1
fi

TUNNEL_IP="172.27.${LAST_OCTET}.1"

echo "Adding site: $NAME"
echo "  Type:      $TYPE"
echo "  Tunnel IP: $TUNNEL_IP"
echo "  WAN IP:    $WAN_IP"

# Append to inventory
python3 -c "
import yaml

with open('$INVENTORY') as f:
    inv = yaml.safe_load(f)

inv['sites'].append({
    'name': '$NAME',
    'type': '$TYPE',
    'tunnel_ip': '$TUNNEL_IP',
    'wan_ip': '$WAN_IP',
    'description': ''
})

with open('$INVENTORY', 'w') as f:
    yaml.dump(inv, f, default_flow_style=False, sort_keys=False)
"

echo "Inventory updated. Regenerating configs..."
python3 "$SCRIPT_DIR/generate_configs.py" -i "$INVENTORY" -o "$OUTPUT_DIR"

echo ""
echo "Site '$NAME' added. Config at: $OUTPUT_DIR/$NAME/"
echo "Next steps:"
echo "  1. Copy $OUTPUT_DIR/$NAME/ to the remote device"
if [ "$TYPE" = "glinet" ]; then
    echo "  2. Run: ./glinet-setup.sh <config-dir>"
else
    echo "  2. Run: sudo ./pi-setup.sh <config-dir>"
fi
echo "  3. Update hub: sudo systemctl restart wg-quick@wg0 && sudo systemctl restart wg-mcast-bridge"
```

- [ ] **Step 2: Write remove-site script**

Create `scripts/remove-site.sh`:

```bash
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
```

- [ ] **Step 3: Make executable and commit**

```bash
chmod +x scripts/add-site.sh scripts/remove-site.sh
git add scripts/add-site.sh scripts/remove-site.sh
git commit -m "feat: add day-2 add-site and remove-site scripts"
```

---

### Task 10: Health Monitor

**Files:**
- Create: `scripts/health-check.sh`

- [ ] **Step 1: Write health check script**

Create `scripts/health-check.sh`:

```bash
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
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/health-check.sh
git add scripts/health-check.sh
git commit -m "feat: add hub health monitoring script with webhook alerts"
```

---

### Task 11: Setup Guide

**Files:**
- Create: `docs/setup-guide.md`

- [ ] **Step 1: Write setup guide**

Create `docs/setup-guide.md` covering:

1. **Prerequisites** — what you need before starting (hardware, software, network access)
2. **Step 1: Prepare site inventory** — copy `sites.yaml.example`, fill in site details
3. **Step 2: Generate configs** — run `generate_configs.py`, review output
4. **Step 3: Set up the hub VM** — create Hyper-V VM, configure vSwitch, run `hub-setup.sh`
5. **Step 4: Set up GL.iNet sites** — SCP configs, run `glinet-setup.sh`
6. **Step 5: Set up Cradlepoint/Pi sites** — flash Pi, SCP configs, run `pi-setup.sh`
7. **Step 6: Verify** — test multicast from hub to each site
8. **Step 7: Enable monitoring** — install health check cron
9. **Day-2: Adding/removing sites** — use `add-site.sh` / `remove-site.sh`
10. **Troubleshooting** — common issues (firewall, MTU, NAT traversal, GRETAP not coming up)

Note: the Hyper-V vSwitch creation (internal switch, VM NIC assignment) should be documented here as a manual step with screenshots/commands.

- [ ] **Step 2: Commit**

```bash
git add docs/setup-guide.md
git commit -m "docs: add step-by-step deployment and troubleshooting guide"
```

---

### Task 12: Final Integration & Cleanup

**Files:**
- Modify: `.gitignore` (verify completeness)
- Run all tests

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/chrisvklein/wg-multicast && python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 2: Run shellcheck on all shell scripts**

```bash
shellcheck scripts/hub-setup.sh scripts/glinet-setup.sh scripts/pi-setup.sh scripts/add-site.sh scripts/remove-site.sh scripts/health-check.sh
```

Fix any issues found.

- [ ] **Step 3: Verify output directory is gitignored**

```bash
mkdir -p output && touch output/test && git status
```

Expected: `output/test` does NOT appear in untracked files.

- [ ] **Step 4: Clean up and final commit**

```bash
rm -rf output/test
git add -A
git status
# If any remaining changes:
git commit -m "chore: final cleanup and integration verification"
```
