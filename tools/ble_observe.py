#!/usr/bin/env python3
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

from mc_tools.ble_observe.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
