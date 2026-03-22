"""Tests for web.ssh_manager — SSH config, command lookup, and SSH operations."""

import pytest

from web.ssh_manager import COMMANDS, _ssh_config, get_command


# ---------------------------------------------------------------------------
# _ssh_config
# ---------------------------------------------------------------------------

class TestSSHConfig:
    """Tests for _ssh_config()."""

    def test_defaults_glinet(self):
        site = {"type": "glinet", "tunnel_ip": "172.27.1.1"}
        cfg = _ssh_config(site)
        assert cfg["host"] == "172.27.1.1"
        assert cfg["username"] == "root"
        assert "id_ed25519" in cfg["client_keys"][0]
        assert cfg["known_hosts"] is None

    def test_defaults_cradlepoint(self):
        site = {"type": "cradlepoint", "tunnel_ip": "172.27.2.1"}
        cfg = _ssh_config(site)
        assert cfg["host"] == "172.27.2.1"
        assert cfg["username"] == "pi"

    def test_ssh_section_overrides(self):
        site = {
            "type": "glinet",
            "tunnel_ip": "172.27.1.1",
            "ssh": {
                "host": "10.0.0.99",
                "user": "admin",
                "key": "/custom/key",
            },
        }
        cfg = _ssh_config(site)
        assert cfg["host"] == "10.0.0.99"
        assert cfg["username"] == "admin"
        assert cfg["client_keys"] == ["/custom/key"]

    def test_partial_ssh_override(self):
        """Only overridden fields change; others keep defaults."""
        site = {
            "type": "cradlepoint",
            "tunnel_ip": "172.27.3.1",
            "ssh": {"host": "10.0.0.50"},
        }
        cfg = _ssh_config(site)
        assert cfg["host"] == "10.0.0.50"
        assert cfg["username"] == "pi"  # default for cradlepoint

    def test_missing_tunnel_ip_fallback(self):
        """When tunnel_ip is missing and ssh.host is not set, fall back to 127.0.0.1."""
        site = {"type": "glinet"}
        cfg = _ssh_config(site)
        assert cfg["host"] == "127.0.0.1"

    def test_unknown_type_defaults_to_root(self):
        site = {"type": "unknown", "tunnel_ip": "10.0.0.1"}
        cfg = _ssh_config(site)
        assert cfg["username"] == "root"


# ---------------------------------------------------------------------------
# get_command
# ---------------------------------------------------------------------------

class TestGetCommand:
    """Tests for get_command()."""

    def test_glinet_status(self):
        cmd = get_command("glinet", "status")
        assert "wg show" in cmd

    def test_glinet_restart(self):
        cmd = get_command("glinet", "restart")
        assert "wg-mcast-gretap" in cmd

    def test_glinet_reboot(self):
        assert get_command("glinet", "reboot") == "reboot"

    def test_cradlepoint_status(self):
        cmd = get_command("cradlepoint", "status")
        assert "wg show" in cmd

    def test_cradlepoint_restart(self):
        cmd = get_command("cradlepoint", "restart")
        assert "systemctl restart" in cmd

    def test_cradlepoint_reboot(self):
        assert get_command("cradlepoint", "reboot") == "sudo reboot"

    def test_invalid_type_raises(self):
        with pytest.raises(KeyError):
            get_command("nonexistent", "status")

    def test_invalid_action_raises(self):
        with pytest.raises(KeyError):
            get_command("glinet", "nonexistent")


# ---------------------------------------------------------------------------
# COMMANDS dict completeness
# ---------------------------------------------------------------------------

class TestCommandsDict:
    """Verify the COMMANDS dict is well-formed."""

    def test_all_types_have_all_actions(self):
        expected_actions = {"status", "restart", "reboot"}
        for site_type, actions in COMMANDS.items():
            assert set(actions.keys()) == expected_actions, (
                f"COMMANDS['{site_type}'] missing actions"
            )

    def test_all_values_are_strings(self):
        for site_type, actions in COMMANDS.items():
            for action, cmd in actions.items():
                assert isinstance(cmd, str), (
                    f"COMMANDS['{site_type}']['{action}'] is not a string"
                )
