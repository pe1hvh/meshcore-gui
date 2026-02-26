#!/usr/bin/env bash
# =============================================================================
# MeshCore Observer — systemd Service Installer
# =============================================================================
#
# Installs meshcore_observer as a systemd daemon service.
#
# Usage:
#   sudo bash install_observer.sh
#   sudo bash install_observer.sh --uninstall
#
# What this script does:
#   1. Copies meshcore_observer.py and meshcore_observer/ to /opt/meshcore-observer/
#   2. Copies observer_config.yaml to /etc/meshcore/ (if not already present)
#   3. Creates a systemd service unit file
#   4. Reloads systemd and enables the service
#
# After installation:
#   sudo nano /etc/meshcore/observer_config.yaml   # edit configuration
#   sudo systemctl start meshcore-observer          # start the service
#   sudo systemctl enable meshcore-observer         # auto-start on boot
#   sudo systemctl status meshcore-observer         # check status
#   journalctl -u meshcore-observer -f              # follow logs
#
#                    Author: PE1HVH
#   SPDX-License-Identifier: MIT
#                 Copyright: (c) 2026 PE1HVH
# =============================================================================

set -euo pipefail

SERVICE_NAME="meshcore-observer"
INSTALL_DIR="/opt/meshcore-observer"
CONFIG_DIR="/etc/meshcore"
CONFIG_FILE="${CONFIG_DIR}/observer_config.yaml"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
if [[ ! -f "${SCRIPT_DIR}/meshcore_observer.py" ]]; then
    error "meshcore_observer.py not found in ${SCRIPT_DIR}"
    error "Run this script from the meshcore project directory."
    exit 1
fi

if [[ ! -d "${SCRIPT_DIR}/meshcore_observer" ]]; then
    error "meshcore_observer/ directory not found in ${SCRIPT_DIR}"
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
"${PYTHON_BIN}" -c "import nicegui" 2>/dev/null || {
    error "nicegui not installed. Run: pip install nicegui"
    exit 1
}
info "All dependencies satisfied."

# Create install directory
info "Copying files to ${INSTALL_DIR}/..."
mkdir -p "${INSTALL_DIR}"
cp "${SCRIPT_DIR}/meshcore_observer.py" "${INSTALL_DIR}/"
cp -r "${SCRIPT_DIR}/meshcore_observer" "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/meshcore_observer.py"

# Copy config (preserve existing)
mkdir -p "${CONFIG_DIR}"
if [[ -f "${CONFIG_FILE}" ]]; then
    warn "Config already exists at ${CONFIG_FILE} — not overwriting."
    warn "New template saved as ${CONFIG_FILE}.new"
    cp "${SCRIPT_DIR}/observer_config.yaml" "${CONFIG_FILE}.new"
else
    info "Installing config template at ${CONFIG_FILE}"
    cp "${SCRIPT_DIR}/observer_config.yaml" "${CONFIG_FILE}"
fi

# Build PYTHONPATH
PYTHONPATH_VALUE="${INSTALL_DIR}"

# Create systemd service file
info "Creating systemd service..."
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=MeshCore Observer — Read-Only Archive Monitor Dashboard
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/meshcore_observer.py --config=${CONFIG_FILE}
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
info "  6. Open dashboard:      http://localhost:9093"
echo
info "To uninstall: sudo bash ${BASH_SOURCE[0]} --uninstall"
