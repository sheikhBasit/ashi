#!/usr/bin/env bash
# scripts/install_system_deps.sh
# Install system-level dependencies for ASHI computer control (Phase 2).
# Idempotent — safe to run multiple times.
#
# Usage: sudo bash scripts/install_system_deps.sh
# (or: bash scripts/install_system_deps.sh  — will prompt for sudo password)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
TARGET_USER="${SUDO_USER:-basitdev}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }

echo "============================================="
echo "  ASHI System Dependencies Installer"
echo "  Project: ${PROJECT_DIR}"
echo "  User:    ${TARGET_USER}"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# 1. Install system packages
# ---------------------------------------------------------------------------
echo "[1/6] Installing system packages..."

PACKAGES=(ydotool tesseract-ocr tesseract-ocr-eng wmctrl)
MISSING=()

for pkg in "${PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "  Installing: ${MISSING[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${MISSING[@]}"
    for pkg in "${MISSING[@]}"; do
        if dpkg -s "$pkg" &>/dev/null; then
            ok "$pkg installed"
        else
            fail "$pkg failed to install"
        fi
    done
else
    ok "All system packages already installed"
fi

# ---------------------------------------------------------------------------
# 2. Create udev rule for /dev/uinput
# ---------------------------------------------------------------------------
echo ""
echo "[2/6] Configuring udev rule for /dev/uinput..."

UDEV_RULE="/etc/udev/rules.d/80-uinput.rules"
UDEV_CONTENT='KERNEL=="uinput", GROUP="input", MODE="0660"'

if [ -f "$UDEV_RULE" ]; then
    ok "udev rule already exists at $UDEV_RULE"
else
    echo "$UDEV_CONTENT" | sudo tee "$UDEV_RULE" > /dev/null
    ok "Created $UDEV_RULE"
fi

# ---------------------------------------------------------------------------
# 3. Reload udev rules
# ---------------------------------------------------------------------------
echo ""
echo "[3/6] Reloading udev rules..."

sudo udevadm control --reload-rules
sudo udevadm trigger
ok "udev rules reloaded"

# ---------------------------------------------------------------------------
# 4. Add user to input group
# ---------------------------------------------------------------------------
echo ""
echo "[4/6] Checking 'input' group membership..."

if id -nG "$TARGET_USER" | grep -qw input; then
    ok "$TARGET_USER is already in 'input' group"
else
    sudo usermod -aG input "$TARGET_USER"
    ok "Added $TARGET_USER to 'input' group"
    warn "You must log out and back in for group change to take effect"
fi

# ---------------------------------------------------------------------------
# 5. Enable/start ydotoold
# ---------------------------------------------------------------------------
echo ""
echo "[5/6] Setting up ydotoold..."

# Check if systemd system-level unit exists
if systemctl list-unit-files ydotoold.service &>/dev/null && systemctl list-unit-files ydotoold.service 2>/dev/null | grep -q ydotoold; then
    # System-level unit exists
    if systemctl is-active --quiet ydotoold.service 2>/dev/null; then
        ok "ydotoold system service is already running"
    else
        sudo systemctl enable ydotoold.service 2>/dev/null || true
        sudo systemctl start ydotoold.service 2>/dev/null || true
        if systemctl is-active --quiet ydotoold.service 2>/dev/null; then
            ok "ydotoold system service started"
        else
            warn "System service failed, will try user service"
        fi
    fi
fi

# Check if user-level systemd unit exists or create one
SYSTEMD_USER_DIR="/home/${TARGET_USER}/.config/systemd/user"
USER_SERVICE="${SYSTEMD_USER_DIR}/ydotoold.service"

# Only set up user service if system service is not running
if ! systemctl is-active --quiet ydotoold.service 2>/dev/null; then
    if [ ! -f "$USER_SERVICE" ]; then
        sudo -u "$TARGET_USER" mkdir -p "$SYSTEMD_USER_DIR"
        cat > "$USER_SERVICE" << 'UNIT'
[Unit]
Description=ydotoold - ydotool daemon
Documentation=https://github.com/ReimuNotMoe/ydotool

[Service]
ExecStart=/usr/bin/ydotoold
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
        ok "Created user service at $USER_SERVICE"
    fi

    # Try to start user service (may fail if not logged in with systemd user session)
    if sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$TARGET_USER")" \
        systemctl --user daemon-reload 2>/dev/null; then
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$TARGET_USER")" \
            systemctl --user enable ydotoold.service 2>/dev/null || true
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$TARGET_USER")" \
            systemctl --user start ydotoold.service 2>/dev/null || true
        ok "ydotoold user service configured"
    else
        # Fallback: check if ydotoold is already running as a process
        if pgrep -x ydotoold &>/dev/null; then
            ok "ydotoold is running as a background process"
        else
            warn "Cannot start ydotoold via systemd. Start manually: ydotoold &"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 6. Pull moondream via Ollama
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Checking Ollama vision model (moondream)..."

if command -v ollama &>/dev/null; then
    if ollama list 2>/dev/null | grep -q moondream; then
        ok "moondream model already pulled"
    else
        echo "  Pulling moondream (this may take a few minutes)..."
        ollama pull moondream
        if ollama list 2>/dev/null | grep -q moondream; then
            ok "moondream model pulled successfully"
        else
            fail "moondream pull may have failed — check ollama manually"
        fi
    fi
else
    warn "ollama not found in PATH — skip model pull"
fi

# ---------------------------------------------------------------------------
# Create screenshot cache dir
# ---------------------------------------------------------------------------
sudo -u "$TARGET_USER" mkdir -p "/home/${TARGET_USER}/.cache/ashi/screenshots"

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo "  Running cc_health check..."
echo "============================================="
echo ""

if [ -f "$VENV_PYTHON" ]; then
    cd "$PROJECT_DIR"
    sudo -u "$TARGET_USER" "$VENV_PYTHON" -c "
import sys
sys.path.insert(0, 'functions')
from computer_control import check_computer_control_health
import json
health = check_computer_control_health()
print(json.dumps(health, indent=2))
all_ok = all(v.get('available', False) for v in health.values())
if all_ok:
    print('\n  All dependencies OK.')
else:
    print('\n  Some dependencies missing — see above.')
    sys.exit(1)
" || warn "Health check reported issues (see output above)"
else
    warn "Venv not found at $VENV_PYTHON — skipping health check"
fi

echo ""
echo "============================================="
echo "  Done. If group membership changed, log out and back in."
echo "============================================="
