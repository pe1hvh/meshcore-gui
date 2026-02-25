#!/usr/bin/env python3
"""
MeshCore GUI — Dual Transport Edition (Serial + BLE)
=====================================================

Thin wrapper that delegates to the package entry point.
All application logic lives in :mod:`meshcore_gui.__main__`.

Usage — Serial:
    python meshcore_gui.py /dev/ttyACM0
    python meshcore_gui.py /dev/ttyACM0 --debug-on

Usage — BLE:
    python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF
    python meshcore_gui.py literal:AA:BB:CC:DD:EE:FF --ble-pin 654321

    python -m meshcore_gui <DEVICE>

                   Author: PE1HVH
                  Version: 5.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

from meshcore_gui.__main__ import main

if __name__ == "__main__":
    main()
