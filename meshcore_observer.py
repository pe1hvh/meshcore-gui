#!/usr/bin/env python3
"""
MeshCore Observer — Read-Only Archive Monitor Dashboard
=========================================================

Standalone daemon that reads archive JSON files produced by
meshcore_gui and meshcore_bridge, aggregates them, and presents
a unified NiceGUI monitoring dashboard.  100% read-only — never
modifies archive files.

Usage:
    python meshcore_observer.py
    python meshcore_observer.py --config=observer_config.yaml
    python meshcore_observer.py --port=9093
    python meshcore_observer.py --debug-on

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

from meshcore_observer.__main__ import main

if __name__ == "__main__":
    main()
