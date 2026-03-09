"""BLE observe tool entrypoint.

Usage:
    python -m tools.ble_observe [options]
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
