"""
Automatische BLE reconnect met bond-opruiming via D-Bus.

Vervangt handmatige ``bluetoothctl remove`` stappen.  Biedt twee
functies:

- :func:`remove_bond` — verwijdert een BLE bond via D-Bus
  (equivalent van ``bluetoothctl remove <address>``)
- :func:`reconnect_loop` — exponential backoff reconnect met
  automatische bond-opruiming

Beide functies zijn async en kunnen direct in de BLEWorker's
asyncio event loop worden aangeroepen.

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
    """Verwijder BLE bond via D-Bus.

    Equivalent van::

        bluetoothctl remove <address>

    Args:
        device_address: BLE MAC-adres (bijv. ``"FF:05:D6:71:83:8D"``).
            Het ``literal:`` prefix wordt automatisch verwijderd.

    Returns:
        True als de bond succesvol verwijderd is, False bij een fout
        (bijv. als het device al verwijderd was).
    """
    # Strip 'literal:' prefix als aanwezig
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
        logger.info(f"Bond verwijderd voor {clean_address}")
        print(f"BLE: Bond verwijderd voor {clean_address}")
        return True
    except Exception as e:
        # "Does Not Exist" is normaal als device al verwijderd was
        error_str = str(e)
        if "DoesNotExist" in error_str or "Does Not Exist" in error_str:
            logger.debug(f"Bond al verwijderd voor {clean_address}")
            print(f"BLE: Bond was al verwijderd voor {clean_address}")
        else:
            logger.warning(f"Bond verwijdering mislukt: {e}")
            print(f"BLE: ⚠️  Bond verwijdering mislukt: {e}")
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
    """Reconnect-loop: bond verwijderen, wachten, opnieuw verbinden.

    Gebruikt exponential backoff: de wachttijd verdubbelt bij elke
    mislukte poging (5s, 10s, 15s, 20s, 25s).

    Args:
        create_connection_func: Async functie die een nieuwe BLE-
            verbinding opzet en het ``MeshCore`` object teruggeeft.
        device_address: BLE MAC-adres.
        max_retries: Maximaal aantal pogingen per disconnect.
        base_delay: Basis wachttijd in seconden (vermenigvuldigt
            met poging-nummer).

    Returns:
        Het nieuwe ``MeshCore`` object bij succes, of ``None`` als
        alle pogingen mislukt zijn.
    """
    for attempt in range(1, max_retries + 1):
        delay = base_delay * attempt
        logger.info(
            f"Reconnect poging {attempt}/{max_retries} over {delay:.0f}s..."
        )
        print(
            f"BLE: 🔄 Reconnect poging {attempt}/{max_retries} "
            f"over {delay:.0f}s..."
        )
        await asyncio.sleep(delay)

        # Stap 1: Verwijder de stale bond
        await remove_bond(device_address)
        await asyncio.sleep(2)

        # Stap 2: Probeer opnieuw te verbinden
        try:
            connection = await create_connection_func()
            logger.info(f"Herverbonden na poging {attempt}")
            print(f"BLE: ✅ Herverbonden na poging {attempt}")
            return connection
        except Exception as e:
            logger.error(f"Reconnect poging {attempt} mislukt: {e}")
            print(f"BLE: ❌ Reconnect poging {attempt} mislukt: {e}")

    logger.error(f"Reconnect mislukt na {max_retries} pogingen")
    print(f"BLE: ❌ Reconnect mislukt na {max_retries} pogingen")
    return None
