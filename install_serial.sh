#!/usr/bin/env bash
# ============================================================================
# MeshCore GUI — Serial Installer
# ============================================================================
#
# Installs a systemd service for the serial-based MeshCore GUI.
# Automatically detects paths and the current user.
#
# Usage:
#   cd ~/meshcore-gui        # (or wherever your project is located)
#   bash install_serial.sh
#
# Optional:
#   bash install_serial.sh --uninstall   # Remove the service
#
# Requirements:
#   - meshcore-gui project with venv/ directory
#   - sudo access (for systemd)
#
# ============================================================================

set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Uninstall mode ──
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Removing meshcore-gui service..."
    sudo systemctl stop meshcore-gui 2>/dev/null || true
    sudo systemctl disable meshcore-gui 2>/dev/null || true
    sudo rm -f /etc/systemd/system/meshcore-gui.service
    sudo systemctl daemon-reload
    sudo systemctl reset-failed 2>/dev/null || true
    ok "Service removed"
    exit 0
fi

# ── Detect environment ──
info "Detecting environment..."

# Current directory must be the project
if [[ ! -f "meshcore_gui.py" ]] && [[ ! -d "meshcore_gui" ]]; then
    error "This script must be run from the meshcore-gui project directory.
       Expected: meshcore_gui.py or meshcore_gui/ directory.
       Current directory: $(pwd)"
fi

PROJECT_DIR="$(pwd)"
CURRENT_USER="$(whoami)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"

# Check venv
if [[ ! -x "${VENV_PYTHON}" ]]; then
    error "Virtual environment not found at: ${VENV_PYTHON}
       Create it first:
         python3 -m venv venv
         source venv/bin/activate
         pip install meshcore nicegui meshcoredecoder"
fi

# Determine the entry point
if [[ -f "${PROJECT_DIR}/meshcore_gui.py" ]]; then
    ENTRY_POINT="meshcore_gui.py"
elif [[ -d "${PROJECT_DIR}/meshcore_gui" ]]; then
    ENTRY_POINT="-m meshcore_gui"
else
    error "Cannot determine entry point."
fi

# Serial port (env or prompt)
SERIAL_PORT="${SERIAL_PORT:-}"
if [[ -z "${SERIAL_PORT}" ]]; then
    echo ""
    echo -e "${YELLOW}Serial device not specified.${NC}"
    echo "You can specify it in two ways:"
    echo ""
    echo "  1. As an environment variable:"
    echo "     SERIAL_PORT=/dev/ttyACM0 bash install_serial.sh"
    echo ""
    echo "  2. Enter manually:"
    read -rp "     Serial device (e.g. /dev/ttyACM0 or /dev/ttyUSB0): " SERIAL_PORT
    echo ""
fi

if [[ -z "${SERIAL_PORT}" ]]; then
    error "No serial device specified. Aborted."
fi

# Optional settings
BAUD="${BAUD:-115200}"
SERIAL_CX_DLY="${SERIAL_CX_DLY:-0.1}"
WEB_PORT="${WEB_PORT:-8081}"
DEBUG_ON="${DEBUG_ON:-}"

if [[ -z "${DEBUG_ON}" ]]; then
    read -rp "Enable debug logging? [y/N] " dbg
    if [[ "${dbg}" == "y" || "${dbg}" == "Y" ]]; then
        DEBUG_ON="yes"
    else
        DEBUG_ON="no"
    fi
fi

DEBUG_FLAG=""
if [[ "${DEBUG_ON}" == "yes" ]]; then
    DEBUG_FLAG="--debug-on"
fi

# Warn about dialout group (Linux)
if ! id -nG "${CURRENT_USER}" | grep -qw "dialout"; then
    warn "User '${CURRENT_USER}' is not in the 'dialout' group."
    warn "Serial access may fail. Fix with:"
    warn "  sudo usermod -aG dialout ${CURRENT_USER}"
    warn "  (then log out/in)"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════"
echo " MeshCore GUI — Serial Installer"
echo "═══════════════════════════════════════════════════"
echo " Project dir:  ${PROJECT_DIR}"
echo " User:         ${CURRENT_USER}"
echo " Python:       ${VENV_PYTHON}"
echo " Entry point:  ${ENTRY_POINT}"
echo " Serial port:  ${SERIAL_PORT}"
echo " Baudrate:     ${BAUD}"
echo " CX delay:     ${SERIAL_CX_DLY}"
echo " Web port:     ${WEB_PORT}"
echo " Debug:        ${DEBUG_ON}"
echo "═══════════════════════════════════════════════════"
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    info "Aborted."
    exit 0
fi

# ── Step 1: Upgrade meshcore library ──
info "Step 1/3: Upgrading meshcore library..."
"${PROJECT_DIR}/venv/bin/pip" install --upgrade meshcore --quiet 2>/dev/null || \
    "${PROJECT_DIR}/venv/bin/pip" install --upgrade meshcore
MESHCORE_VERSION=$("${PROJECT_DIR}/venv/bin/pip" show meshcore 2>/dev/null | grep "^Version:" | awk '{print $2}')
ok "meshcore version: ${MESHCORE_VERSION:-unknown}"

# ── Step 2: Verify Python syntax ──
info "Step 2/3: Verifying Python syntax..."
"${VENV_PYTHON}" -c "
import ast, sys
files = [
    '${PROJECT_DIR}/meshcore_gui.py',
    '${PROJECT_DIR}/meshcore_gui/ble/worker.py',
    '${PROJECT_DIR}/meshcore_gui/ble/commands.py',
]
errors = []
for f in files:
    try:
        ast.parse(open(f).read())
    except Exception as e:
        errors.append(f'{f}: {e}')
if errors:
    print('SYNTAX ERRORS:')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
print('OK')
" || error "Syntax errors found in Python files"
ok "Python files are syntactically correct"

# ── Step 3: Install systemd service ──
info "Step 3/3: Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/meshcore-gui.service"

sudo tee "${SERVICE_FILE}" > /dev/null << SERVICE_EOF
[Unit]
Description=MeshCore GUI (Serial)

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PYTHON} ${ENTRY_POINT} ${SERIAL_PORT} ${DEBUG_FLAG} --port=${WEB_PORT} --baud=${BAUD} --serial-cx-dly=${SERIAL_CX_DLY}
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo systemctl daemon-reload
sudo systemctl enable meshcore-gui
ok "meshcore-gui.service installed and enabled"

# ── Done ──
echo ""
echo "═══════════════════════════════════════════════════"
echo -e " ${GREEN}Installation complete!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo " Commands:"
echo "   sudo systemctl start meshcore-gui      # Start"
echo "   sudo systemctl stop meshcore-gui       # Stop"
echo "   sudo systemctl restart meshcore-gui    # Restart"
echo "   sudo systemctl status meshcore-gui     # Status"
echo "   journalctl -u meshcore-gui -f          # Live logs"
echo ""
echo " Uninstall:"
echo "   bash install_serial.sh --uninstall"
echo ""
echo "═══════════════════════════════════════════════════"

# Optionally start immediately
echo ""
read -rp "Start service now? [y/N] " start_now
if [[ "${start_now}" == "y" || "${start_now}" == "Y" ]]; then
    sudo systemctl start meshcore-gui
    sleep 2
    if systemctl is-active --quiet meshcore-gui; then
        ok "Service is running!"
        echo ""
        info "View live logs: journalctl -u meshcore-gui -f"
    else
        warn "Service could not start. Check logs:"
        echo "  journalctl -u meshcore-gui --no-pager -n 20"
    fi
fi
