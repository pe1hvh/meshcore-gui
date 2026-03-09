#!/usr/bin/env python3
"""
MeshCore Bridge — Cross-Frequency Message Bridge Daemon
========================================================

Standalone daemon that connects two meshcore_gui instances on
different frequencies by forwarding messages on a configurable
bridge channel.  Requires zero modifications to the existing
meshcore_gui codebase.

Usage:
    python meshcore_bridge.py
    python meshcore_bridge.py --config=bridge_config.yaml
    python meshcore_bridge.py --port=9092
    python meshcore_bridge.py --debug-on

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

from meshcore_bridge.__main__ import main

if __name__ == "__main__":
    main()
