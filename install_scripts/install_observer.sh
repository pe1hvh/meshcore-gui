#!/usr/bin/env bash
# ============================================================================
# MeshCore Observer — systemd Service Installer
# ============================================================================
#
# Installs a systemd service for the MeshCore Observer daemon.
# Automatically detects the venv and current user.
#
# Usage:
#   bash install_scripts/install_observer.sh         # from project root
#   cd install_scripts && bash install_observer.sh   # from install_scripts/
#
# Optional:
#   bash install_scripts/install_observer.sh --uninstall
#
# Requirements:
#   - meshcore-gui project with venv/ directory
#   - nicegui and pyyaml installed in the venv
#   - sudo access (for systemd)
#
#                    Author: PE1HVH
#   SPDX-License-Identifier: MIT
#                 Copyright: (c) 2026 PE1HVH
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

SERVICE_NAME="meshcore-observer"

# ── Resolve project root ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "${SCRIPT_DIR}")" == "install_scripts" ]]; then
    PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
else
    PROJECT_DIR="${SCRIPT_DIR}"
fi

# ── Uninstall mode ──
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Removing ${SERVICE_NAME} service..."
    sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    sudo systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl daemon-reload
    sudo systemctl reset-failed 2>/dev/null || true
    ok "Service removed"
    exit 0
fi

# ── Detect environment ──
info "Detecting environment..."

if [[ ! -f "${PROJECT_DIR}/meshcore_observer.py" ]] && [[ ! -d "${PROJECT_DIR}/meshcore_observer" ]]; then
    error "Cannot find meshcore_observer.py or meshcore_observer/ in ${PROJECT_DIR}
       Run this script from the project directory or from install_scripts/."
fi

CURRENT_USER="$(whoami)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"

# Check venv
if [[ ! -x "${VENV_PYTHON}" ]]; then
    # Try parent directory venv (observer may be in meshcore-gui project)
    PARENT_VENV="$(dirname "${PROJECT_DIR}")/venv/bin/python"
    if [[ -x "${PARENT_VENV}" ]]; then
        VENV_PYTHON="${PARENT_VENV}"
        warn "Using parent directory venv: ${VENV_PYTHON}"
    else
        error "Virtual environment not found at: ${VENV_PYTHON}
       Create it first:
         python3 -m venv venv
         source venv/bin/activate
         pip install nicegui pyyaml"
    fi
fi

# ── Check dependencies ──
info "Checking dependencies..."

"${VENV_PYTHON}" -c "import nicegui" 2>/dev/null || {
    error "nicegui not installed in venv. Run:
         source venv/bin/activate
         pip install nicegui"
}

"${VENV_PYTHON}" -c "import yaml" 2>/dev/null || {
    error "pyyaml not installed in venv. Run:
         source venv/bin/activate
         pip install pyyaml"
}

ok "All dependencies satisfied"

# ── Detect NODE_PATH for meshcore-decoder (MQTT auth) ──
NODE_PATH_VALUE=""
if command -v node &>/dev/null; then
    NPM_GLOBAL="$(npm root -g 2>/dev/null || true)"
    if [[ -n "${NPM_GLOBAL}" ]] && [[ -d "${NPM_GLOBAL}" ]]; then
        NODE_PATH_VALUE="${NPM_GLOBAL}"
        info "Node.js global modules: ${NPM_GLOBAL}"
    fi
fi

# ── Optional settings ──
WEB_PORT="${WEB_PORT:-9093}"
ARCHIVE_DIR="${ARCHIVE_DIR:-~/.meshcore-gui/archive}"
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

# ── Config file ──
CONFIG_FLAG=""
CONFIG_FILE="${PROJECT_DIR}/observer_config.yaml"
if [[ -f "${CONFIG_FILE}" ]]; then
    CONFIG_FLAG="--config=${CONFIG_FILE}"
    info "Using config: ${CONFIG_FILE}"
else
    info "No observer_config.yaml found — using defaults"
fi

# ── Summary ──
echo ""
echo "═══════════════════════════════════════════════════"
echo " MeshCore Observer — Service Installer"
echo "═══════════════════════════════════════════════════"
echo " Project dir:  ${PROJECT_DIR}"
echo " User:         ${CURRENT_USER}"
echo " Python:       ${VENV_PYTHON}"
echo " Archive dir:  ${ARCHIVE_DIR}"
echo " Web port:     ${WEB_PORT}"
echo " Config:       ${CONFIG_FILE}"
echo " Debug:        ${DEBUG_ON}"
if [[ -n "${NODE_PATH_VALUE}" ]]; then
echo " NODE_PATH:    ${NODE_PATH_VALUE}"
fi
echo "═══════════════════════════════════════════════════"
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    info "Aborted."
    exit 0
fi

# ── Install systemd service ──
info "Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Build optional Environment line for NODE_PATH
ENV_LINE=""
if [[ -n "${NODE_PATH_VALUE}" ]]; then
    ENV_LINE="Environment=\"NODE_PATH=${NODE_PATH_VALUE}\""
fi

sudo tee "${SERVICE_FILE}" > /dev/null << SERVICE_EOF
[Unit]
Description=MeshCore Observer — Read-Only Archive Monitor Dashboard

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PYTHON} meshcore_observer.py ${CONFIG_FLAG} --port=${WEB_PORT} ${DEBUG_FLAG}
Restart=on-failure
RestartSec=30
${ENV_LINE}

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
ok "${SERVICE_NAME}.service installed and enabled"

# ── Done ──
echo ""
echo "═══════════════════════════════════════════════════"
echo -e " ${GREEN}Installation complete!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo " Commands:"
echo "   sudo systemctl start ${SERVICE_NAME}      # Start"
echo "   sudo systemctl stop ${SERVICE_NAME}       # Stop"
echo "   sudo systemctl restart ${SERVICE_NAME}    # Restart"
echo "   sudo systemctl status ${SERVICE_NAME}     # Status"
echo "   journalctl -u ${SERVICE_NAME} -f          # Live logs"
echo ""
echo " Dashboard: http://localhost:${WEB_PORT}"
echo ""
echo " Uninstall:"
echo "   bash install_scripts/install_observer.sh --uninstall"
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
