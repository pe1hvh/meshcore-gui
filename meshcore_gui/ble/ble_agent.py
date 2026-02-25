"""
Ingebouwde BlueZ D-Bus agent voor MeshCore BLE PIN pairing.

Vervangt de externe ``bt-agent.service`` (bluez-tools).
Gebruikt ``dbus_fast`` (async, al dependency van bleak).

De agent registreert zich bij BlueZ als default pairing agent en
beantwoordt PIN/passkey-verzoeken automatisch met de geconfigureerde
PIN (standaard ``123456`` voor T1000e).

Referentie
~~~~~~~~~~
- BlueZ Agent1 API: https://github.com/bluez/bluez/blob/master/doc/agent-api.txt
- mdphoto/meshecore-gui: https://github.com/mdphoto/meshecore-gui/blob/main/src/ble_agent.py
- dbus_fast: https://github.com/Bluetooth-Devices/dbus-fast

                   Author: PE1HVH / Claude
  SPDX-License-Identifier: MIT
"""

import logging

from dbus_fast.aio import MessageBus
from dbus_fast import BusType
from dbus_fast.service import ServiceInterface, method

logger = logging.getLogger(__name__)

AGENT_PATH = "/meshcore/ble_agent"
CAPABILITY = "KeyboardOnly"


class BluezAgent(ServiceInterface):
    """BlueZ pairing agent die automatisch PIN afhandelt.

    Implementeert de ``org.bluez.Agent1`` interface.  Alle pairing-
    gerelateerde callbacks geven de geconfigureerde PIN terug of
    accepteren het verzoek stilzwijgend.
    """

    def __init__(self, pin: str = "123456") -> None:
        super().__init__("org.bluez.Agent1")
        self.pin = pin

    @method()
    def Release(self) -> None:
        logger.info("BLE Agent released")

    @method()
    def RequestPinCode(self, device: 'o') -> 's':
        logger.info(f"PIN requested for {device}, providing: {self.pin}")
        return self.pin

    @method()
    def RequestPasskey(self, device: 'o') -> 'u':
        logger.info(f"Passkey requested for {device}, providing: {self.pin}")
        return int(self.pin)

    @method()
    def DisplayPasskey(self, device: 'o', passkey: 'u', entered: 'q') -> None:
        logger.info(f"Passkey display: {passkey} (entered: {entered})")

    @method()
    def DisplayPinCode(self, device: 'o', pincode: 's') -> None:
        logger.info(f"PIN display: {pincode}")

    @method()
    def RequestConfirmation(self, device: 'o', passkey: 'u') -> None:
        logger.info(f"Confirming passkey {passkey} for {device}")

    @method()
    def RequestAuthorization(self, device: 'o') -> None:
        logger.info(f"Authorizing {device}")

    @method()
    def AuthorizeService(self, device: 'o', uuid: 's') -> None:
        logger.info(f"Authorizing service {uuid} for {device}")

    @method()
    def Cancel(self) -> None:
        logger.info("Pairing cancelled")


class BleAgentManager:
    """Beheert registratie/deregistratie van de BlueZ agent.

    Gebruik::

        agent = BleAgentManager(pin="123456")
        await agent.start()   # Registreer VOOR BLE connect
        ...
        await agent.stop()    # Deregistreer bij afsluiten

    De manager verbindt met de system D-Bus, exporteert de agent op
    ``AGENT_PATH`` en registreert deze als default agent bij BlueZ.
    """

    def __init__(self, pin: str = "123456") -> None:
        self.pin = pin
        self.bus: MessageBus | None = None
        self.agent: BluezAgent | None = None
        self._registered = False

    @property
    def is_registered(self) -> bool:
        """True als de agent succesvol geregistreerd is bij BlueZ."""
        return self._registered

    async def start(self) -> None:
        """Registreer agent bij BlueZ.  Aanroepen VOOR BLE connect."""
        try:
            self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            self.agent = BluezAgent(self.pin)
            self.bus.export(AGENT_PATH, self.agent)

            introspection = await self.bus.introspect("org.bluez", "/org/bluez")
            proxy = self.bus.get_proxy_object(
                "org.bluez", "/org/bluez", introspection
            )
            agent_manager = proxy.get_interface("org.bluez.AgentManager1")

            await agent_manager.call_register_agent(AGENT_PATH, CAPABILITY)
            await agent_manager.call_request_default_agent(AGENT_PATH)
            self._registered = True
            logger.info(f"BLE agent geregistreerd met PIN {self.pin}")
            print(f"BLE: PIN agent geregistreerd (PIN {self.pin})")
        except Exception as e:
            logger.error(f"BLE agent registratie mislukt: {e}")
            print(f"BLE: ⚠️  PIN agent registratie mislukt: {e}")
            print(
                "BLE: Tip — controleer D-Bus permissies of "
                "installeer /etc/dbus-1/system.d/meshcore-ble.conf"
            )

    async def stop(self) -> None:
        """Deregistreer agent bij BlueZ."""
        if self.bus and self._registered:
            try:
                introspection = await self.bus.introspect(
                    "org.bluez", "/org/bluez"
                )
                proxy = self.bus.get_proxy_object(
                    "org.bluez", "/org/bluez", introspection
                )
                agent_manager = proxy.get_interface("org.bluez.AgentManager1")
                await agent_manager.call_unregister_agent(AGENT_PATH)
            except Exception as e:
                logger.warning(f"Agent deregistratie mislukt: {e}")
            self._registered = False

        if self.bus:
            self.bus.disconnect()
            self.bus = None
            logger.info("BLE agent gestopt")
            print("BLE: PIN agent gestopt")
