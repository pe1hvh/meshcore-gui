#!/usr/bin/env bash
# =============================================================================
# MeshCore Bridge — systemd Service Installer
# =============================================================================
#
# Installs meshcore_bridge as a systemd daemon service.
#
# Usage:
#   sudo bash install_scripts/install_bridge.sh         # from project root
#   cd install_scripts && sudo bash install_bridge.sh   # from install_scripts/
#   sudo bash install_scripts/install_bridge.sh --uninstall
#
# What this script does:
#   1. Copies meshcore_bridge.py and meshcore_bridge/ to /opt/meshcore-bridge/
#   2. Copies bridge_config.yaml to /etc/meshcore/ (if not already present)
#   3. Creates a systemd service unit file
#   4. Reloads systemd and enables the service
#
# After installation:
#   sudo nano /etc/meshcore/bridge_config.yaml   # edit configuration
#   sudo systemctl start meshcore-bridge          # start the service
#   sudo systemctl enable meshcore-bridge         # auto-start on boot
#   sudo systemctl status meshcore-bridge         # check status
#   journalctl -u meshcore-bridge -f              # follow logs
#
#                    Author: PE1HVH
#   SPDX-License-Identifier: MIT
#                 Copyright: (c) 2026 PE1HVH
# =============================================================================

set -euo pipefail

SERVICE_NAME="meshcore-bridge"
INSTALL_DIR="/opt/meshcore-bridge"
CONFIG_DIR="/etc/meshcore"
CONFIG_FILE="${CONFIG_DIR}/bridge_config.yaml"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Resolve project root ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "${SCRIPT_DIR}")" == "install_scripts" ]]; then
    PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
else
    PROJECT_DIR="${SCRIPT_DIR}"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Check root ──
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo)."
    exit 1
fi

# ── Uninstall mode ──
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Uninstalling ${SERVICE_NAME}..."

    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        info "Stopping service..."
        systemctl stop "${SERVICE_NAME}"
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        info "Disabling service..."
        systemctl disable "${SERVICE_NAME}"
    fi

    if [[ -f "${SERVICE_FILE}" ]]; then
        info "Removing service file..."
        rm -f "${SERVICE_FILE}"
        systemctl daemon-reload
    fi

    if [[ -d "${INSTALL_DIR}" ]]; then
        info "Removing installation directory..."
        rm -rf "${INSTALL_DIR}"
    fi

    warn "Configuration preserved at ${CONFIG_DIR}/"
    info "Uninstall complete."
    exit 0
fi

# ── Install mode ──
info "Installing ${SERVICE_NAME}..."

# Verify source files exist
if [[ ! -f "${PROJECT_DIR}/meshcore_bridge.py" ]]; then
    error "meshcore_bridge.py not found in ${PROJECT_DIR}"
    error "Run this script from the project directory or from install_scripts/."
    exit 1
fi

if [[ ! -d "${PROJECT_DIR}/meshcore_bridge" ]]; then
    error "meshcore_bridge/ directory not found in ${PROJECT_DIR}"
    exit 1
fi

# Detect Python interpreter
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "${candidate}" &>/dev/null; then
        PYTHON_BIN="$(command -v "${candidate}")"
        break
    fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
    error "Python 3.10+ not found. Install Python first."
    exit 1
fi

PYTHON_VERSION=$("${PYTHON_BIN}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Using Python ${PYTHON_VERSION} at ${PYTHON_BIN}"

# Check dependencies
info "Checking dependencies..."
"${PYTHON_BIN}" -c "import yaml" 2>/dev/null || {
    error "pyyaml not installed. Run: pip install pyyaml"
    exit 1
}
"${PYTHON_BIN}" -c "from meshcore_gui.core.shared_data import SharedData" 2>/dev/null || {
    error "meshcore_gui not importable. Ensure it is installed or on PYTHONPATH."
    exit 1
}
info "All dependencies satisfied."

# Create install directory
info "Copying files to ${INSTALL_DIR}/..."
mkdir -p "${INSTALL_DIR}"
cp "${PROJECT_DIR}/meshcore_bridge.py" "${INSTALL_DIR}/"
cp -r "${PROJECT_DIR}/meshcore_bridge" "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/meshcore_bridge.py"

# Copy config (preserve existing)
mkdir -p "${CONFIG_DIR}"
if [[ -f "${CONFIG_FILE}" ]]; then
    warn "Config already exists at ${CONFIG_FILE} — not overwriting."
    warn "New template saved as ${CONFIG_FILE}.new"
    cp "${PROJECT_DIR}/bridge_config.yaml" "${CONFIG_FILE}.new"
else
    info "Installing config template at ${CONFIG_FILE}"
    cp "${PROJECT_DIR}/bridge_config.yaml" "${CONFIG_FILE}"
fi

# Detect meshcore_gui location for PYTHONPATH
MESHCORE_GUI_DIR=""
MESHCORE_GUI_PARENT=$("${PYTHON_BIN}" -c "
import meshcore_gui, os
print(os.path.dirname(os.path.dirname(meshcore_gui.__file__)))
" 2>/dev/null || true)

if [[ -n "${MESHCORE_GUI_PARENT}" ]]; then
    MESHCORE_GUI_DIR="${MESHCORE_GUI_PARENT}"
    info "meshcore_gui found at ${MESHCORE_GUI_DIR}"
fi

# Build PYTHONPATH
PYTHONPATH_VALUE="${INSTALL_DIR}"
if [[ -n "${MESHCORE_GUI_DIR}" ]]; then
    PYTHONPATH_VALUE="${INSTALL_DIR}:${MESHCORE_GUI_DIR}"
fi

# Create systemd service file
info "Creating systemd service..."
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=MeshCore Bridge — Cross-Frequency Message Bridge Daemon
Documentation=file://${INSTALL_DIR}/BRIDGE.md
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/meshcore_bridge.py --config=${CONFIG_FILE}
WorkingDirectory=${INSTALL_DIR}
Environment="PYTHONPATH=${PYTHONPATH_VALUE}"

# Restart policy
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home /var/log
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
info "Reloading systemd daemon..."
systemctl daemon-reload

# Copy documentation
if [[ -f "${PROJECT_DIR}/BRIDGE.md" ]]; then
    cp "${PROJECT_DIR}/BRIDGE.md" "${INSTALL_DIR}/"
fi

# ── Summary ──
echo
info "============================================="
info "  Installation complete!"
info "============================================="
echo
info "Files installed:"
info "  Application: ${INSTALL_DIR}/"
info "  Config:      ${CONFIG_FILE}"
info "  Service:     ${SERVICE_FILE}"
echo
info "Next steps:"
info "  1. Edit configuration:  sudo nano ${CONFIG_FILE}"
info "  2. Start the service:   sudo systemctl start ${SERVICE_NAME}"
info "  3. Enable auto-start:   sudo systemctl enable ${SERVICE_NAME}"
info "  4. Check status:        sudo systemctl status ${SERVICE_NAME}"
info "  5. Follow logs:         journalctl -u ${SERVICE_NAME} -f"
info "  6. Open dashboard:      http://localhost:9092"
echo
info "To uninstall: sudo bash install_scripts/install_bridge.sh --uninstall"
