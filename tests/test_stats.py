"""Tests for web.stats — WireGuard + bridge parsers and stats collector."""

import time

import pytest

from web.stats import merge_stats, parse_bridge_stats, parse_ip_link_stats, parse_wg_dump

# ---------------------------------------------------------------------------
# Real command output fixtures
# ---------------------------------------------------------------------------

# Real output from `wg show wg0 dump`
WG_DUMP = (
    "wg0\tPRIVKEY=\t51820\toff\n"
    "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI=\tPSK=\t198.51.100.1:51820"
    "\t172.27.1.1/32\t1711900000\t142300000\t89700000\t25"
)

# Real output from `bridge link show br-mcast` (no -s, stats come from ip -s link)
BRIDGE_STATS = (
    "3: ens19: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master br-mcast"
    " state forwarding priority 32 cost 100\n"
    "16: gretap-test-sit@NONE: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1380"
    " master br-mcast state forwarding priority 32 cost 100"
)

# Real output from `ip -s link show ens19`
IP_LINK_STATS = (
    "3: ens19: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel master br-mcast state UP\n"
    "    link/ether bc:24:11:26:44:5d brd ff:ff:ff:ff:ff:ff\n"
    "    RX:  bytes packets errors dropped  missed   mcast\n"
    "    890000000 1200000 0       0       0       0\n"
    "    TX:  bytes packets errors dropped carrier collsns\n"
    "    1200000000 1500000 0      0       0       0"
)


# ---------------------------------------------------------------------------
# TestParseWgDump
# ---------------------------------------------------------------------------
class TestParseWgDump:
    """Tests for parse_wg_dump()."""

    def test_parses_peer(self):
        peers = parse_wg_dump(WG_DUMP)
        assert len(peers) == 1
        peer = peers[0]
        assert peer["public_key"] == "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI="
        assert peer["endpoint"] == "198.51.100.1:51820"
        assert peer["allowed_ips"] == "172.27.1.1/32"
        assert peer["tx_bytes"] == 142300000
        assert peer["rx_bytes"] == 89700000
        assert peer["last_handshake"] == 1711900000

    def test_empty_dump(self):
        peers = parse_wg_dump("")
        assert peers == []

    def test_skips_interface_line(self):
        # Interface line has exactly 4 fields; should not appear as a peer.
        peers = parse_wg_dump(WG_DUMP)
        for peer in peers:
            assert peer["public_key"] != "wg0"


# ---------------------------------------------------------------------------
# TestParseBridgeStats
# ---------------------------------------------------------------------------
class TestParseBridgeStats:
    """Tests for parse_bridge_stats()."""

    def test_parses_ports(self):
        ports = parse_bridge_stats(BRIDGE_STATS)
        assert len(ports) == 2
        assert ports[0]["name"] == "ens19"
        assert ports[0]["state"] == "forwarding"

    def test_parses_gretap_port(self):
        ports = parse_bridge_stats(BRIDGE_STATS)
        gretap = ports[1]
        assert gretap["name"] == "gretap-test-sit"
        assert gretap["state"] == "forwarding"


class TestParseIpLinkStats:
    """Tests for parse_ip_link_stats()."""

    def test_parses_rx_tx(self):
        stats = parse_ip_link_stats(IP_LINK_STATS)
        assert stats["rx_bytes"] == 890000000
        assert stats["rx_packets"] == 1200000
        assert stats["tx_bytes"] == 1200000000
        assert stats["tx_packets"] == 1500000

    def test_empty_output(self):
        stats = parse_ip_link_stats("")
        assert stats["rx_bytes"] == 0
        assert stats["tx_bytes"] == 0


# ---------------------------------------------------------------------------
# TestMergeStats
# ---------------------------------------------------------------------------
class TestMergeStats:
    """Tests for merge_stats()."""

    def test_merges_peer_with_site(self):
        sites = [
            {
                "name": "test-site",
                "public_key": "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI=",
                "tunnel_ip": "172.27.1.1",
            }
        ]
        peers = parse_wg_dump(WG_DUMP)
        result = merge_stats(sites, peers, [])
        site = result["sites"][0]
        assert site["status"] in ("online", "stale", "offline")

    def test_includes_bridge_ports(self):
        ports = parse_bridge_stats(BRIDGE_STATS)
        result = merge_stats([], [], ports)
        assert result["bridge_ports"] == ports
        assert len(result["bridge_ports"]) == 2

    def test_includes_summary(self):
        sites = [
            {
                "name": "test-site",
                "public_key": "BBzylEIxlYsToTk8P2JlaRz3AfJNRVQ/ScvJiFAzITI=",
                "tunnel_ip": "172.27.1.1",
            },
            {
                "name": "offline-site",
                "public_key": "UNKNOWN_KEY",
                "tunnel_ip": "172.27.2.1",
            },
        ]
        peers = parse_wg_dump(WG_DUMP)
        result = merge_stats(sites, peers, [])
        summary = result["summary"]
        assert "total" in summary
        assert "online" in summary
        assert summary["total"] == 2
        # The test-site peer handshake is in the past, so it's stale/offline;
        # the offline-site has no matching peer, so it's offline.
        assert summary["online"] + summary["stale"] + summary["offline"] == 2
