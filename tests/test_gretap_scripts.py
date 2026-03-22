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
        assert "gretap-s1" in script
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
        assert "gretap-s1" in script


class TestGlinetGretapScript:
    def test_creates_gretap_and_bridges_to_br_lan(self):
        script = generate_glinet_gretap_script("172.27.1.1", "172.27.0.1")
        assert "gretap" in script
        assert "local 172.27.1.1" in script
        assert "remote 172.27.0.1" in script
        assert "br-lan" in script
        assert "mtu 1380" in script

    def test_uses_ip_link_add(self):
        script = generate_glinet_gretap_script("172.27.1.1", "172.27.0.1")
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
