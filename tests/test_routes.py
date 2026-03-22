"""Integration tests for Outpost Conduit Web UI routes."""

import os
import sys
import yaml
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set env vars BEFORE importing app
os.environ["ADMIN_USER"] = "admin"
os.environ["JWT_SECRET"] = "testsecret"
os.environ["INVENTORY_PATH"] = "/tmp/test-sites.yaml"
os.environ["OUTPUT_DIR"] = "/tmp/test-output"

from web.auth import hash_password  # noqa: E402

os.environ["ADMIN_PASSWORD_HASH"] = hash_password("testpass")

from fastapi.testclient import TestClient  # noqa: E402
from web.app import app  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INVENTORY = {
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
    ],
}


@pytest.fixture(autouse=True, scope="session")
def write_test_inventory():
    """Write a valid sites.yaml to /tmp/test-sites.yaml before any tests run."""
    os.makedirs("/tmp/test-output", exist_ok=True)
    with open("/tmp/test-sites.yaml", "w") as f:
        yaml.dump(SAMPLE_INVENTORY, f)
    yield
    # Cleanup is optional; leave files for debugging


@pytest.fixture(scope="session")
def client(write_test_inventory):
    """Return a TestClient wrapping the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """Obtain and return a valid JWT token for the test admin user."""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "testpass"})
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    """Return Authorization headers dict for authenticated requests."""
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# TestAuth
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for /api/auth/login and JWT-protected routes."""

    def test_login_success(self, client):
        """POST /api/auth/login with correct credentials returns 200 + token."""
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "testpass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0

    def test_login_bad_password(self, client):
        """POST /api/auth/login with wrong password returns 401."""
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrongpass"},
        )
        assert resp.status_code == 401

    def test_protected_route_no_token(self, client):
        """GET /api/status without Authorization header returns 401."""
        resp = client.get("/api/status")
        assert resp.status_code == 401

    def test_protected_route_with_token(self, client, auth_headers):
        """GET /api/status with valid Bearer token returns 200."""
        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestSitesAPI
# ---------------------------------------------------------------------------


class TestSitesAPI:
    """Tests for /api/sites CRUD endpoints."""

    def test_list_sites(self, client, auth_headers):
        """GET /api/sites returns a list of sites."""
        resp = client.get("/api/sites", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_add_site(self, client, auth_headers):
        """POST /api/sites with valid payload returns 201."""
        new_site = {
            "name": "site-test-new",
            "type": "glinet",
            "tunnel_ip": "172.27.99.1",
            "wan_ip": "198.51.100.99",
            "description": "Integration test site",
        }
        resp = client.post("/api/sites", json=new_site, headers=auth_headers)
        assert resp.status_code == 201

    def test_get_next_ip(self, client, auth_headers):
        """GET /api/sites/next-ip returns a tunnel_ip field."""
        resp = client.get("/api/sites/next-ip", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tunnel_ip" in data
        assert data["tunnel_ip"].startswith("172.27.")

    def test_download_site(self, client, auth_headers):
        """GET /api/sites/{name}/download returns a zip after generating configs."""
        # First generate configs for site-01 so the output dir exists
        gen_resp = client.post("/api/sites/site-01/generate", headers=auth_headers)
        # Generation may fail in test env (no wg binary) — 200 or 500 both acceptable
        # as long as we can verify the download behaviour

        # Create output dir manually if generation failed
        site_dir = "/tmp/test-output/site-01"
        os.makedirs(site_dir, exist_ok=True)
        dummy_config = os.path.join(site_dir, "wg0.conf")
        if not os.path.exists(dummy_config):
            with open(dummy_config, "w") as f:
                f.write("[Interface]\nPrivateKey = dummy\n")

        resp = client.get("/api/sites/site-01/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"


# ---------------------------------------------------------------------------
# TestPages
# ---------------------------------------------------------------------------


class TestPages:
    """Tests for HTML page and static file routes."""

    def test_login_page(self, client):
        """GET /login returns 200 with HTML content."""
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "html" in resp.headers["content-type"].lower()

    def test_index_page(self, client):
        """GET / returns 200 with HTML content."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers["content-type"].lower()

    def test_static_css(self, client):
        """GET /static/css/style.css returns 200."""
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200
