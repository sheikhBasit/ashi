#!/usr/bin/env bash
# scripts/setup_computer_control.sh
# Setup script for ASHI Phase 2: Computer Control
# Run once on a fresh machine or after OS upgrade.
#
# Usage: bash scripts/setup_computer_control.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PIP="${PROJECT_DIR}/.venv/bin/pip"

echo "=== ASHI Phase 2: Computer Control Setup ==="
echo "Project: ${PROJECT_DIR}"
echo ""

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    ydotool \
    tesseract-ocr \
    tesseract-ocr-eng \
    python3-dbus \
    wmctrl \
    2>/dev/null

echo "  ydotool:     $(which ydotool 2>/dev/null || echo 'NOT FOUND')"
echo "  tesseract:   $(which tesseract 2>/dev/null || echo 'NOT FOUND')"
echo "  wmctrl:      $(which wmctrl 2>/dev/null || echo 'NOT FOUND')"

# ---------------------------------------------------------------------------
# 2. Python packages into project venv
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Installing Python packages into .venv..."
if [ -f "${VENV_PIP}" ]; then
    "${VENV_PIP}" install --quiet Pillow pytesseract
    echo "  Pillow:      OK"
    echo "  pytesseract: OK"
else
    echo "  WARNING: .venv not found at ${VENV_PIP}"
    echo "  Run: python3 -m venv .venv && .venv/bin/pip install Pillow pytesseract"
fi

# ---------------------------------------------------------------------------
# 3. ydotool daemon setup (for ydotool >= 1.0)
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Configuring ydotool..."

# Check ydotool version
YDOTOOL_VERSION=$(ydotool --version 2>/dev/null | head -1 || echo "0.1.x")
echo "  Version: ${YDOTOOL_VERSION}"

# Ensure user is in 'input' group (for /dev/uinput access)
if ! groups | grep -q '\binput\b'; then
    echo "  Adding $(whoami) to 'input' group..."
    sudo usermod -aG input "$(whoami)"
    echo "  NOTE: Log out and back in for group change to take effect."
else
    echo "  User already in 'input' group."
fi

# udev rule for uinput access
UDEV_RULE="/etc/udev/rules.d/80-uinput.rules"
if [ ! -f "${UDEV_RULE}" ]; then
    echo "  Creating udev rule for /dev/uinput..."
    echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' | \
        sudo tee "${UDEV_RULE}" > /dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "  udev rule created."
else
    echo "  udev rule already exists."
fi

# For ydotool 1.x+: set up systemd user service for ydotoold
if echo "${YDOTOOL_VERSION}" | grep -qE "^1\.|^[2-9]"; then
    SYSTEMD_DIR="${HOME}/.config/systemd/user"
    SERVICE_FILE="${SYSTEMD_DIR}/ydotoold.service"
    mkdir -p "${SYSTEMD_DIR}"

    if [ ! -f "${SERVICE_FILE}" ]; then
        echo "  Creating ydotoold systemd user service..."
        cat > "${SERVICE_FILE}" << 'UNIT'
[Unit]
Description=ydotoold - ydotool daemon
Documentation=https://github.com/ReimuNotMoe/ydotool

[Service]
ExecStart=/usr/bin/ydotoold
ExecStartPost=/bin/sleep 0.5
ExecStartPost=/bin/chmod 666 /tmp/.ydotool_socket
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
        systemctl --user daemon-reload
        systemctl --user enable ydotoold.service
        systemctl --user start ydotoold.service
        echo "  ydotoold service started."
    else
        echo "  ydotoold service already configured."
        systemctl --user start ydotoold.service 2>/dev/null || true
    fi

    # Ensure YDOTOOL_SOCKET is set in environment
    if ! grep -q "YDOTOOL_SOCKET" "${HOME}/.profile" 2>/dev/null; then
        echo 'export YDOTOOL_SOCKET=/tmp/.ydotool_socket' >> "${HOME}/.profile"
        echo "  Added YDOTOOL_SOCKET to ~/.profile"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Ollama vision model
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Pulling vision model for screen understanding..."
if command -v ollama &> /dev/null; then
    if ! ollama list 2>/dev/null | grep -q "moondream"; then
        echo "  Pulling moondream (this may take a minute)..."
        ollama pull moondream
    else
        echo "  moondream already available."
    fi
else
    echo "  WARNING: ollama not found. Install it for screen_understand."
fi

# ---------------------------------------------------------------------------
# 5. Screenshot cache directory
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Creating screenshot cache directory..."
mkdir -p "${HOME}/.cache/ashi/screenshots"
echo "  ${HOME}/.cache/ashi/screenshots"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Verify with:"
echo "  cd ${PROJECT_DIR}"
echo "  .venv/bin/python -c 'from functions.computer_control import check_computer_control_health; import json; print(json.dumps(check_computer_control_health(), indent=2))'"
echo ""
echo "Run tests:"
echo "  .venv/bin/pytest tests/test_computer_control.py -v"
echo ""

# Check if logout needed
if ! groups | grep -q '\binput\b'; then
    echo "IMPORTANT: Log out and back in for 'input' group membership to take effect."
    echo "           ydotool will not work until you do this."
fi
