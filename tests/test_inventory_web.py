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
        assert inv["hub"]["wan_ip"] == "1.2.3.4"
        assert len(inv["sites"]) == 1

    def test_get_sites(self, inv_manager):
        sites = inv_manager.get_sites()
        assert len(sites) == 1
        assert sites[0]["name"] == "site-01"

    def test_get_site_by_name(self, inv_manager):
        site = inv_manager.get_site("site-01")
        assert site is not None
        assert site["tunnel_ip"] == "172.27.1.1"

    def test_get_missing_site_returns_none(self, inv_manager):
        assert inv_manager.get_site("no-such-site") is None


class TestWrite:
    def test_add_site(self, inv_manager):
        new_site = {"name": "site-02", "type": "glinet", "tunnel_ip": "172.27.2.1", "wan_ip": "dynamic"}
        inv_manager.add_site(new_site)
        assert len(inv_manager.get_sites()) == 2
        assert inv_manager.get_site("site-02")["tunnel_ip"] == "172.27.2.1"

    def test_add_duplicate_raises(self, inv_manager):
        dup = {"name": "site-01", "type": "glinet", "tunnel_ip": "172.27.9.1", "wan_ip": "dynamic"}
        with pytest.raises(ValueError, match="exists"):
            inv_manager.add_site(dup)

    def test_update_site(self, inv_manager):
        inv_manager.update_site("site-01", {"wan_ip": "5.6.7.8"})
        site = inv_manager.get_site("site-01")
        assert site["wan_ip"] == "5.6.7.8"

    def test_update_nonexistent_raises(self, inv_manager):
        with pytest.raises(ValueError, match="not found"):
            inv_manager.update_site("ghost", {"wan_ip": "0.0.0.0"})

    def test_delete_site(self, inv_manager):
        inv_manager.delete_site("site-01")
        assert inv_manager.get_sites() == []

    def test_delete_nonexistent_raises(self, inv_manager):
        with pytest.raises(ValueError, match="not found"):
            inv_manager.delete_site("ghost")

    def test_atomic_write(self, inv_manager):
        new_site = {"name": "site-02", "type": "glinet", "tunnel_ip": "172.27.2.1", "wan_ip": "dynamic"}
        inv_manager.add_site(new_site)
        # Read file directly to confirm it was persisted
        with open(inv_manager.path) as f:
            data = yaml.safe_load(f)
        assert len(data["sites"]) == 2

    def test_next_tunnel_ip(self, inv_manager):
        # site-01 uses 172.27.1.1, so next available should be 172.27.2.1
        assert inv_manager.next_tunnel_ip() == "172.27.2.1"
