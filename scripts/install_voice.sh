#!/usr/bin/env bash
# scripts/install_voice.sh -- Install ASHI voice daemon dependencies + service.
# Idempotent. Run as your normal user (not root).
#
# Usage: bash scripts/install_voice.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
VENV_PIP="${PROJECT_DIR}/.venv/bin/pip"
SERVICE_FILE="${PROJECT_DIR}/ashi-voice.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
PIPER_VOICE_DIR="$HOME/.local/share/piper"
PIPER_MODEL_NAME="en_US-lessac-medium"
PIPER_DOWNLOAD_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; exit 1; }

echo "============================================="
echo "  ASHI Voice Daemon Installer"
echo "  Project: ${PROJECT_DIR}"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# 0. Verify venv
# ---------------------------------------------------------------------------
if [ ! -f "$VENV_PYTHON" ]; then
    fail "Python venv not found at $VENV_PYTHON — run setup first"
fi

# ---------------------------------------------------------------------------
# 1. Install Python packages
# ---------------------------------------------------------------------------
echo "[1/5] Installing Python packages..."

PACKAGES=(openwakeword faster-whisper sounddevice webrtcvad numpy)

for pkg in "${PACKAGES[@]}"; do
    if "$VENV_PIP" show "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        echo "  Installing $pkg..."
        "$VENV_PIP" install --quiet "$pkg"
        ok "$pkg installed"
    fi
done

# ---------------------------------------------------------------------------
# 2. Install piper-tts
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Installing piper TTS..."

if "$VENV_PIP" show piper-tts &>/dev/null; then
    ok "piper-tts already installed"
else
    echo "  Installing piper-tts..."
    "$VENV_PIP" install --quiet piper-tts
    if "$VENV_PIP" show piper-tts &>/dev/null; then
        ok "piper-tts installed"
    else
        warn "piper-tts pip install failed — will try binary fallback"

        # Fallback: download piper binary
        PIPER_BIN="$HOME/.local/bin/piper"
        if [ -f "$PIPER_BIN" ]; then
            ok "piper binary already at $PIPER_BIN"
        else
            echo "  Downloading piper binary..."
            mkdir -p "$HOME/.local/bin"
            ARCH=$(uname -m)
            if [ "$ARCH" = "x86_64" ]; then
                PIPER_URL="https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz"
            elif [ "$ARCH" = "aarch64" ]; then
                PIPER_URL="https://github.com/rhasspy/piper/releases/latest/download/piper_linux_aarch64.tar.gz"
            else
                warn "Unsupported architecture $ARCH for piper binary"
                PIPER_URL=""
            fi

            if [ -n "$PIPER_URL" ]; then
                TMP_TAR=$(mktemp /tmp/piper-XXXXXX.tar.gz)
                curl -fSL "$PIPER_URL" -o "$TMP_TAR"
                tar xzf "$TMP_TAR" -C "$HOME/.local/bin/" --strip-components=1 piper/piper
                rm -f "$TMP_TAR"
                chmod +x "$PIPER_BIN"
                ok "piper binary installed at $PIPER_BIN"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 3. Download piper voice model
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Downloading piper voice model..."

mkdir -p "$PIPER_VOICE_DIR"

ONNX_FILE="${PIPER_VOICE_DIR}/${PIPER_MODEL_NAME}.onnx"
JSON_FILE="${PIPER_VOICE_DIR}/${PIPER_MODEL_NAME}.onnx.json"

if [ -f "$ONNX_FILE" ] && [ -f "$JSON_FILE" ]; then
    ok "Voice model already downloaded"
else
    echo "  Downloading ${PIPER_MODEL_NAME} voice model..."

    if [ ! -f "$ONNX_FILE" ]; then
        curl -fSL "${PIPER_DOWNLOAD_BASE}/${PIPER_MODEL_NAME}.onnx" -o "$ONNX_FILE"
        ok "Downloaded ${PIPER_MODEL_NAME}.onnx"
    fi

    if [ ! -f "$JSON_FILE" ]; then
        curl -fSL "${PIPER_DOWNLOAD_BASE}/${PIPER_MODEL_NAME}.onnx.json" -o "$JSON_FILE"
        ok "Downloaded ${PIPER_MODEL_NAME}.onnx.json"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Pre-download faster-whisper model
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Pre-downloading faster-whisper base.en model..."

"$VENV_PYTHON" -c "
from faster_whisper import WhisperModel
import sys
try:
    m = WhisperModel('base.en', device='cpu', compute_type='int8')
    print('  Model loaded and cached.')
except Exception as e:
    print(f'  Warning: {e}', file=sys.stderr)
" && ok "Whisper base.en model ready" || warn "Whisper model download may have failed — will retry on first use"

# ---------------------------------------------------------------------------
# 5. Install systemd user service
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Installing ashi-voice systemd user service..."

if [ ! -f "$SERVICE_FILE" ]; then
    fail "Service file not found: $SERVICE_FILE"
fi

mkdir -p "$SYSTEMD_USER_DIR"
cp "$SERVICE_FILE" "$SYSTEMD_USER_DIR/ashi-voice.service"
ok "Copied ashi-voice.service to $SYSTEMD_USER_DIR/"

systemctl --user daemon-reload
ok "Reloaded systemd user daemon"

systemctl --user enable ashi-voice.service
ok "Enabled ashi-voice.service"

systemctl --user start ashi-voice.service
ok "Started ashi-voice.service"

# Wait and check
sleep 3
echo ""
echo "============================================="
echo "  Service Status"
echo "============================================="
systemctl --user status ashi-voice.service --no-pager || true

echo ""
echo "============================================="
echo "  Done!"
echo "============================================="
echo ""
echo "Commands:"
echo "  systemctl --user status ashi-voice   # check status"
echo "  systemctl --user restart ashi-voice  # restart"
echo "  systemctl --user stop ashi-voice     # stop"
echo "  journalctl --user -u ashi-voice -f   # follow logs"
