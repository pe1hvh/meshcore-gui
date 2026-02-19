"""
Built-in BlueZ D-Bus agent for MeshCore BLE PIN pairing.

Replaces the external ``bt-agent.service`` (bluez-tools).
Uses ``dbus_fast`` (async, already a dependency of bleak).

The agent registers with BlueZ as the default pairing agent and
answers PIN/passkey requests automatically with the configured
PIN (default ``123456`` for T1000e).

References
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
    """BlueZ pairing agent that handles PIN requests automatically.

    Implements the ``org.bluez.Agent1`` interface.  All pairing-related
    callbacks return the configured PIN or silently accept the request.
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
    """Manages registration/deregistration of the BlueZ pairing agent.

    Usage::

        agent = BleAgentManager(pin="123456")
        await agent.start()   # Register BEFORE BLE connect
        ...
        await agent.stop()    # Deregister on shutdown

    The manager connects to the system D-Bus, exports the agent on
    ``AGENT_PATH`` and registers it as the default agent with BlueZ.
    """

    def __init__(self, pin: str = "123456") -> None:
        self.pin = pin
        self.bus: MessageBus | None = None
        self.agent: BluezAgent | None = None
        self._registered = False

    @property
    def is_registered(self) -> bool:
        """True if the agent was successfully registered with BlueZ."""
        return self._registered

    async def start(self) -> None:
        """Register agent with BlueZ.  Call BEFORE BLE connect."""
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
            logger.info(f"BLE agent registered with PIN {self.pin}")
            print(f"BLE: PIN agent registered (PIN {self.pin})")
        except Exception as e:
            logger.error(f"BLE agent registration failed: {e}")
            print(f"BLE: ⚠️  PIN agent registration failed: {e}")
            print(
                "BLE: Tip — check D-Bus permissions or "
                "install /etc/dbus-1/system.d/meshcore-ble.conf"
            )

    async def stop(self) -> None:
        """Deregister agent from BlueZ."""
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
                logger.warning(f"Agent deregistration failed: {e}")
            self._registered = False

        if self.bus:
            self.bus.disconnect()
            self.bus = None
            logger.info("BLE agent stopped")
            print("BLE: PIN agent stopped")
