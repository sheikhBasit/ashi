#!/usr/bin/env bash
set -euo pipefail

# install_service.sh -- Install ASHI as a systemd user service
# Usage: bash scripts/install_service.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_FILE="$PROJECT_DIR/ashi.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "=== ASHI Service Installer ==="
echo "Project: $PROJECT_DIR"
echo "Service: $SERVICE_FILE"

# Verify service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: $SERVICE_FILE not found"
    exit 1
fi

# Verify venv exists
if [ ! -f "$PROJECT_DIR/.venv/bin/python" ]; then
    echo "ERROR: Python venv not found at $PROJECT_DIR/.venv/"
    exit 1
fi

# Create systemd user dir if needed
mkdir -p "$SYSTEMD_USER_DIR"

# Copy service file
cp "$SERVICE_FILE" "$SYSTEMD_USER_DIR/ashi.service"
echo "Copied ashi.service to $SYSTEMD_USER_DIR/"

# Enable linger so service survives logout
echo "Enabling linger for $USER..."
sudo loginctl enable-linger "$USER" 2>/dev/null || {
    echo "WARNING: Could not enable linger (may need sudo). Service will stop on logout."
    echo "Run manually: sudo loginctl enable-linger $USER"
}

# Reload, enable, start
systemctl --user daemon-reload
echo "Reloaded systemd user daemon"

systemctl --user enable ashi.service
echo "Enabled ashi.service"

systemctl --user start ashi.service
echo "Started ashi.service"

# Wait a moment, then show status
sleep 2
echo ""
echo "=== Service Status ==="
systemctl --user status ashi.service --no-pager || true

echo ""
echo "=== Quick Test ==="
if curl -sf http://127.0.0.1:7070/health 2>/dev/null; then
    echo ""
    echo "ASHI daemon is running and healthy."
else
    echo "Daemon may still be starting. Check: systemctl --user status ashi"
fi

echo ""
echo "Commands:"
echo "  systemctl --user status ashi    # check status"
echo "  systemctl --user restart ashi   # restart"
echo "  systemctl --user stop ashi      # stop"
echo "  journalctl --user -u ashi -f    # follow logs"
