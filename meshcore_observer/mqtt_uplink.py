"""
MQTT uplink — publishes RX log packets to LetsMesh analyzer.

Manages paho-mqtt client(s) with WebSocket+TLS transport, Ed25519 JWT
authentication, status topics with LWT, and privacy-configurable
packet type filtering.

Lifecycle::

    uplink = MqttUplink(mqtt_config, debug=True)
    uplink.start()                     # Connect to all enabled brokers
    uplink.publish_entries(new_rxlog)   # Called from timer loop
    uplink.shutdown()                   # Graceful disconnect

Thread safety: paho-mqtt ``loop_start()`` runs its own network thread.
``publish_entries()`` is safe to call from the NiceGUI timer thread.

                   Author: PE1HVH
                  Version: 1.0.0
  SPDX-License-Identifier: MIT
                Copyright: (c) 2026 PE1HVH
"""

import json
import logging
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from meshcore_observer.config import MqttBrokerConfig, MqttConfig
from meshcore_observer.auth_token import TokenManager

logger = logging.getLogger(__name__)

# Packet type name lookup (for debug logging)
PACKET_TYPE_NAMES = {
    0: "REQ", 1: "RESPONSE", 2: "TXT_MSG", 3: "ACK", 4: "ADVERT",
    5: "GRP_TXT", 6: "GRP_DATA", 7: "ANON_REQ", 8: "PATH", 9: "TRACE",
}


@dataclass
class BrokerState:
    """Runtime state for a single broker connection.

    Attributes:
        config:           Broker configuration.
        client:           paho-mqtt client instance.
        connected:        Whether currently connected.
        packets_published: Total packets published to this broker.
        last_publish_time: Timestamp of last successful publish.
        last_error:       Last error message, if any.
        reconnect_count:  Number of reconnection attempts.
    """

    config: MqttBrokerConfig
    client: object = None  # paho.mqtt.client.Client
    connected: bool = False
    packets_published: int = 0
    last_publish_time: Optional[str] = None
    last_error: str = ""
    reconnect_count: int = 0


class MqttUplink:
    """MQTT uplink to LetsMesh analyzer brokers.

    Manages one or more paho-mqtt clients, each connecting to a
    configured broker via WebSocket+TLS.  Publishes RX log entries
    as LetsMesh-compatible JSON payloads on ``meshcore/{IATA}/{KEY}/packets``.

    Args:
        mqtt_config: Validated MqttConfig instance.
        debug:       Enable verbose debug logging.
    """

    def __init__(self, mqtt_config: MqttConfig, debug: bool = False) -> None:
        self._cfg = mqtt_config
        self._debug = debug
        self._lock = threading.Lock()

        # Resolved identity
        self._public_key = mqtt_config.resolve_public_key().upper()
        self._private_key = mqtt_config.resolve_private_key()
        self._device_name = mqtt_config.resolve_device_name()
        self._iata = mqtt_config.iata.upper()

        # Token manager
        self._token_mgr = TokenManager(
            self._public_key,
            self._private_key,
            mqtt_config.token_lifetime_s,
        )

        # Topic paths
        self._topic_base = f"meshcore/{self._iata}/{self._public_key}"
        self._topic_packets = f"{self._topic_base}/packets"
        self._topic_status = f"{self._topic_base}/status"

        # Privacy filter
        self._allowed_types: Optional[set] = None
        if mqtt_config.upload_packet_types:
            self._allowed_types = set(mqtt_config.upload_packet_types)

        # Broker states
        self._brokers: Dict[str, BrokerState] = {}

        # Aggregate stats
        self._total_published: int = 0
        self._total_filtered: int = 0
        self._total_skipped_no_raw: int = 0
        self._started: bool = False

        # Status republish tracking
        self._last_status_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to all enabled brokers and publish online status.

        Creates paho-mqtt clients, configures auth, TLS, LWT, and
        starts the network loop.  Non-blocking — network threads run
        in the background.
        """
        try:
            import paho.mqtt.client as paho_mqtt
        except ImportError:
            logger.error(
                "paho-mqtt is required for MQTT uplink. "
                "Install with: pip install paho-mqtt"
            )
            return

        enabled_brokers = [b for b in self._cfg.brokers if b.enabled]
        if not enabled_brokers:
            logger.warning("MQTT enabled but no brokers configured")
            return

        for broker_cfg in enabled_brokers:
            state = BrokerState(config=broker_cfg)

            # Client ID
            client_id = f"meshcore_observer_{self._public_key[:8]}"
            if len(enabled_brokers) > 1:
                client_id += f"_{broker_cfg.name}"

            try:
                # paho-mqtt v2.x API
                client = paho_mqtt.Client(
                    callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
                    client_id=client_id,
                    transport=broker_cfg.transport,
                    protocol=paho_mqtt.MQTTv311,
                )
            except (TypeError, AttributeError):
                # Fallback for paho-mqtt v1.x
                client = paho_mqtt.Client(
                    client_id=client_id,
                    transport=broker_cfg.transport,
                    protocol=paho_mqtt.MQTTv311,
                )

            state.client = client

            # Auth: username + JWT password
            username = self._token_mgr.username
            password = self._token_mgr.get_token(broker_cfg.server)
            client.username_pw_set(username, password)

            # TLS
            if broker_cfg.tls:
                client.tls_set(
                    cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )

            # LWT (Last Will and Testament)
            lwt_payload = json.dumps({
                "status": "offline",
                "origin": self._device_name,
                "origin_id": self._public_key,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            client.will_set(
                self._topic_status,
                payload=lwt_payload,
                qos=1,
                retain=True,
            )

            # Callbacks
            client.on_connect = self._make_on_connect(broker_cfg.name)
            client.on_disconnect = self._make_on_disconnect(broker_cfg.name)

            self._brokers[broker_cfg.name] = state

            # Connect
            if self._cfg.dry_run:
                logger.info(
                    "[DRY RUN] Would connect to %s:%d (%s)",
                    broker_cfg.server, broker_cfg.port, broker_cfg.name,
                )
                continue

            try:
                logger.info(
                    "Connecting to MQTT broker %s (%s:%d)...",
                    broker_cfg.name, broker_cfg.server, broker_cfg.port,
                )
                client.connect_async(broker_cfg.server, broker_cfg.port)
                client.loop_start()
            except Exception as exc:
                state.last_error = str(exc)
                logger.error(
                    "Failed to connect to %s: %s", broker_cfg.name, exc,
                )

        self._started = True

    def publish_entries(self, new_rxlog: List[Tuple[str, dict]]) -> int:
        """Publish new RX log entries to all connected brokers.

        Filters by packet type, skips entries without ``raw_payload``,
        transforms to LetsMesh format, and publishes to each broker.

        Args:
            new_rxlog: List of (source_address, entry_dict) tuples from
                       ArchiveWatcher.poll().

        Returns:
            Number of entries published (per broker).
        """
        if not self._started or not new_rxlog:
            return 0

        published_count = 0

        for source_addr, entry in new_rxlog:
            # Skip entries without raw_payload (pre-Fase1 archives)
            raw = entry.get("raw_payload", "")
            if not raw:
                self._total_skipped_no_raw += 1
                if self._debug:
                    logger.debug(
                        "Skipping entry without raw_payload: %s",
                        entry.get("message_hash", "?")[:12],
                    )
                continue

            # Privacy filter: check packet type
            pkt_type = entry.get("packet_type_num")
            if self._allowed_types is not None and pkt_type is not None:
                if int(pkt_type) not in self._allowed_types:
                    self._total_filtered += 1
                    if self._debug:
                        type_name = PACKET_TYPE_NAMES.get(int(pkt_type), str(pkt_type))
                        logger.debug(
                            "Filtered packet type %s (%s)", pkt_type, type_name,
                        )
                    continue

            # Transform to LetsMesh payload format
            payload = self._transform_entry(entry, source_addr)
            payload_json = json.dumps(payload)

            if self._cfg.dry_run:
                logger.info("[DRY RUN] Would publish: %s", payload_json[:200])
                published_count += 1
                continue

            # Publish to each connected broker
            for name, state in self._brokers.items():
                if not state.connected or state.client is None:
                    continue

                try:
                    result = state.client.publish(
                        self._topic_packets,
                        payload=payload_json,
                        qos=0,
                    )
                    if result.rc == 0:
                        with self._lock:
                            state.packets_published += 1
                            state.last_publish_time = datetime.now(
                                timezone.utc
                            ).isoformat()
                        published_count += 1
                    else:
                        logger.warning(
                            "Publish to %s returned rc=%d", name, result.rc,
                        )
                except Exception as exc:
                    state.last_error = str(exc)
                    logger.error("Publish error on %s: %s", name, exc)

        with self._lock:
            self._total_published += published_count

        # Periodic status republish
        self._maybe_republish_status()

        return published_count

    def shutdown(self) -> None:
        """Graceful shutdown — publish offline status and disconnect."""
        if not self._started:
            return

        logger.info("Shutting down MQTT uplink...")

        for name, state in self._brokers.items():
            if state.client is None:
                continue

            if state.connected and not self._cfg.dry_run:
                # Publish offline status before disconnect
                try:
                    offline_payload = json.dumps({
                        "status": "offline",
                        "origin": self._device_name,
                        "origin_id": self._public_key,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    state.client.publish(
                        self._topic_status,
                        payload=offline_payload,
                        qos=1,
                        retain=True,
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not publish offline status to %s: %s",
                        name, exc,
                    )

            try:
                state.client.loop_stop()
                state.client.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting from %s: %s", name, exc)

        self._started = False
        logger.info("MQTT uplink stopped")

    def get_status(self) -> Dict:
        """Return current MQTT status for dashboard display.

        Returns:
            Dict with enabled, dry_run, brokers status, totals.
        """
        with self._lock:
            broker_statuses = []
            for name, state in self._brokers.items():
                broker_statuses.append({
                    "name": name,
                    "server": state.config.server,
                    "connected": state.connected,
                    "packets_published": state.packets_published,
                    "last_publish_time": state.last_publish_time or "-",
                    "last_error": state.last_error,
                })

            return {
                "enabled": self._cfg.enabled,
                "dry_run": self._cfg.dry_run,
                "started": self._started,
                "iata": self._iata,
                "public_key_short": self._public_key[:12] + "...",
                "topic_base": self._topic_base,
                "brokers": broker_statuses,
                "total_published": self._total_published,
                "total_filtered": self._total_filtered,
                "total_skipped_no_raw": self._total_skipped_no_raw,
                "upload_filter": (
                    [PACKET_TYPE_NAMES.get(t, str(t)) for t in sorted(self._allowed_types)]
                    if self._allowed_types
                    else "ALL"
                ),
            }

    # ------------------------------------------------------------------
    # Internal: transform + publish helpers
    # ------------------------------------------------------------------

    def _transform_entry(self, entry: dict, source_addr: str) -> dict:
        """Transform an archive RX log entry to LetsMesh payload format.

        Args:
            entry:       RX log entry dict from archive JSON.
            source_addr: Source address from archive file.

        Returns:
            LetsMesh-compatible payload dict.
        """
        # Parse timestamp for date/time fields
        ts_utc = entry.get("timestamp_utc", "")
        time_str = entry.get("time", "")
        date_str = ""

        if ts_utc:
            try:
                dt = datetime.fromisoformat(ts_utc)
                if not time_str:
                    time_str = dt.strftime("%H:%M:%S")
                # LetsMesh format: DD/M/YYYY
                date_str = f"{dt.day}/{dt.month}/{dt.year}"
            except (ValueError, AttributeError):
                pass

        return {
            "origin": self._device_name,
            "origin_id": self._public_key,
            "timestamp": ts_utc or datetime.now(timezone.utc).isoformat(),
            "type": "PACKET",
            "direction": "rx",
            "time": time_str,
            "date": date_str,
            "len": str(entry.get("packet_len", "")),
            "packet_type": str(entry.get("packet_type_num", "")),
            "route": str(entry.get("route_type", "")),
            "payload_len": str(entry.get("payload_len", "")),
            "raw": entry.get("raw_payload", ""),
            "SNR": str(entry.get("snr", "")),
            "RSSI": str(entry.get("rssi", "")),
            "score": "1000",
            "hash": entry.get("message_hash", ""),
        }

    def _publish_online_status(self, broker_name: str) -> None:
        """Publish online status to a specific broker.

        Args:
            broker_name: Name of the broker to publish to.
        """
        state = self._brokers.get(broker_name)
        if not state or not state.client or not state.connected:
            return

        status_payload = json.dumps({
            "status": "online",
            "origin": self._device_name,
            "origin_id": self._public_key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "stats": {
                "uptime_s": 0,
                "packets_published": state.packets_published,
                "sources_active": 0,
            },
        })

        try:
            state.client.publish(
                self._topic_status,
                payload=status_payload,
                qos=1,
                retain=True,
            )
            logger.info("Published online status to %s", broker_name)
        except Exception as exc:
            logger.error(
                "Failed to publish status to %s: %s", broker_name, exc,
            )

    def _maybe_republish_status(self) -> None:
        """Republish status if interval has elapsed."""
        if self._cfg.status_interval_s <= 0:
            return

        now = time.monotonic()
        if now - self._last_status_time < self._cfg.status_interval_s:
            return

        self._last_status_time = now

        for name in self._brokers:
            self._publish_online_status(name)

    # ------------------------------------------------------------------
    # Internal: paho-mqtt callbacks
    # ------------------------------------------------------------------

    def _make_on_connect(self, broker_name: str):
        """Create an on_connect callback for a specific broker.

        Args:
            broker_name: Broker label for logging.

        Returns:
            Callback function for paho-mqtt.
        """
        def on_connect(client, userdata, flags, rc, *args):
            if rc == 0:
                logger.info("Connected to MQTT broker: %s", broker_name)
                with self._lock:
                    state = self._brokers.get(broker_name)
                    if state:
                        state.connected = True
                        state.last_error = ""
                        state.reconnect_count = 0
                self._publish_online_status(broker_name)
            else:
                error_msg = f"Connection refused (rc={rc})"
                logger.error(
                    "MQTT connection to %s failed: %s", broker_name, error_msg,
                )
                with self._lock:
                    state = self._brokers.get(broker_name)
                    if state:
                        state.connected = False
                        state.last_error = error_msg

        return on_connect

    def _make_on_disconnect(self, broker_name: str):
        """Create an on_disconnect callback for a specific broker.

        Args:
            broker_name: Broker label for logging.

        Returns:
            Callback function for paho-mqtt.
        """
        def on_disconnect(client, userdata, flags_or_rc, rc=None, *args):
            # Handle both v1.x and v2.x callback signatures
            actual_rc = rc if rc is not None else flags_or_rc

            logger.warning(
                "Disconnected from MQTT broker %s (rc=%s)",
                broker_name, actual_rc,
            )
            with self._lock:
                state = self._brokers.get(broker_name)
                if state:
                    state.connected = False
                    state.reconnect_count += 1

                    # Refresh token on reconnect
                    self._token_mgr.invalidate()
                    try:
                        password = self._token_mgr.get_token(
                            state.config.server
                        )
                        client.username_pw_set(
                            self._token_mgr.username, password,
                        )
                    except Exception as exc:
                        state.last_error = f"Token refresh failed: {exc}"
                        logger.error(
                            "Token refresh failed for %s: %s",
                            broker_name, exc,
                        )

            # paho-mqtt auto-reconnects when loop_start() is active

        return on_disconnect
