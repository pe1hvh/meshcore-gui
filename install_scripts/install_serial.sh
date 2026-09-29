#!/usr/bin/env bash
# ============================================================================
# MeshCore GUI — Serial Installer (multi-instance)
# ============================================================================
#
# Installs a systemd service for the serial-based MeshCore GUI.
# The service name is derived from the serial port, so multiple instances
# can coexist on the same machine.
#
# Usage:
#   bash install_scripts/install_serial.sh         # from project root
#   cd install_scripts && bash install_serial.sh   # from install_scripts/
#
# Optional env vars:
#   SERIAL_PORT=/dev/ttyUSB0   Serial device (will prompt if omitted)
#   WEB_PORT=8081               NiceGUI web port (default: 8081)
#   BAUD=115200                 Baud rate (default: 115200)
#   SERIAL_CX_DLY=0.1          Serial connect delay (default: 0.1)
#   DEBUG_ON=yes|no             Enable debug logging (will prompt if omitted)
#
# Examples — two instances on the same machine:
#   SERIAL_PORT=/dev/ttyUSB1 WEB_PORT=8081 bash install_scripts/install_serial.sh
#   SERIAL_PORT=/dev/ttyUSB2 WEB_PORT=8082 bash install_scripts/install_serial.sh
#
# Uninstall a specific instance:
#   SERIAL_PORT=/dev/ttyUSB1 bash install_scripts/install_serial.sh --uninstall
#
# List all installed instances:
#   bash install_scripts/install_serial.sh --list
#
# Requirements:
#   - meshcore-gui project with .venv/ directory (uv supported too)
#   - sudo access (for systemd)
#
# ============================================================================

set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Resolve project root ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "${SCRIPT_DIR}")" == "install_scripts" ]]; then
    PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
else
    PROJECT_DIR="${SCRIPT_DIR}"
fi

# ── List mode ──
if [[ "${1:-}" == "--list" ]]; then
    echo ""
    echo "Installed MeshCore GUI instances:"
    echo "─────────────────────────────────────────────────"
    found=0
    for f in /etc/systemd/system/meshcore-gui-*.service; do
        [[ -f "$f" ]] || continue
        name="$(basename "$f" .service)"
        status="$(systemctl is-active "$name" 2>/dev/null || echo inactive)"
        port="$(grep -oP '(?<=--port=)\S+' "$f" 2>/dev/null || echo '?')"
        device="$(grep -oP '(?<=ExecStart=.{60,200} )/dev/\S+' "$f" 2>/dev/null | head -1 || echo '?')"
        echo "  ${name}"
        echo "    device : ${device}"
        echo "    port   : ${port}"
        echo "    status : ${status}"
        echo ""
        found=1
    done
    if [[ $found -eq 0 ]]; then
        echo "  (none found)"
    fi
    echo "─────────────────────────────────────────────────"
    exit 0
fi

# ── Resolve serial port (needed for service name) ──
SERIAL_PORT="${SERIAL_PORT:-}"
if [[ -z "${SERIAL_PORT}" ]]; then
    echo ""
    echo -e "${YELLOW}Serial device not specified.${NC}"
    echo "You can specify it in two ways:"
    echo ""
    echo "  1. As an environment variable:"
    echo "     SERIAL_PORT=/dev/ttyACM0 bash $0"
    echo ""
    echo "  2. Enter manually:"
    read -rp "     Serial device (e.g. /dev/ttyACM0 or /dev/ttyUSB0): " SERIAL_PORT
    echo ""
fi

if [[ -z "${SERIAL_PORT}" ]]; then
    error "No serial device specified. Aborted."
fi

# Derive a safe service name from the device path
# e.g. /dev/ttyUSB1 → meshcore-gui-ttyUSB1
DEVICE_SLUG="$(basename "${SERIAL_PORT}")"
SERVICE_NAME="meshcore-gui-${DEVICE_SLUG}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Uninstall mode ──
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Removing ${SERVICE_NAME}..."
    sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    sudo systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    sudo rm -f "${SERVICE_FILE}"
    sudo systemctl daemon-reload
    sudo systemctl reset-failed 2>/dev/null || true
    ok "Service '${SERVICE_NAME}' removed"
    exit 0
fi

# ── Detect environment ──
info "Detecting environment..."

if [[ ! -f "${PROJECT_DIR}/meshcore_gui.py" ]] && [[ ! -d "${PROJECT_DIR}/meshcore_gui" ]]; then
    error "Cannot find meshcore_gui.py or meshcore_gui/ in ${PROJECT_DIR}
       Run this script from the project directory or from install_scripts/."
fi

CURRENT_USER="$(whoami)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

if command -v uv >/dev/null; then
    UV="$(which uv)" 
else
    UV=""
fi

# Check .venv / bootstrap dependencies when missing
if [[ ! -x "${VENV_PYTHON}" ]]; then
    if [[ -z "${UV}" ]] ; then
        info "Virtual environment not found. Creating project .venv..."
        python3 -m venv "${PROJECT_DIR}/.venv"

        info "Installing required Python packages into the .venv..."
        # shellcheck disable=SC1091
        source "${PROJECT_DIR}/.venv/bin/activate"
        pip install nicegui meshcore meshcoredecoder
        ok "Virtual environment created and dependencies installed"
    fi
fi

# Determine the entry point
if [[ -f "${PROJECT_DIR}/meshcore_gui.py" ]]; then
    ENTRY_POINT="meshcore_gui.py"
elif [[ -d "${PROJECT_DIR}/meshcore_gui" ]]; then
    ENTRY_POINT="-m meshcore_gui"
else
    error "Cannot determine entry point."
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

# Warn if this service already exists
if [[ -f "${SERVICE_FILE}" ]]; then
    warn "Service '${SERVICE_NAME}' already exists and will be overwritten."
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════"
echo " MeshCore GUI — Serial Installer"
echo "═══════════════════════════════════════════════════"
echo " Project dir:  ${PROJECT_DIR}"
echo " User:         ${CURRENT_USER}"
if [[ ! -z ${UV} ]]; then
  echo " Uv:           ${UV}"
fi 
echo " Python:       ${VENV_PYTHON}"
echo " Entry point:  ${ENTRY_POINT}"
echo " Serial port:  ${SERIAL_PORT}"
echo " Baudrate:     ${BAUD}"
echo " CX delay:     ${SERIAL_CX_DLY}"
echo " Web port:     ${WEB_PORT}"
echo " Debug:        ${DEBUG_ON}"
echo " Service name: ${SERVICE_NAME}"
echo "═══════════════════════════════════════════════════"
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    info "Aborted."
    exit 0
fi

if [[ -z "${UV}" ]] ; then
# ── Step 1: Upgrade meshcore library ──
info "Step 1/3: Upgrading meshcore library..."
"${PROJECT_DIR}/.venv/bin/pip" install --upgrade meshcore --quiet 2>/dev/null || \
    "${PROJECT_DIR}/.venv/bin/pip" install --upgrade meshcore
MESHCORE_VERSION=$("${PROJECT_DIR}/.venv/bin/pip" show meshcore 2>/dev/null | grep "^Version:" | awk '{print $2}')
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
fi

if [[ ! -z "${UV}" ]] ; then
    # uv will take care of installing all requirements
    VENV_PYTHON="${UV} run"
fi

# ── Step 3: Install systemd service ──
info "Step 3/3: Installing systemd service..."

sudo tee "${SERVICE_FILE}" > /dev/null << SERVICE_EOF
[Unit]
Description=MeshCore GUI (${SERIAL_PORT})

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
sudo systemctl enable "${SERVICE_NAME}"
ok "'${SERVICE_NAME}' installed and enabled"

# ── Done ──
echo ""
echo "═══════════════════════════════════════════════════"
echo -e " ${GREEN}Installation complete!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo " Commands:"
echo "   sudo systemctl start   ${SERVICE_NAME}"
echo "   sudo systemctl stop    ${SERVICE_NAME}"
echo "   sudo systemctl restart ${SERVICE_NAME}"
echo "   sudo systemctl status  ${SERVICE_NAME}"
echo "   journalctl -u ${SERVICE_NAME} -f"
echo ""
echo " All instances:"
echo "   bash install_scripts/install_serial.sh --list"
echo ""
echo " Uninstall this instance:"
echo "   SERIAL_PORT=${SERIAL_PORT} bash install_scripts/install_serial.sh --uninstall"
echo ""
echo "═══════════════════════════════════════════════════"

# Optionally start immediately
echo ""
read -rp "Start service now? [y/N] " start_now
if [[ "${start_now}" == "y" || "${start_now}" == "Y" ]]; then
    sudo systemctl start "${SERVICE_NAME}"
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        ok "Service is running!"
        echo ""
        info "View live logs: journalctl -u ${SERVICE_NAME} -f"
    else
        warn "Service could not start. Check logs:"
        echo "  journalctl -u ${SERVICE_NAME} --no-pager -n 20"
    fi
fi
