"""
BLE bond manager via ``meshcore-ble-connect`` subprocess.

Wraps the standalone ``meshcore-ble-connect`` CLI tool (v1.1.0+) which
manages the full BLE bond lifecycle via D-Bus: discovery, pairing with
PIN (BLE SMP), trust, and bond verification.  The tool is idempotent
and safe to call repeatedly.

This module replaces the built-in :class:`BleAgentManager` and the
``_ensure_paired()`` / ``remove_bond()`` flow in the BLE worker.  The
``meshcore-ble-connect`` tool handles all BlueZ version differences
internally — no more ``NEEDS_PREPAIR`` branching needed.

Graceful degradation: if ``meshcore-ble-connect`` is not installed,
all functions log a warning and return success so the legacy flow
(BleAgentManager + bleak pairing) can still be used as fallback.

Exit codes from ``meshcore-ble-connect``:

+------+----------------------------+-------------------------------+
| Code | Meaning                    | GUI action                    |
+------+----------------------------+-------------------------------+
|  0   | Bond OK                    | Proceed with bleak connect    |
|  1   | No bond (--check-only)     | N/A (not used here)           |
|  2   | Pairing failed             | Show error, retry later       |
|  3   | Adapter problem            | Show "BT adapter not found"   |
|  4   | D-Bus permission error     | Show "Insufficient rights"    |
+------+----------------------------+-------------------------------+

                   Author: PE1HVH / Claude
  SPDX-License-Identifier: MIT
"""

import asyncio
import logging
import shutil
import subprocess
from typing import Optional, Tuple

from meshcore_gui.config import debug_print

logger = logging.getLogger(__name__)

# Timeout in seconds for the meshcore-ble-connect subprocess.
BLE_CONNECT_TIMEOUT: int = 60

# Human-readable error messages per exit code.
_EXIT_CODE_MESSAGES: dict[int, str] = {
    2: "❌ BLE pairing failed — check PIN and device",
    3: "❌ Bluetooth adapter not found",
    4: "❌ Insufficient D-Bus permissions — check system config",
}

# Cache the availability check so we only look up the binary once.
_tool_available: Optional[bool] = None


def is_ble_connect_available() -> bool:
    """Check whether ``meshcore-ble-connect`` is on PATH.

    The result is cached after the first call so repeated checks are
    essentially free.

    Returns:
        True if the tool is found, False otherwise.
    """
    global _tool_available
    if _tool_available is None:
        _tool_available = shutil.which("meshcore-ble-connect") is not None
        if _tool_available:
            logger.info("meshcore-ble-connect found on PATH")
            print("BLE: ✅ meshcore-ble-connect found on PATH")
        else:
            logger.warning(
                "meshcore-ble-connect NOT found on PATH — "
                "falling back to legacy BLE agent"
            )
            print(
                "BLE: ⚠️  meshcore-ble-connect not installed — "
                "using legacy BLE agent fallback"
            )
    return _tool_available


async def ensure_bond(
    mac: str,
    pin: Optional[str] = None,
    timeout: int = BLE_CONNECT_TIMEOUT,
) -> Tuple[bool, int, str]:
    """Ensure BLE bond is valid via ``meshcore-ble-connect``.

    Calls the external tool as a subprocess.  If the tool is not
    installed, returns success immediately (graceful degradation).

    Args:
        mac:     BLE MAC address (``literal:`` prefix is stripped).
        pin:     Optional pairing PIN.  When ``None`` the tool runs
                 without ``--pin`` (interactive / agent-based pairing).
        timeout: Subprocess timeout in seconds.

    Returns:
        Tuple of ``(success, exit_code, message)``:

        - ``success``: True when the bond is valid (exit code 0) or
          when the tool is not installed (fallback).
        - ``exit_code``: The process exit code (0 on fallback).
        - ``message``: Human-readable status or error message.
    """
    if not is_ble_connect_available():
        return True, 0, "meshcore-ble-connect not installed — skipped"

    # Strip 'literal:' prefix if present (meshcore-ble-connect expects
    # a plain MAC address).
    clean_mac = mac.replace("literal:", "")

    cmd = ["meshcore-ble-connect", clean_mac]
    if pin:
        cmd.extend(["--pin", pin])

    debug_print(f"Running: {' '.join(cmd)} (timeout={timeout}s)")
    logger.info("Calling meshcore-ble-connect for %s", clean_mac)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        rc = result.returncode

        if rc == 0:
            msg = "BLE bond OK"
            debug_print(f"meshcore-ble-connect: {msg}")
            logger.info(msg)
            return True, 0, msg

        # Non-zero exit code — log stderr for diagnostics
        stderr = result.stderr.strip()
        if stderr:
            debug_print(f"meshcore-ble-connect stderr: {stderr}")
            logger.debug("meshcore-ble-connect stderr: %s", stderr)

        msg = _EXIT_CODE_MESSAGES.get(rc, f"❌ meshcore-ble-connect failed (exit {rc})")
        logger.warning("meshcore-ble-connect failed: rc=%d msg=%s", rc, msg)
        print(f"BLE: {msg}")
        return False, rc, msg

    except subprocess.TimeoutExpired:
        msg = f"❌ meshcore-ble-connect timed out after {timeout}s"
        logger.error(msg)
        print(f"BLE: {msg}")
        return False, -1, msg

    except FileNotFoundError:
        # Race condition: tool was on PATH at startup but removed since.
        global _tool_available
        _tool_available = False
        msg = "meshcore-ble-connect disappeared from PATH — skipped"
        logger.warning(msg)
        return True, 0, msg

    except Exception as exc:
        msg = f"❌ meshcore-ble-connect error: {exc}"
        logger.error(msg)
        debug_print(msg)
        return False, -1, msg
