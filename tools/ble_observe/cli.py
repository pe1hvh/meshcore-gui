from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure local src/ is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from transport import (
    BleakTransport,
    ensure_exclusive_access,
    OwnershipError,
    DiscoveryError,
    ConnectionError,
    NotificationError,
    exitcodes,
)

NUS_CHAR_NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


NUS_CHAR_WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host -> device (Companion protocol write)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ble-observe", description="MeshCore BLE observe (read-only)")
    p.add_argument("--scan-only", action="store_true", help="Only scan and list devices")
    p.add_argument("--address", type=str, help="BLE address (e.g. FF:05:D6:71:83:8D)")
    p.add_argument("--scan-seconds", type=float, default=5.0, help="Scan duration")
    p.add_argument("--pre-scan-seconds", type=float, default=5.0, help="Pre-scan before connect")
    p.add_argument("--connect-timeout", type=float, default=20.0, help="Connect timeout")
    p.add_argument("--notify", action="store_true", help="Listen for notifications (read-only)")
    p.add_argument("--app-start", action="store_true", help="Send CMD_APP_START (0x01) before enabling notify (protocol write)")
    p.add_argument("--notify-seconds", type=float, default=10.0, help="Notify listen duration")
    return p

async def scan(scan_seconds: float) -> int:
    t = BleakTransport()
    devices = await t.discover(timeout=scan_seconds)
    for d in devices:
        name = d.name or ""
        rssi = "" if d.rssi is None else str(d.rssi)
        print(f"{d.address}\t{name}\t{rssi}")
    return exitcodes.OK

async def observe(address: str, *, pre_scan: float, connect_timeout: float, notify: bool, notify_seconds: float, app_start: bool) -> int:
    await ensure_exclusive_access(address, pre_scan_seconds=pre_scan)
    t = BleakTransport(allow_write=bool(app_start))
    await t.connect(address, timeout=connect_timeout)
    try:
        services = await t.get_services()
        print("SERVICES:")
        for svc in services:
            print(f"- {svc.uuid}")
        if notify:
            if app_start:
                # Companion BLE handshake: CMD_APP_START (0x01)
                await t.write(NUS_CHAR_WRITE_UUID, bytes([0x01]), response=False)
                await asyncio.sleep(0.1)
            def on_rx(data: bytearray) -> None:
                print(data.hex())
            await t.start_notify(NUS_CHAR_NOTIFY_UUID, on_rx)
            await asyncio.sleep(notify_seconds)
            await t.stop_notify(NUS_CHAR_NOTIFY_UUID)
        return exitcodes.OK
    finally:
        await t.disconnect()

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.scan_only:
            return asyncio.run(scan(args.scan_seconds))
        if not args.address:
            print("ERROR: --address required unless --scan-only", file=sys.stderr)
            return exitcodes.USAGE
        return asyncio.run(
            observe(
                args.address,
                pre_scan=args.pre_scan_seconds,
                connect_timeout=args.connect_timeout,
                notify=args.notify,
                notify_seconds=args.notify_seconds,
                app_start=args.app_start,
            )
        )
    except OwnershipError as exc:
        print(f"ERROR(OWNERSHIP): {exc}", file=sys.stderr)
        return exitcodes.OWNERSHIP
    except DiscoveryError as exc:
        print(f"ERROR(DISCOVERY): {exc}", file=sys.stderr)
        return exitcodes.DISCOVERY
    except ConnectionError as exc:
        print(f"ERROR(CONNECT): {exc}", file=sys.stderr)
        return exitcodes.CONNECT
    except NotificationError as exc:
        print(f"ERROR(NOTIFY): {exc}", file=sys.stderr)
        return exitcodes.NOTIFY
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR(INTERNAL): {exc}", file=sys.stderr)
        return exitcodes.INTERNAL
