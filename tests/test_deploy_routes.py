"""Tests for web.routes.deploy_routes — deploy REST + SSH WebSocket routes.

All SSH operations are mocked so no real SSH connections are made.
Uses Starlette's synchronous TestClient to avoid async fixture issues.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from starlette.testclient import TestClient

from web.auth import create_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def site_inventory(tmp_path):
    """Write a minimal inventory file and return its path."""
    inv = {
        "hub": {"wan_ip": "1.2.3.4", "tunnel_ip": "172.27.0.1", "listen_port": 51820},
        "sites": [
            {
                "name": "site-gl",
                "type": "glinet",
                "tunnel_ip": "172.27.1.1",
                "wan_ip": "198.51.100.1",
            },
            {
                "name": "site-cp",
                "type": "cradlepoint",
                "tunnel_ip": "172.27.2.1",
                "wan_ip": "dynamic",
            },
        ],
    }
    path = tmp_path / "sites.yaml"
    path.write_text(yaml.dump(inv))
    return str(path)


@pytest.fixture
def output_dir_with_configs(tmp_path):
    """Create an output directory with fake generated configs for site-gl."""
    out = tmp_path / "output"
    site_dir = out / "site-gl"
    site_dir.mkdir(parents=True)
    (site_dir / "wg0.conf").write_text("[Interface]\n# dummy")
    return str(out)


@pytest.fixture
def app_env(site_inventory, output_dir_with_configs, monkeypatch):
    """Set env vars so the FastAPI app lifespan configures correctly."""
    pw_hash = hash_password("testpass")
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", pw_hash)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("INVENTORY_PATH", site_inventory)
    monkeypatch.setenv("OUTPUT_DIR", output_dir_with_configs)
    return {"jwt_secret": "test-secret"}


@pytest.fixture
def auth_headers(app_env):
    """Return Authorization headers with a valid JWT."""
    token = create_token("admin", app_env["jwt_secret"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(app_env):
    """Yield a synchronous Starlette TestClient bound to the FastAPI app."""
    from web.app import app

    with patch("web.stats.StatsCollector.start"), \
         patch("web.stats.StatsCollector.stop"):
        with TestClient(app) as tc:
            yield tc


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


class TestPushEndpoint:
    """POST /{name}/push"""

    def test_push_success(self, client, auth_headers):
        with patch("web.routes.deploy_routes.scp_directory", new_callable=AsyncMock) as mock_scp:
            mock_scp.return_value = "Copied ok"
            resp = client.post("/api/sites/site-gl/push", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_push_site_not_found(self, client, auth_headers):
        resp = client.post("/api/sites/nonexistent/push", headers=auth_headers)
        assert resp.status_code == 404

    def test_push_no_configs_dir(self, client, auth_headers):
        """site-cp exists but has no generated configs."""
        resp = client.post("/api/sites/site-cp/push", headers=auth_headers)
        assert resp.status_code == 404
        assert "generate" in resp.json()["detail"].lower()

    def test_push_scp_error(self, client, auth_headers):
        with patch("web.routes.deploy_routes.scp_directory", new_callable=AsyncMock) as mock_scp:
            mock_scp.return_value = "[ERROR] SCP failed: connection refused"
            resp = client.post("/api/sites/site-gl/push", headers=auth_headers)
        assert resp.status_code == 502

    def test_push_requires_auth(self, client):
        resp = client.post("/api/sites/site-gl/push")
        assert resp.status_code == 401


class TestSetupEndpoint:
    """POST /{name}/setup"""

    def test_setup_glinet(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "setup complete\n"
            resp = client.post("/api/sites/site-gl/setup", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        # Verify the command references glinet-setup.sh
        call_args = mock_ssh.call_args
        assert "glinet-setup.sh" in call_args[0][1]

    def test_setup_cradlepoint(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "pi setup complete\n"
            resp = client.post("/api/sites/site-cp/setup", headers=auth_headers)
        assert resp.status_code == 200
        call_args = mock_ssh.call_args
        assert "pi-setup.sh" in call_args[0][1]

    def test_setup_ssh_error(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "[ERROR] SSH connection failed: timeout"
            resp = client.post("/api/sites/site-gl/setup", headers=auth_headers)
        assert resp.status_code == 502

    def test_setup_uses_120s_timeout(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "ok"
            client.post("/api/sites/site-gl/setup", headers=auth_headers)
        call_args = mock_ssh.call_args
        # timeout=120 is the third positional arg or keyword
        all_args = call_args[0] + tuple(call_args[1].values())
        assert 120 in all_args


class TestRestartEndpoint:
    """POST /{name}/restart"""

    def test_restart_glinet(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "restarted\n"
            resp = client.post("/api/sites/site-gl/restart", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_restart_ssh_error(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "[ERROR] connection refused"
            resp = client.post("/api/sites/site-gl/restart", headers=auth_headers)
        assert resp.status_code == 502


class TestStatusEndpoint:
    """POST /{name}/status"""

    def test_status_success(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = "wg0 output...\n"
            resp = client.post("/api/sites/site-gl/status", headers=auth_headers)
        assert resp.status_code == 200
        assert "output" in resp.json()

    def test_status_site_not_found(self, client, auth_headers):
        resp = client.post("/api/sites/nonexistent/status", headers=auth_headers)
        assert resp.status_code == 404


class TestRebootEndpoint:
    """POST /{name}/reboot"""

    def test_reboot_returns_ok(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            # Reboot may return error (disconnect) — endpoint should still succeed
            mock_ssh.return_value = "[ERROR] SSH connection failed: disconnected"
            resp = client.post("/api/sites/site-gl/reboot", headers=auth_headers)
        # Reboot endpoint always returns 200 (disconnect is expected)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_reboot_uses_10s_timeout(self, client, auth_headers):
        with patch("web.routes.deploy_routes.run_ssh_command", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ""
            client.post("/api/sites/site-gl/reboot", headers=auth_headers)
        call_args = mock_ssh.call_args
        all_args = call_args[0] + tuple(call_args[1].values())
        assert 10 in all_args


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


class TestSSHWebSocket:
    """WS /api/ws/ssh/{name}"""

    def test_ws_invalid_token_rejected(self, client):
        """WebSocket with invalid token should be closed."""
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/ssh/site-gl?token=bad-token"):
                pass

    def test_ws_nonexistent_site_rejected(self, client, app_env):
        """WebSocket for nonexistent site should be closed."""
        token = create_token("admin", app_env["jwt_secret"])
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/ws/ssh/nosuchsite?token={token}"):
                pass

    def test_ws_streams_output(self, client, app_env):
        """WebSocket sends command output and done marker."""
        token = create_token("admin", app_env["jwt_secret"])

        async def fake_stream(site, command, timeout=30):
            yield "line 1\n"
            yield "line 2\n"

        with patch("web.routes.deploy_routes.stream_ssh_command", side_effect=fake_stream):
            with client.websocket_connect(f"/api/ws/ssh/site-gl?token={token}") as ws:
                ws.send_text(json.dumps({"command": "ls"}))
                msg1 = ws.receive_json()
                assert "output" in msg1
                msg2 = ws.receive_json()
                assert "output" in msg2
                done = ws.receive_json()
                assert done.get("done") is True

    def test_ws_empty_command_returns_error(self, client, app_env):
        """Empty command should return an error message."""
        token = create_token("admin", app_env["jwt_secret"])

        with client.websocket_connect(f"/api/ws/ssh/site-gl?token={token}") as ws:
            ws.send_text(json.dumps({"command": ""}))
            msg = ws.receive_json()
            assert "error" in msg

    def test_ws_invalid_json_returns_error(self, client, app_env):
        """Non-JSON message should return an error."""
        token = create_token("admin", app_env["jwt_secret"])

        with client.websocket_connect(f"/api/ws/ssh/site-gl?token={token}") as ws:
            ws.send_text("not json at all")
            msg = ws.receive_json()
            assert "error" in msg
