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
            {"name": "s1", "tunnel_ip": "172.27.1.1", "wan_ip": "1.2.3.4", "public_key": "PUB1=", "psk": "PSK1="},
            {"name": "s2", "tunnel_ip": "172.27.2.1", "wan_ip": "dynamic", "public_key": "PUB2=", "psk": "PSK2="},
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
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1", "wan_ip": "1.2.3.4", "public_key": "PUB=", "psk": "PSK="}]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "Endpoint = 1.2.3.4:51820" in config

    def test_dynamic_endpoint_omitted(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1", "wan_ip": "dynamic", "public_key": "PUB=", "psk": "PSK="}]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "Endpoint" not in config

    def test_persistent_keepalive_on_all_peers(self):
        hub = {"tunnel_ip": "172.27.0.1", "listen_port": 51820}
        sites = [{"name": "s1", "tunnel_ip": "172.27.1.1", "wan_ip": "1.2.3.4", "public_key": "PUB=", "psk": "PSK="}]
        config = generate_hub_wg_config(hub, sites, "PK=")
        assert "PersistentKeepalive = 25" in config


class TestSiteWgConfig:
    def test_site_config_structure(self):
        hub = {"wan_ip": "203.0.113.10", "tunnel_ip": "172.27.0.1", "listen_port": 51820, "public_key": "HUBPUB="}
        site = {"name": "site-01", "tunnel_ip": "172.27.1.1", "private_key": "SITEPK=", "psk": "PSK="}
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
        hub = {"wan_ip": "203.0.113.10", "tunnel_ip": "172.27.0.1", "listen_port": 51820, "public_key": "HUBPUB="}
        site = {"name": "s1", "tunnel_ip": "172.27.1.1", "private_key": "PK=", "psk": "PSK="}
        config = generate_site_wg_config(hub, site)
        assert "MTU = 1420" in config
