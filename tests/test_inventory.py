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
        with pytest.raises(ValueError, match="(?i)duplicate"):
            validate_inventory(sample_inventory)

    def test_duplicate_site_name_raises(self, sample_inventory):
        sample_inventory["sites"][1]["name"] = "site-01"
        with pytest.raises(ValueError, match="(?i)duplicate"):
            validate_inventory(sample_inventory)

    def test_no_sites_raises(self, sample_inventory):
        sample_inventory["sites"] = []
        with pytest.raises(ValueError, match="sites"):
            validate_inventory(sample_inventory)
