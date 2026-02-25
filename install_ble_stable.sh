#!/usr/bin/env bash
# ============================================================================
# MeshCore GUI — BLE Installer
# ============================================================================
#
# Installs the BLE PIN agent, reconnect module, systemd service
# and D-Bus policy.  Automatically detects the correct paths and user.
#
# Usage:
#   cd ~/meshcore-gui        # (or wherever your project is located)
#   bash install_ble_stable.sh
#
# Optional:
#   bash install_ble_stable.sh --uninstall   # Remove everything
#
# Requirements:
#   - meshcore-gui project with venv/ directory
#   - sudo access (for systemd and D-Bus config)
#   - Linux with BlueZ (Bluetooth)
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
    info "Removing meshcore-gui service and configuration..."
    sudo systemctl stop meshcore-gui 2>/dev/null || true
    sudo systemctl disable meshcore-gui 2>/dev/null || true
    sudo rm -f /etc/systemd/system/meshcore-gui.service
    sudo rm -f /etc/dbus-1/system.d/meshcore-ble.conf
    sudo systemctl daemon-reload
    sudo systemctl reset-failed 2>/dev/null || true
    ok "Service and configuration removed"
    info "Python files in your project have NOT been removed."
    info "Remove manually if desired:"
    info "  rm meshcore_gui/ble/ble_agent.py"
    info "  rm meshcore_gui/ble/ble_reconnect.py"
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
         pip install meshcore nicegui bleak meshcoredecoder"
fi

# Determine the entry point
if [[ -f "${PROJECT_DIR}/meshcore_gui.py" ]]; then
    ENTRY_POINT="meshcore_gui.py"
elif [[ -d "${PROJECT_DIR}/meshcore_gui" ]]; then
    ENTRY_POINT="-m meshcore_gui"
else
    error "Cannot determine entry point."
fi

# Check BLE address argument
BLE_ADDRESS="${BLE_ADDRESS:-}"
if [[ -z "${BLE_ADDRESS}" ]]; then
    echo ""
    echo -e "${YELLOW}BLE MAC address not specified.${NC}"
    echo "You can specify it in two ways:"
    echo ""
    echo "  1. As an environment variable:"
    echo "     BLE_ADDRESS=FF:05:D6:71:83:8D bash install_ble_stable.sh"
    echo ""
    echo "  2. Enter manually:"
    read -rp "     BLE MAC address (e.g. FF:05:D6:71:83:8D): " BLE_ADDRESS
    echo ""
fi

if [[ -z "${BLE_ADDRESS}" ]]; then
    error "No BLE MAC address specified. Aborted."
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════"
echo " MeshCore GUI — BLE Stability Installer"
echo "═══════════════════════════════════════════════════"
echo " Project dir:  ${PROJECT_DIR}"
echo " User:         ${CURRENT_USER}"
echo " Python:       ${VENV_PYTHON}"
echo " Entry point:  ${ENTRY_POINT}"
echo " BLE address:  ${BLE_ADDRESS}"
echo "═══════════════════════════════════════════════════"
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    info "Aborted."
    exit 0
fi

# ── Step 1: Upgrade meshcore library ──
info "Step 1/6: Upgrading meshcore library..."
"${PROJECT_DIR}/venv/bin/pip" install --upgrade meshcore --quiet 2>/dev/null || \
    "${PROJECT_DIR}/venv/bin/pip" install --upgrade meshcore
MESHCORE_VERSION=$("${PROJECT_DIR}/venv/bin/pip" show meshcore 2>/dev/null | grep "^Version:" | awk '{print $2}')
ok "meshcore version: ${MESHCORE_VERSION:-unknown}"

# ── Step 2: Check that dbus_fast is available ──
info "Step 2/6: Checking dbus_fast dependency..."
if "${VENV_PYTHON}" -c "import dbus_fast" 2>/dev/null; then
    ok "dbus_fast available (included with bleak)"
else
    warn "dbus_fast not found, installing..."
    "${PROJECT_DIR}/venv/bin/pip" install dbus-fast --quiet
    ok "dbus_fast installed"
fi

# ── Step 3: Copy Python files ──
info "Step 3/6: Installing Python files..."

# Detect if ble_agent.py and ble_reconnect.py already exist
BLE_DIR="${PROJECT_DIR}/meshcore_gui/ble"
if [[ ! -d "${BLE_DIR}" ]]; then
    error "Directory ${BLE_DIR} not found."
fi

# Check if the files are already in place
AGENT_OK=false
RECONNECT_OK=false
[[ -f "${BLE_DIR}/ble_agent.py" ]] && AGENT_OK=true
[[ -f "${BLE_DIR}/ble_reconnect.py" ]] && RECONNECT_OK=true

if $AGENT_OK && $RECONNECT_OK; then
    ok "ble_agent.py and ble_reconnect.py are already installed"
else
    # Check if they are in the same directory as this script
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    if [[ -f "${SCRIPT_DIR}/meshcore_gui/ble/ble_agent.py" ]]; then
        cp "${SCRIPT_DIR}/meshcore_gui/ble/ble_agent.py" "${BLE_DIR}/"
        cp "${SCRIPT_DIR}/meshcore_gui/ble/ble_reconnect.py" "${BLE_DIR}/"
        ok "Files copied from ${SCRIPT_DIR}"
    else
        if ! $AGENT_OK; then
            error "ble_agent.py not found in ${BLE_DIR}/
       Copy this file manually to ${BLE_DIR}/"
        fi
        if ! $RECONNECT_OK; then
            error "ble_reconnect.py not found in ${BLE_DIR}/
       Copy this file manually to ${BLE_DIR}/"
        fi
    fi
fi

# Verify Python syntax
info "Verifying Python syntax..."
"${VENV_PYTHON}" -c "
import ast, sys
errors = []
for f in ['${BLE_DIR}/ble_agent.py', '${BLE_DIR}/ble_reconnect.py', '${BLE_DIR}/worker.py']:
    try:
        ast.parse(open(f).read())
    except SyntaxError as e:
        errors.append(f'{f}: {e}')
if errors:
    print('SYNTAX ERRORS:')
    for e in errors:
        print(f'  {e}')
    sys.exit(1)
print('OK')
" || error "Syntax errors found in Python files"
ok "All Python files are syntactically correct"

# ── Step 4: Remove old bt-agent service ──
info "Step 4/6: Cleaning up old services..."
if systemctl is-active --quiet bt-agent 2>/dev/null; then
    sudo systemctl stop bt-agent
    sudo systemctl disable bt-agent
    ok "bt-agent.service stopped and disabled"
elif systemctl list-unit-files | grep -q bt-agent 2>/dev/null; then
    sudo systemctl disable bt-agent 2>/dev/null || true
    ok "bt-agent.service disabled"
else
    ok "bt-agent.service was already absent"
fi

# Stop existing meshcore-gui service if running
if systemctl is-active --quiet meshcore-gui 2>/dev/null; then
    sudo systemctl stop meshcore-gui
    ok "Existing meshcore-gui.service stopped"
fi

# ── Step 5: Install D-Bus policy ──
info "Step 5/6: Installing D-Bus policy..."
DBUS_CONF="/etc/dbus-1/system.d/meshcore-ble.conf"

sudo tee "${DBUS_CONF}" > /dev/null << DBUS_EOF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <!-- Allow user '${CURRENT_USER}' to interact with BlueZ for BLE pairing agent -->
  <policy user="${CURRENT_USER}">
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.Agent1"/>
    <allow send_interface="org.bluez.AgentManager1"/>
  </policy>
</busconfig>
DBUS_EOF

ok "D-Bus policy installed for user '${CURRENT_USER}'"

# ── Step 6: Install systemd service ──
info "Step 6/6: Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/meshcore-gui.service"

sudo tee "${SERVICE_FILE}" > /dev/null << SERVICE_EOF
[Unit]
Description=MeshCore GUI (BLE)
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PYTHON} ${ENTRY_POINT} ${BLE_ADDRESS} --debug-on
Restart=on-failure
RestartSec=30
Environment=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket

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
echo "   bash install_ble_stable.sh --uninstall"
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
