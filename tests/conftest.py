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
