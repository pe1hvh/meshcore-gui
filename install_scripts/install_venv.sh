#!/usr/bin/env bash
# ============================================================================
# MeshCore GUI — Virtual Environment Setup
# ============================================================================
#
# Creates a venv and installs core Python dependencies.
#
# Usage:
#   bash install_scripts/install_venv.sh         # from project root
#   cd install_scripts && bash install_venv.sh   # from install_scripts/
#
# ============================================================================

set -euo pipefail

# ── Resolve project root ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "${SCRIPT_DIR}")" == "install_scripts" ]]; then
    PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
else
    PROJECT_DIR="${SCRIPT_DIR}"
fi

cd "${PROJECT_DIR}"

echo "Creating virtual environment in ${PROJECT_DIR}/venv ..."
python3 -m venv venv
source venv/bin/activate
pip install nicegui meshcore bleak meshcoredecoder
echo "Done. Activate with: source ${PROJECT_DIR}/venv/bin/activate"
