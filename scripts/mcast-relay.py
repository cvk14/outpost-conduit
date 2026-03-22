#!/usr/bin/env python3
"""Multicast relay for Outpost Conduit.

Relays multicast (mDNS 224.0.0.251:5353) between local LAN and the hub
via unicast UDP through the WireGuard tunnel. Replaces GRETAP for routers
with broken kernel GRE TX (e.g., GL.iNet SFT1200 on kernel 4.14).

Hub mode:  Listens on relay port, re-broadcasts received packets as multicast.
           Also captures local multicast and sends to all registered sites.
Site mode: Captures multicast on LAN, forwards as unicast to hub relay port.
           Also receives unicast from hub and re-broadcasts as multicast on LAN.

Usage:
  Hub:  python3 mcast-relay.py --mode hub --iface br-mcast --sites 172.27.2.1,172.27.3.1
  Site: python3 mcast-relay.py --mode site --iface br-lan --hub 172.27.0.1
"""

import argparse
import socket
import struct
import threading
import sys

MCAST_GROUP = "224.0.0.251"
MCAST_PORT = 5353
RELAY_PORT = 5350


def hub_mode(iface, site_ips):
    """Hub: relay between multicast on bridge and unicast to/from sites."""
    print(f"[hub] Relaying multicast on {iface} to sites: {site_ips}")

    # Socket for receiving unicast from sites
    relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    relay_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    relay_sock.bind(("0.0.0.0", RELAY_PORT))

    # Socket for sending/receiving multicast on the bridge
    mcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    mcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, iface.encode())
    mcast_sock.bind(("", MCAST_PORT))
    # Join multicast group
    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GROUP), socket.inet_aton("0.0.0.0"))
    mcast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    # Set multicast TTL
    mcast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 5)
    # Set outgoing multicast interface
    mcast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("0.0.0.0"))

    def relay_from_sites():
        """Receive unicast from sites, re-broadcast as multicast on bridge."""
        while True:
            try:
                data, addr = relay_sock.recvfrom(65535)
                mcast_sock.sendto(data, (MCAST_GROUP, MCAST_PORT))
            except Exception as e:
                print(f"[hub] relay_from_sites error: {e}", file=sys.stderr)

    def relay_to_sites():
        """Capture multicast on bridge, send as unicast to all sites."""
        while True:
            try:
                data, addr = mcast_sock.recvfrom(65535)
                src_ip = addr[0]
                # Don't relay packets that came from ourselves (avoid loops)
                if src_ip in site_ips:
                    continue
                for site_ip in site_ips:
                    try:
                        relay_sock.sendto(data, (site_ip, RELAY_PORT))
                    except Exception:
                        pass
            except Exception as e:
                print(f"[hub] relay_to_sites error: {e}", file=sys.stderr)

    t1 = threading.Thread(target=relay_from_sites, daemon=True)
    t2 = threading.Thread(target=relay_to_sites, daemon=True)
    t1.start()
    t2.start()
    print(f"[hub] Relay running (multicast {MCAST_GROUP}:{MCAST_PORT} <-> unicast :{RELAY_PORT})")
    t1.join()


def site_mode(iface, hub_ip):
    """Site: relay between local multicast and unicast to/from hub."""
    print(f"[site] Relaying multicast on {iface} to hub {hub_ip}:{RELAY_PORT}")

    # Socket for unicast to/from hub
    relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    relay_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    relay_sock.bind(("0.0.0.0", RELAY_PORT))

    # Socket for multicast on LAN
    mcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    mcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        mcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, iface.encode())
    except Exception:
        pass  # May not be supported on all platforms
    mcast_sock.bind(("", MCAST_PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GROUP), socket.inet_aton("0.0.0.0"))
    mcast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    mcast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 5)

    def relay_to_hub():
        """Capture local multicast, forward as unicast to hub."""
        while True:
            try:
                data, addr = mcast_sock.recvfrom(65535)
                relay_sock.sendto(data, (hub_ip, RELAY_PORT))
            except Exception as e:
                print(f"[site] relay_to_hub error: {e}", file=sys.stderr)

    def relay_from_hub():
        """Receive unicast from hub, re-broadcast as multicast on LAN."""
        while True:
            try:
                data, addr = relay_sock.recvfrom(65535)
                mcast_sock.sendto(data, (MCAST_GROUP, MCAST_PORT))
            except Exception as e:
                print(f"[site] relay_from_hub error: {e}", file=sys.stderr)

    t1 = threading.Thread(target=relay_to_hub, daemon=True)
    t2 = threading.Thread(target=relay_from_hub, daemon=True)
    t1.start()
    t2.start()
    print(f"[site] Relay running (multicast {MCAST_GROUP}:{MCAST_PORT} <-> unicast {hub_ip}:{RELAY_PORT})")
    t1.join()


def main():
    parser = argparse.ArgumentParser(description="Outpost Conduit multicast relay")
    parser.add_argument("--mode", required=True, choices=["hub", "site"])
    parser.add_argument("--iface", required=True, help="Network interface (br-mcast for hub, br-lan for site)")
    parser.add_argument("--hub", help="Hub tunnel IP (site mode only)")
    parser.add_argument("--sites", help="Comma-separated site tunnel IPs (hub mode only)")
    args = parser.parse_args()

    if args.mode == "hub":
        if not args.sites:
            print("Error: --sites required in hub mode", file=sys.stderr)
            sys.exit(1)
        site_ips = [s.strip() for s in args.sites.split(",")]
        hub_mode(args.iface, site_ips)
    else:
        if not args.hub:
            print("Error: --hub required in site mode", file=sys.stderr)
            sys.exit(1)
        site_mode(args.iface, args.hub)


if __name__ == "__main__":
    main()
