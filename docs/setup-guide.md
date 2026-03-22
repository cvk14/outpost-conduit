# wg-mcast Deployment Guide

Tunnels IP multicast over WireGuard using GRETAP Layer 2 overlays.

## Architecture

```
Windows 11 Host (Motorola Radio Management)
  └── Hyper-V Ubuntu VM  ← WireGuard hub (wg0 172.27.0.1)
        ├── br-mcast bridge  ← GRETAP + multicast NIC
        ├── gretap-site01 → site-01 (172.27.1.1)
        ├── gretap-site02 → site-02 (172.27.2.1)
        └── ...

Remote site – GL.iNet/OpenWrt:
  Router (wg0 172.27.N.1) → gretap0 → br-lan (native LAN bridge)

Remote site – Cradlepoint:
  Cradlepoint (WAN only) → Pi sidecar (wg0 172.27.N.1) → gretap0 → br0 → eth0 (LAN)
```

**Tunnel network:** 172.27.0.0/16
**MTU chain:** WAN 1500 → WireGuard 1420 → GRETAP/bridge 1380

---

## Prerequisites

**Hardware**
- Hub: Windows 11 Pro machine with Hyper-V enabled
- Remote GL.iNet sites: GL.iNet router running OpenWrt
- Remote Cradlepoint sites: Raspberry Pi (any model with 2 Ethernet ports or a USB NIC)

**Software (on the machine running the generator)**
- Python 3.8+
- `wireguard-tools` (`wg` and `wg-genkey` must be in PATH)
- PyYAML: `pip3 install pyyaml`

**Network**
- Hub WAN IP must be reachable from all remote sites on UDP port 51820
- Remote sites with static WAN IPs connect faster; dynamic sites rely on `PersistentKeepalive`

---

## Step 1: Prepare Site Inventory

Copy the example inventory and edit it:

```bash
cp sites.yaml.example sites.yaml
```

Edit `sites.yaml`:

```yaml
hub:
  wan_ip: "203.0.113.10"      # Hub's public IP or DDNS hostname
  tunnel_ip: "172.27.0.1"
  listen_port: 51820
  # mcast_nic: "eth1"         # VM NIC connected to multicast VLAN (default: eth1)

sites:
  - name: "site-01-downtown"
    type: "glinet"             # "glinet" or "cradlepoint"
    tunnel_ip: "172.27.1.1"   # Unique per site; format 172.27.N.1
    wan_ip: "198.51.100.1"    # Static WAN IP, or "dynamic" for NAT/DHCP
    description: "Downtown GL.iNet"

  - name: "site-02-airport"
    type: "cradlepoint"
    tunnel_ip: "172.27.2.1"
    wan_ip: "dynamic"
    description: "Airport Cradlepoint + Pi"
```

Rules:
- Each `name` must be unique.
- Each `tunnel_ip` must be unique and follow the `172.27.N.1` convention.
- Use `"dynamic"` for `wan_ip` when the site is behind NAT or DHCP.

---

## Step 2: Generate Configs

```bash
python3 scripts/generate_configs.py -i sites.yaml -o output/
```

Output structure:

```
output/
  hub/
    wg0.conf           # Hub WireGuard config (all peers)
    setup-bridge.sh    # Creates br-mcast + all GRETAP tunnels
    teardown-bridge.sh # Tears down bridge and tunnels
    keys/
      privatekey       # Hub WireGuard private key (mode 600)
      publickey
  site-01-downtown/
    wg0.conf           # Site WireGuard config
    setup-gretap.sh    # Creates gretap0 + bridge
    keys/
      privatekey       # Site private key (mode 600)
      publickey
      presharedkey     # Per-site PSK (mode 600)
  site-02-airport/
    ...
```

Keys are generated once and preserved on subsequent runs — re-running to add sites does not rotate existing keys.

---

## Step 3: Set Up the Hub VM

### 3a. Create the Hyper-V VM

On the Windows 11 host, open an elevated PowerShell prompt.

**Create an internal vSwitch for the multicast application:**

```powershell
New-VMSwitch -Name "mcast-internal" -SwitchType Internal
```

**Create the VM** (adjust paths and memory as needed):

```powershell
New-VM -Name "wg-mcast-hub" `
    -Generation 2 `
    -MemoryStartupBytes 2GB `
    -SwitchName "Default Switch"   # Management NIC (internet access)

Add-VMNetworkAdapter -VMName "wg-mcast-hub" -SwitchName "mcast-internal"

# Attach your Ubuntu Server ISO
Add-VMDvdDrive -VMName "wg-mcast-hub" -Path "C:\ISOs\ubuntu-24.04-server.iso"
Set-VMFirmware -VMName "wg-mcast-hub" -FirstBootDevice (Get-VMDvdDrive -VMName "wg-mcast-hub")
```

The VM will have two NICs:
- `eth0` — management / internet (Default Switch)
- `eth1` — multicast internal (mcast-internal vSwitch); this is `mcast_nic` in `sites.yaml`

### 3b. Install Ubuntu Server

Boot the VM, install Ubuntu Server 24.04 LTS. Enable SSH during setup for remote access.

### 3c. Deploy Hub Config

From your workstation, copy the generated hub config to the VM:

```bash
scp -r output/hub/ user@<hub-vm-ip>:/tmp/hub-config/
```

On the VM:

```bash
sudo ./hub-setup.sh /tmp/hub-config/
```

The script:
1. Installs `wireguard`, `iproute2`, `bridge-utils`
2. Installs `wg0.conf` → `/etc/wireguard/wg0.conf` and enables `wg-quick@wg0`
3. Installs `setup-bridge.sh` / `teardown-bridge.sh` to `/usr/local/bin/`
4. Creates and starts the `wg-mcast-bridge` systemd service (depends on `wg-quick@wg0`)

Verify:

```bash
sudo systemctl status wg-quick@wg0
sudo systemctl status wg-mcast-bridge
sudo wg show
bridge link show br-mcast
```

---

## Step 4: Set Up GL.iNet Sites

Copy the site config to the router (default GL.iNet SSH is `root@192.168.8.1`):

```bash
scp -r output/site-01-downtown/ root@192.168.8.1:/tmp/site-config/
```

On the router:

```bash
./glinet-setup.sh /tmp/site-config/
```

The script:
1. Installs WireGuard via `opkg` if not already present
2. Configures the WireGuard interface (`wgmcast`) and firewall rules via UCI
3. Installs `setup-gretap.sh` as `/usr/local/bin/wg-mcast-gretap-up`
4. Creates and enables the `/etc/init.d/wg-mcast-gretap` init script (starts at boot, after WireGuard)
5. Adds `gretap0` to the existing `br-lan` bridge so multicast traffic joins the LAN

Verify on the router:

```bash
wg show
ip link show gretap0
bridge link show
```

---

## Step 5: Set Up Cradlepoint/Pi Sites

### 5a. Prepare the Pi

Flash a Raspberry Pi with **Raspberry Pi OS Lite** (64-bit). Enable SSH:

```bash
# On the SD card boot partition
touch ssh
```

Connect the Pi's `eth0` to the Cradlepoint LAN. The Cradlepoint handles WAN routing; the Pi handles the WireGuard/GRETAP overlay.

### 5b. Deploy Pi Config

```bash
scp -r output/site-02-airport/ pi@<pi-ip>:/tmp/site-config/
```

On the Pi:

```bash
sudo ./pi-setup.sh /tmp/site-config/
```

The script:
1. Installs `wireguard`, `iproute2`, `bridge-utils`
2. Installs `wg0.conf` and enables `wg-quick@wg0`
3. Installs `setup-gretap.sh` as `/usr/local/bin/wg-mcast-gretap-up`
4. Creates and starts the `wg-mcast-gretap` systemd service (depends on `wg-quick@wg0`, waits 5s before bringing up GRETAP)
5. Creates `gretap0` and bridge `br0`, then enslaves both `gretap0` and `eth0` to `br0`

Verify on the Pi:

```bash
sudo systemctl status wg-quick@wg0
sudo systemctl status wg-mcast-gretap
sudo wg show
ip link show gretap0
bridge link show br0
```

---

## Step 6: Verify End-to-End

### WireGuard connectivity

On the hub VM:

```bash
sudo wg show
```

Each remote site should show a recent handshake under its peer entry. A handshake timestamp older than ~3 minutes indicates the peer is not maintaining connectivity.

### GRETAP / bridge connectivity

Ping across the overlay using tunnel IPs:

```bash
# From hub VM — ping site tunnel IPs
ping 172.27.1.1    # site-01
ping 172.27.2.1    # site-02
```

### Multicast

Use `socat` for a quick multicast smoke test. On the hub VM (or any bridged host):

```bash
# Listener
socat UDP4-RECVFROM:5007,ip-add-membership=239.1.1.1:eth1,fork -

# Sender (from a remote site or Motorola RM host)
echo "multicast test" | socat - UDP4-DATAGRAM:239.1.1.1:5007,ip-multicast-ttl=5
```

If the listener receives the packet, the Layer 2 overlay is working.

---

## Step 7: Enable Monitoring

Copy the health-check script to the hub VM:

```bash
scp scripts/health-check.sh user@<hub-vm-ip>:/tmp/
ssh user@<hub-vm-ip> sudo cp /tmp/health-check.sh /usr/local/bin/wg-mcast-health-check
ssh user@<hub-vm-ip> sudo chmod 755 /usr/local/bin/wg-mcast-health-check
```

Install as a cron job (runs every 5 minutes):

```bash
sudo crontab -e
```

Add:

```
*/5 * * * * /usr/local/bin/wg-mcast-health-check >> /var/log/wg-mcast-health.log 2>&1
```

**Optional webhook alerts** (Slack, Teams, or any HTTP endpoint):

```bash
# Add to /etc/environment or the cron environment
WG_MCAST_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

The health check alerts when:
- The `wg0` interface is down
- The `br-mcast` bridge is down
- Any peer has not completed a handshake in the last 5 minutes
- The bridge has no ports

---

## Day-2: Adding and Removing Sites

### Add a site

```bash
./scripts/add-site.sh site-03-stadium glinet 198.51.100.50
# or for a dynamic NAT site:
./scripts/add-site.sh site-04-venue cradlepoint dynamic
```

The script appends the site to `sites.yaml`, auto-assigns the next available tunnel IP, and regenerates all configs (existing keys are preserved).

Deploy the new site config (Steps 4 or 5), then restart the hub to pick up the new peer:

```bash
sudo systemctl restart wg-quick@wg0
sudo systemctl restart wg-mcast-bridge
```

### Remove a site

```bash
./scripts/remove-site.sh site-03-stadium
```

The script removes the site from `sites.yaml`, deletes `output/site-03-stadium/`, and regenerates the hub config. Then restart hub services as above, and decommission the remote device.

---

## Troubleshooting

### Firewall blocking UDP 51820

Remote sites cannot establish a handshake if the hub's WAN firewall blocks UDP 51820.

```bash
# Verify from a remote site
nc -u -z -w3 <hub-wan-ip> 51820 && echo "open" || echo "blocked"
```

Open the port on the hub's host firewall and/or upstream router/firewall.

### MTU problems / fragmentation

Symptom: WireGuard handshakes succeed but large packets are dropped; GRETAP traffic unreliable.

The expected MTU chain is: WAN 1500 → WireGuard 1420 → GRETAP/bridge 1380.

Check effective MTUs:

```bash
ip link show wg0       # should be 1420
ip link show gretap0   # should be 1380
ip link show br-mcast  # should be 1380
```

If your WAN path has an MTU below 1500 (common on PPPoE links, ~1492), lower WireGuard MTU in `wg0.conf` and reduce GRETAP MTU accordingly. Regenerate and redeploy.

Test with a large ping (no fragmentation):

```bash
ping -M do -s 1350 172.27.1.1
```

### NAT traversal (dynamic WAN sites)

Sites configured with `wan_ip: "dynamic"` rely on `PersistentKeepalive = 25` to maintain NAT mappings. If a dynamic site loses connectivity after idle periods, verify keepalives are active:

```bash
sudo wg show wg0   # "persistent keepalive" should appear in the peer entry
```

If the Cradlepoint NAT times out in under 25 seconds, lower the keepalive in `generate_configs.py` (the `PersistentKeepalive` value in `generate_site_wg_config` and `generate_hub_wg_config`), then regenerate and redeploy.

### GRETAP not coming up

GRETAP tunnels route traffic through the WireGuard tunnel (`172.27.0.0/16`). If WireGuard is not established, `ip link set gretap0 up` will succeed but packets will be dropped.

Check order of operations:

```bash
# Hub
sudo wg show wg0                   # Verify peer handshakes first
sudo systemctl status wg-mcast-bridge

# GL.iNet
wg show
ip link show gretap0

# Pi
sudo systemctl status wg-quick@wg0
sudo systemctl status wg-mcast-gretap
```

The Pi's `wg-mcast-gretap` service has a 5-second startup delay (`ExecStartPre=/bin/sleep 5`) to allow WireGuard to complete its first handshake. If the tunnel is slow to connect, manually restart after WireGuard is established:

```bash
sudo systemctl restart wg-mcast-gretap
```

### Bridge not forwarding (STP convergence)

The hub bridge (`br-mcast`) runs Spanning Tree Protocol. STP takes approximately 30 seconds to converge after the bridge or a port comes up. During this time, traffic will not forward even though interfaces appear UP.

```bash
bridge link show br-mcast   # Check port state: "learning" → "forwarding"
```

Wait ~30 seconds after `wg-mcast-bridge` starts before expecting multicast traffic to pass. If STP is not needed (no redundant links), it can be disabled by removing `ip link set br-mcast type bridge stp_state 1` from the generated `setup-bridge.sh`, then redeploying.
