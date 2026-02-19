"""
Automatic BLE reconnect with bond cleanup via D-Bus.

Replaces manual ``bluetoothctl remove`` steps.  Provides two
functions:

- :func:`remove_bond` — removes a BLE bond via D-Bus
  (equivalent of ``bluetoothctl remove <address>``)
- :func:`reconnect_loop` — linear backoff reconnect with
  automatic bond cleanup

Both functions are async and can be called directly in the
BLEWorker's asyncio event loop.

                   Author: PE1HVH / Claude
  SPDX-License-Identifier: MIT
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from dbus_fast.aio import MessageBus
from dbus_fast import BusType

logger = logging.getLogger(__name__)


async def remove_bond(device_address: str) -> bool:
    """Remove BLE bond via D-Bus.

    Equivalent of::

        bluetoothctl remove <address>

    Args:
        device_address: BLE MAC address (e.g. ``"FF:05:D6:71:83:8D"``).
            The ``literal:`` prefix is automatically stripped.

    Returns:
        True if the bond was successfully removed, False on error
        (e.g. if the device was already removed).
    """
    # Strip 'literal:' prefix if present
    clean_address = device_address.replace("literal:", "")
    dev_path = "/org/bluez/hci0/dev_" + clean_address.replace(":", "_")

    bus = None
    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        introspection = await bus.introspect("org.bluez", "/org/bluez/hci0")
        proxy = bus.get_proxy_object(
            "org.bluez", "/org/bluez/hci0", introspection
        )
        adapter = proxy.get_interface("org.bluez.Adapter1")
        await adapter.call_remove_device(dev_path)
        logger.info(f"Bond removed for {clean_address}")
        print(f"BLE: Bond removed for {clean_address}")
        return True
    except Exception as e:
        # "Does Not Exist" is normal if the device was already removed
        error_str = str(e)
        if "DoesNotExist" in error_str or "Does Not Exist" in error_str:
            logger.debug(f"Bond already removed for {clean_address}")
            print(f"BLE: Bond already removed for {clean_address}")
        else:
            logger.warning(f"Bond removal failed: {e}")
            print(f"BLE: ⚠️  Bond removal failed: {e}")
        return False
    finally:
        if bus:
            bus.disconnect()


async def reconnect_loop(
    create_connection_func: Callable[[], Coroutine[Any, Any, Any]],
    device_address: str,
    max_retries: int = 5,
    base_delay: float = 5.0,
) -> Optional[Any]:
    """Reconnect loop: remove bond, wait, reconnect.

    Uses linear backoff: the wait time increases with each failed
    attempt (5s, 10s, 15s, 20s, 25s).

    Args:
        create_connection_func: Async function that creates a new BLE
            connection and returns the ``MeshCore`` object.
        device_address: BLE MAC address.
        max_retries: Maximum number of attempts per disconnect.
        base_delay: Base delay in seconds (multiplied by attempt number).

    Returns:
        The new ``MeshCore`` object on success, or ``None`` if all
        attempts failed.
    """
    for attempt in range(1, max_retries + 1):
        delay = base_delay * attempt
        logger.info(
            f"Reconnect attempt {attempt}/{max_retries} in {delay:.0f}s..."
        )
        print(
            f"BLE: 🔄 Reconnect attempt {attempt}/{max_retries} "
            f"in {delay:.0f}s..."
        )
        await asyncio.sleep(delay)

        # Step 1: Remove stale bond
        await remove_bond(device_address)
        await asyncio.sleep(2)

        # Step 2: Try to reconnect
        try:
            connection = await create_connection_func()
            logger.info(f"Reconnected after attempt {attempt}")
            print(f"BLE: ✅ Reconnected after attempt {attempt}")
            return connection
        except Exception as e:
            logger.error(f"Reconnect attempt {attempt} failed: {e}")
            print(f"BLE: ❌ Reconnect attempt {attempt} failed: {e}")

    logger.error(f"Reconnect failed after {max_retries} attempts")
    print(f"BLE: ❌ Reconnect failed after {max_retries} attempts")
    return None
