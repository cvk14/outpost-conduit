import os
import sys
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_configs import generate_all


class TestGenerateAll:
    def test_creates_output_directory_structure(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        assert os.path.isdir(os.path.join(output_dir, "hub"))
        assert os.path.isfile(os.path.join(output_dir, "hub", "wg0.conf"))
        assert os.path.isfile(os.path.join(output_dir, "hub", "setup-bridge.sh"))
        assert os.path.isfile(os.path.join(output_dir, "hub", "teardown-bridge.sh"))
        assert os.path.isdir(os.path.join(output_dir, "site-01"))
        assert os.path.isfile(os.path.join(output_dir, "site-01", "wg0.conf"))
        assert os.path.isfile(os.path.join(output_dir, "site-01", "setup-gretap.sh"))
        assert os.path.isdir(os.path.join(output_dir, "site-02"))

    def test_creates_key_files(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        assert os.path.isfile(os.path.join(output_dir, "hub", "keys", "privatekey"))
        assert os.path.isfile(os.path.join(output_dir, "hub", "keys", "publickey"))
        for site_name in ["site-01", "site-02"]:
            keys_dir = os.path.join(output_dir, site_name, "keys")
            assert os.path.isfile(os.path.join(keys_dir, "privatekey"))
            assert os.path.isfile(os.path.join(keys_dir, "publickey"))
            assert os.path.isfile(os.path.join(keys_dir, "presharedkey"))

    def test_key_files_have_restricted_permissions(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        pk_path = os.path.join(output_dir, "hub", "keys", "privatekey")
        mode = oct(os.stat(pk_path).st_mode)[-3:]
        assert mode == "600"

    def test_setup_scripts_are_executable(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        bridge_sh = os.path.join(output_dir, "hub", "setup-bridge.sh")
        assert os.access(bridge_sh, os.X_OK)

    def test_glinet_gets_glinet_script(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        script = open(os.path.join(output_dir, "site-01", "setup-gretap.sh")).read()
        assert "br-lan" in script

    def test_cradlepoint_gets_pi_script(self, sample_inventory_file, output_dir):
        generate_all(sample_inventory_file, output_dir)
        script = open(os.path.join(output_dir, "site-02", "setup-gretap.sh")).read()
        assert "br0" in script
        assert "eth0" in script

    def test_preserves_existing_keys(self, sample_inventory_file, output_dir):
        """Running generate_all twice should NOT regenerate existing keys."""
        generate_all(sample_inventory_file, output_dir)
        # Read keys from first run
        hub_pk1 = open(os.path.join(output_dir, "hub", "keys", "privatekey")).read()
        site_pk1 = open(os.path.join(output_dir, "site-01", "keys", "privatekey")).read()
        # Run again
        generate_all(sample_inventory_file, output_dir)
        hub_pk2 = open(os.path.join(output_dir, "hub", "keys", "privatekey")).read()
        site_pk2 = open(os.path.join(output_dir, "site-01", "keys", "privatekey")).read()
        assert hub_pk1 == hub_pk2
        assert site_pk1 == site_pk2


class TestCli:
    def test_cli_runs_successfully(self, sample_inventory_file, output_dir):
        result = subprocess.run(
            [sys.executable, "scripts/generate_configs.py", "--inventory", sample_inventory_file, "--output", output_dir],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode == 0
        assert os.path.isfile(os.path.join(output_dir, "hub", "wg0.conf"))

    def test_cli_fails_on_bad_inventory(self, output_dir):
        result = subprocess.run(
            [sys.executable, "scripts/generate_configs.py", "--inventory", "/nonexistent.yaml", "--output", output_dir],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        assert result.returncode != 0
