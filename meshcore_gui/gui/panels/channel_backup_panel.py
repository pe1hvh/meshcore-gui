"""
Channel backup panel — dialogs for exporting and restoring channels.

Two independent dialogs in a single panel class:

Backup
    One-click snapshot of the device's current channel table (names +
    PSKs) to a device-scoped JSON file in
    ``~/.meshcore-gui/channel_backups/``.  After writing, the dialog
    shows the absolute path so the operator can copy it off-box.

Restore
    Load a backup file and preview exactly what will change before
    writing anything to the device.  Entries are classified into four
    buckets (restorable / conflict / identical / skipped) so the user
    sees in advance which slots will be overwritten.

Both dialogs are lightweight and read-only with respect to the device
until the user confirms — the Restore action enqueues ``add_channel``
commands via the normal command queue, reusing the existing BLE worker
path so no new protocol code is required.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.services.cache import DeviceCache
from meshcore_gui.services.channel_backup_store import (
    ChannelBackup,
    ChannelBackupEntry,
    ChannelBackupStore,
)


class ChannelBackupPanel:
    """NiceGUI dialogs for channel Backup & Restore.

    Args:
        device_id:    Device identifier (used to instantiate the backup
                      store and a read-only :class:`DeviceCache` for the
                      restore-preview diff).
        put_command:  Callable to enqueue a command dict for the BLE
                      worker (used to dispatch ``add_channel`` during
                      restore).
    """

    def __init__(
        self,
        device_id: str,
        put_command: Callable[[Dict], None],
    ) -> None:
        self._device_id = device_id
        self._put_command = put_command
        self._store = ChannelBackupStore(device_id)

        # Live state captured from the 500 ms update cycle
        self._live_channels: List[Dict] = []

        # Dialog + widget references (populated in render())
        self._backup_dialog: Optional[ui.dialog] = None
        self._backup_summary_label: Optional[ui.label] = None
        self._backup_path_label: Optional[ui.label] = None

        self._restore_dialog: Optional[ui.dialog] = None
        self._restore_status_label: Optional[ui.label] = None
        self._restore_preview_area: Optional[ui.column] = None
        self._restore_confirm_btn: Optional[ui.button] = None
        self._restore_upload: Optional[ui.upload] = None

        # Parsed backup pending restore (set on upload or device-file load)
        self._pending_backup: Optional[ChannelBackup] = None
        self._pending_diff: Dict[str, List[ChannelBackupEntry]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Create both dialog widget trees.

        Must be called once during dashboard page rendering so the
        widgets are bound to the correct NiceGUI client session.
        """
        self._render_backup_dialog()
        self._render_restore_dialog()

    def update(self, data: Dict) -> None:
        """Update the live channel snapshot from the 500 ms tick.

        Args:
            data: SharedData snapshot dict containing the ``channels`` list.
        """
        self._live_channels = data.get("channels", [])

    def open_backup(self) -> None:
        """Open the Backup dialog and pre-compute summary text."""
        if self._backup_dialog is None:
            return
        self._reset_backup_view()
        self._backup_dialog.open()

    def open_restore(self) -> None:
        """Open the Restore dialog, pre-populated with device-file preview."""
        if self._restore_dialog is None:
            return
        self._pending_backup = None
        self._pending_diff = {}
        self._render_restore_preview()
        self._restore_dialog.open()

    # ------------------------------------------------------------------
    # Backup dialog
    # ------------------------------------------------------------------

    def _render_backup_dialog(self) -> None:
        self._backup_dialog = ui.dialog()
        with self._backup_dialog:
            with ui.card().classes("w-full").style(
                "min-width: 360px; max-width: 480px; gap: 0.6rem"
            ):
                ui.label("💾 Backup channels").classes(
                    "font-bold text-gray-600 text-base"
                )

                ui.label(
                    "Create a local JSON snapshot of every channel "
                    "currently known to this GUI (name + PSK + slot). "
                    "Use this before reflashing firmware or wiping NVS."
                ).classes("text-xs text-gray-500")

                self._backup_summary_label = ui.label("").classes(
                    "text-sm text-gray-700"
                )
                self._backup_path_label = ui.label("").classes(
                    "text-xs text-gray-400 break-all"
                )

                with ui.row().classes("gap-2 justify-end w-full"):
                    ui.button(
                        "Close",
                        on_click=self._close_backup,
                    ).props("flat no-caps")
                    ui.button(
                        "Create backup now",
                        on_click=self._do_backup,
                    ).props("unelevated color=primary no-caps")

    def _reset_backup_view(self) -> None:
        """Populate the backup dialog with the current pre-export summary."""
        if self._backup_summary_label:
            live_count = len(self._live_channels)
            self._backup_summary_label.text = (
                f"This device reports {live_count} active channel"
                f"{'s' if live_count != 1 else ''}. "
                "Click below to write the backup."
            )
        if self._backup_path_label:
            self._backup_path_label.text = ""

    def _do_backup(self) -> None:
        """Execute the export and show the resulting path."""
        try:
            backup = self._store.export_from_cache(
                live_channels=self._live_channels,
            )
        except OSError as exc:
            ui.notify(f"⚠️ Backup failed: {exc}", type="negative", timeout=4000)
            return

        exported = len(backup.channels)
        with_psk = sum(1 for e in backup.channels if e.psk_hex)
        without_psk = exported - with_psk

        if self._backup_summary_label:
            msg = f"✅ Exported {exported} channel{'s' if exported != 1 else ''}"
            if without_psk:
                msg += (
                    f" — {with_psk} with PSK, {without_psk} without "
                    "(these cannot be restored automatically)"
                )
            else:
                msg += f" with PSKs."
            self._backup_summary_label.text = msg
        if self._backup_path_label:
            self._backup_path_label.text = f"Saved to: {self._store.path}"

        ui.notify(
            f"Channels backed up ({exported} slot{'s' if exported != 1 else ''})",
            type="positive",
            timeout=3000,
        )

    def _close_backup(self) -> None:
        if self._backup_dialog:
            self._backup_dialog.close()

    # ------------------------------------------------------------------
    # Restore dialog
    # ------------------------------------------------------------------

    def _render_restore_dialog(self) -> None:
        self._restore_dialog = ui.dialog()
        with self._restore_dialog:
            with ui.card().classes("w-full").style(
                "min-width: 380px; max-width: 560px; gap: 0.6rem"
            ):
                ui.label("📥 Restore channels").classes(
                    "font-bold text-gray-600 text-base"
                )

                ui.label(
                    "Previews what will be written before any device "
                    "change is made. PSK conflicts are flagged — the "
                    "existing slot will be overwritten on confirm."
                ).classes("text-xs text-gray-500")

                self._restore_status_label = ui.label("").classes(
                    "text-sm text-gray-700"
                )

                # Optional upload for restoring from a file that is not
                # the default device-scoped one (e.g. replacing a broken
                # node with a new one using the old node's backup).
                self._restore_upload = ui.upload(
                    on_upload=self._on_upload,
                    max_file_size=1 * 1024 * 1024,  # 1 MiB
                    auto_upload=True,
                ).props(
                    'accept=".json" flat dense label="Load different file…"'
                ).classes("w-full")

                self._restore_preview_area = ui.column().classes(
                    "w-full gap-0 text-xs"
                ).style(
                    "max-height: 40vh; overflow-y: auto; "
                    "font-family: 'JetBrains Mono', monospace"
                )

                with ui.row().classes("gap-2 justify-end w-full"):
                    ui.button(
                        "Cancel",
                        on_click=self._close_restore,
                    ).props("flat no-caps")
                    self._restore_confirm_btn = ui.button(
                        "Write to device",
                        on_click=self._do_restore,
                    ).props("unelevated color=primary no-caps")
                    self._restore_confirm_btn.disable()

    def _on_upload(self, event) -> None:
        """Accept a .json file uploaded by the user and show its preview."""
        try:
            raw = event.content.read().decode("utf-8")
        except (AttributeError, UnicodeDecodeError) as exc:
            ui.notify(
                f"⚠️ Could not read file: {exc}",
                type="negative",
                timeout=4000,
            )
            return

        import json

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            ui.notify(
                f"⚠️ Not valid JSON: {exc}",
                type="negative",
                timeout=4000,
            )
            return

        backup = self._store._parse(data)  # noqa: SLF001 — panel + store are siblings
        if backup is None:
            ui.notify(
                "⚠️ Unrecognised backup format",
                type="negative",
                timeout=4000,
            )
            return

        self._pending_backup = backup
        self._render_restore_preview(from_file=event.name)

        if self._restore_upload is not None:
            self._restore_upload.reset()

    def _render_restore_preview(self, from_file: Optional[str] = None) -> None:
        """Rebuild the Restore preview using the currently pending backup."""
        # Fall back to the device's own saved backup file if none was uploaded
        if self._pending_backup is None:
            self._pending_backup = self._store.load_backup()

        if self._restore_preview_area:
            self._restore_preview_area.clear()

        if self._pending_backup is None:
            if self._restore_status_label:
                self._restore_status_label.text = (
                    "No backup found for this device. Upload a .json file "
                    "or create a backup first via 💾 Backup channels."
                )
            if self._restore_confirm_btn:
                self._restore_confirm_btn.disable()
            self._pending_diff = {}
            return

        # Compute diff against the live device state
        cache = DeviceCache(self._device_id)
        cache.load()
        cached_keys_raw = cache.get_channel_keys()
        cached_keys: Dict[int, str] = {}
        for k, v in cached_keys_raw.items():
            try:
                cached_keys[int(k)] = (v or "").lower()
            except (ValueError, TypeError):
                continue

        diff = ChannelBackupStore.diff_against_device(
            self._pending_backup, self._live_channels, cached_keys
        )
        self._pending_diff = diff

        # Header line describing the loaded backup
        src = from_file or self._store.path.name
        exported_at = self._pending_backup.exported_at or "unknown time"
        fw = self._pending_backup.firmware_version or "?"

        if self._restore_status_label:
            self._restore_status_label.text = (
                f"Loaded: {src}  ·  {exported_at}  ·  firmware {fw}  ·  "
                f"{len(self._pending_backup.channels)} slot(s)"
            )

        # Counts per category
        restorable = diff["restorable"]
        conflicts = diff["conflict"]
        identical = diff["identical"]
        skipped = diff["skipped"]

        def _row(symbol: str, color: str, entry: ChannelBackupEntry, note: str) -> None:
            psk_preview = entry.psk_hex[:8] + "…" if entry.psk_hex else "(no PSK)"
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(symbol).style(f"color: {color}; min-width: 1rem")
                ui.label(
                    f"[{entry.slot_idx:>2}] {entry.name or '(unnamed)'}"
                ).style("min-width: 14rem")
                ui.label(psk_preview).classes("text-gray-400")
                ui.label(note).classes("text-gray-500")

        if self._restore_preview_area:
            with self._restore_preview_area:
                ui.label(
                    f"✅ {len(restorable)} writable  ·  ⚠️ {len(conflicts)} conflict  "
                    f"·  ✓ {len(identical)} unchanged  ·  ⊘ {len(skipped)} skipped"
                ).classes("text-sm text-gray-700 py-1")

                ui.separator()

                for e in restorable:
                    _row("✅", "#16a34a", e, "will be added")
                for e in conflicts:
                    _row("⚠️", "#d97706", e, "slot occupied — will overwrite")
                for e in identical:
                    _row("✓", "#6b7280", e, "already matches — will re-send")
                for e in skipped:
                    _row("⊘", "#9ca3af", e, "no PSK stored — cannot restore")

        # Enable confirm only when there is at least one entry we can write
        can_write = bool(restorable or conflicts or identical)
        if self._restore_confirm_btn:
            if can_write:
                self._restore_confirm_btn.enable()
            else:
                self._restore_confirm_btn.disable()

    def _do_restore(self) -> None:
        """Enqueue add_channel commands for every restorable entry."""
        if self._pending_backup is None:
            return

        # Build the queue: restorable + conflict + identical (in that order)
        to_write: List[ChannelBackupEntry] = []
        to_write.extend(self._pending_diff.get("restorable", []))
        to_write.extend(self._pending_diff.get("conflict", []))
        to_write.extend(self._pending_diff.get("identical", []))

        if not to_write:
            ui.notify("Nothing to restore", type="warning", timeout=2500)
            return

        # Sort by slot index for predictable write order
        to_write.sort(key=lambda e: e.slot_idx)

        dispatched = 0
        for entry in to_write:
            if not entry.psk_hex or not entry.name:
                continue
            self._put_command({
                "action": "add_channel",
                "idx": entry.slot_idx,
                "name": entry.name,
                "secret_hex": entry.psk_hex,
            })
            dispatched += 1

        ui.notify(
            f"📥 Restoring {dispatched} channel"
            f"{'s' if dispatched != 1 else ''}… "
            "(watch status bar for progress)",
            type="info",
            timeout=3500,
        )
        self._close_restore()

    def _close_restore(self) -> None:
        if self._restore_dialog:
            self._restore_dialog.close()
