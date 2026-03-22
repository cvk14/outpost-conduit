#!/bin/bash
set -euo pipefail

# Outpost Conduit Web UI setup
# Usage: sudo ./scripts/web-setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
SERVICE_USER="${SUDO_USER:-$(whoami)}"

echo "=== Outpost Conduit Web UI Setup ==="

# --- Create venv ---
echo "[1/5] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q fastapi "uvicorn[standard]" asyncssh bcrypt pyjwt pyyaml

# --- Create .env ---
if [ ! -f "$ENV_FILE" ]; then
    echo "[2/5] Configuring admin credentials..."
    read -rp "Admin username [admin]: " ADMIN_USER
    ADMIN_USER="${ADMIN_USER:-admin}"
    read -rsp "Admin password: " ADMIN_PASS
    echo
    ADMIN_HASH=$("$VENV_DIR/bin/python3" -c "
import bcrypt, sys
pw = sys.stdin.buffer.read()
print(bcrypt.hashpw(pw, bcrypt.gensalt()).decode())
" <<< "$ADMIN_PASS")
    JWT_SECRET=$(openssl rand -hex 32)

    cat > "$ENV_FILE" << EOF
ADMIN_USER=$ADMIN_USER
ADMIN_PASSWORD_HASH=$ADMIN_HASH
JWT_SECRET=$JWT_SECRET
INVENTORY_PATH=$PROJECT_DIR/sites.yaml
OUTPUT_DIR=$PROJECT_DIR/output
EOF
    chmod 600 "$ENV_FILE"
    echo "  Credentials saved to $ENV_FILE"
else
    echo "[2/5] .env already exists, skipping..."
fi

# --- Install systemd service ---
echo "[3/5] Installing systemd service..."
cat > /etc/systemd/system/outpost-conduit-web.service << UNIT
[Unit]
Description=Outpost Conduit Web UI
After=wg-quick@wg0.service wg-mcast-bridge.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/uvicorn web.app:app --host 0.0.0.0 --port 8080
Restart=always
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
UNIT

# --- Enable and start ---
echo "[4/5] Starting service..."
systemctl daemon-reload
systemctl enable outpost-conduit-web
systemctl start outpost-conduit-web

# --- Done ---
echo "[5/5] Verifying..."
sleep 2
if systemctl is-active outpost-conduit-web >/dev/null; then
    echo ""
    echo "=== Web UI is running ==="
    echo "URL: http://$(hostname -I | awk '{print $1}'):8080"
    echo "Service: systemctl status outpost-conduit-web"
else
    echo "ERROR: Service failed to start"
    systemctl status outpost-conduit-web
    exit 1
fi
