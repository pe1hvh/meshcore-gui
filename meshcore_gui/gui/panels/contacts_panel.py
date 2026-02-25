"""Contacts panel — list of known mesh nodes with click-to-DM."""

from typing import Callable, Dict, Optional

from nicegui import ui

from meshcore_gui.gui.constants import TYPE_ICONS, TYPE_NAMES
from meshcore_gui.services.contact_cleaner import ContactCleanerService
from meshcore_gui.services.pin_store import PinStore


class ContactsPanel:
    """Displays contacts in the left column. Click opens a DM dialog.

    Args:
        put_command: Callable to enqueue a command dict for the worker.
        pin_store: PinStore for persistent pin state.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        pin_store: PinStore,
        set_auto_add_enabled: Callable[[bool], None],
        on_add_room: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self._put_command = put_command
        self._pin_store = pin_store
        self._set_auto_add_enabled = set_auto_add_enabled
        self._on_add_room = on_add_room
        self._cleaner = ContactCleanerService(pin_store)
        self._container = None
        self._auto_add_checkbox = None
        self._last_data: Optional[Dict] = None

    def render(self) -> None:
        with ui.card().classes('w-full'):
            ui.label('👥 Contacts').classes('font-bold text-gray-600')
            self._container = ui.column().classes(
                'w-full gap-0 max-h-96 overflow-y-auto'
            )
            with ui.row().classes('w-full gap-2 mt-2 items-center'):
                ui.button(
                    '🧹 Clean up',
                    on_click=self._open_purge_dialog,
                )
                self._auto_add_checkbox = ui.checkbox(
                    '📥 Auto-add',
                    value=False,
                    on_change=self._on_auto_add_change,
                )

    def update(self, data: Dict) -> None:
        if not self._container:
            return

        self._last_data = data

        # Sync auto-add checkbox with device state
        if self._auto_add_checkbox is not None:
            device_state = data.get('auto_add_enabled', False)
            if self._auto_add_checkbox.value != device_state:
                self._auto_add_checkbox.set_value(device_state)

        self._container.clear()

        # Sort: pinned contacts first, then alphabetical within each group
        contacts_items = list(data['contacts'].items())
        contacts_items.sort(
            key=lambda item: (
                0 if self._pin_store.is_pinned(item[0]) else 1,
                item[1].get('adv_name', item[0][:12]).lower(),
            )
        )

        with self._container:
            for key, contact in contacts_items:
                ctype = contact.get('type', 0)
                icon = TYPE_ICONS.get(ctype, '○')
                name = contact.get('adv_name', key[:12])
                type_name = TYPE_NAMES.get(ctype, '-')
                lat = contact.get('adv_lat', 0)
                lon = contact.get('adv_lon', 0)
                has_loc = lat != 0 or lon != 0
                pinned = self._pin_store.is_pinned(key)

                tooltip = (
                    f"{name}\nType: {type_name}\n"
                    f"Key: {key[:16]}...\nClick to send DM"
                )
                if has_loc:
                    tooltip += f"\nLat: {lat:.4f}\nLon: {lon:.4f}"

                row_classes = (
                    'w-full items-center gap-1 py-0 px-1 '
                    'rounded no-wrap '
                )
                if pinned:
                    row_classes += 'bg-yellow-50'
                
                # Outer row: checkbox + clickable contact info
                with ui.row().classes(row_classes):
                    # Pin checkbox — click.stop prevents DM dialog opening
                    cb = ui.checkbox(
                        value=pinned,
                    ).props('dense size=xs').on(
                        'click.stop', lambda e: None,
                    )
                    cb.on_value_change(
                        lambda e, k=key: self._toggle_pin(k)
                    )

                    # Clickable area for DM
                    with ui.row().classes(
                        'items-center gap-0.5 flex-grow '
                        'cursor-pointer hover:bg-gray-100 rounded py-0 px-1'
                    ).on(
                        'click',
                        lambda e, k=key, n=name, t=ctype: self._on_contact_click(k, n, t),
                    ):
                        ui.label(icon).classes('text-sm')
                        ui.label(name[:15]).classes(
                            'text-sm flex-grow truncate'
                        ).tooltip(tooltip)
                        ui.label(type_name).classes('text-xs text-gray-500')
                        loc_icon = '📍' if has_loc else '✖'
                        loc_cls = 'text-xs w-4 text-center'
                        if not has_loc:
                            loc_cls += ' text-red-400'
                        ui.label(loc_icon).classes(loc_cls)

    # ------------------------------------------------------------------
    # Pin toggle
    # ------------------------------------------------------------------

    def _toggle_pin(self, pubkey: str) -> None:
        """Toggle pin state for a contact and refresh the list."""
        if self._pin_store.is_pinned(pubkey):
            self._pin_store.unpin(pubkey)
        else:
            self._pin_store.pin(pubkey)
        # Re-render with last known data so sort order and visuals update
        if self._last_data:
            self.update(self._last_data)

    # ------------------------------------------------------------------
    # Auto-add toggle
    # ------------------------------------------------------------------

    def _on_auto_add_change(self, e) -> None:
        """Handle auto-add checkbox toggle.

        Optimistically updates SharedData and sends the command.
        On failure, the command handler rolls back SharedData and the
        next GUI update cycle will revert the checkbox.
        """
        enabled = e.value
        self._set_auto_add_enabled(enabled)
        self._put_command({
            'action': 'set_auto_add',
            'enabled': enabled,
        })

    # ------------------------------------------------------------------
    # Purge unpinned contacts
    # ------------------------------------------------------------------

    def _open_purge_dialog(self) -> None:
        """Open confirmation dialog for bulk-deleting unpinned contacts."""
        try:
            if not self._last_data:
                ui.notify('No contacts loaded', type='warning')
                print("CleanUp: _last_data is None")
                return

            contacts = self._last_data.get('contacts', {})
            if not contacts:
                ui.notify('No contacts found', type='warning')
                print("CleanUp: contacts dict is empty")
                return

            print(f"CleanUp: {len(contacts)} contacts found, calculating stats...")
            stats = self._cleaner.get_purge_stats(contacts)
            print(
                f"CleanUp: unpinned={stats.unpinned_count}, "
                f"pinned={stats.pinned_count}"
            )

            if stats.unpinned_count == 0:
                ui.notify(
                    'All contacts are pinned — nothing to remove',
                    type='info',
                )
                return

            with ui.dialog() as dialog, ui.card().classes('w-96'):
                ui.label('🧹 Clean up contacts').classes(
                    'font-bold text-lg'
                )
                ui.label(
                    f'{stats.unpinned_count} contacts will be removed from device.\n'
                    f'{stats.pinned_count} pinned contacts will be kept.'
                ).classes('whitespace-pre-line my-2')

                delete_history_cb = ui.checkbox(
                    'Also delete from local history',
                ).props('dense')

                with ui.row().classes('w-full justify-end gap-2 mt-4'):
                    ui.button('Cancel', on_click=dialog.close).props(
                        'flat'
                    )

                    def confirm_purge():
                        self._put_command({
                            'action': 'purge_unpinned',
                            'pubkeys': stats.unpinned_keys,
                            'delete_from_history': delete_history_cb.value,
                        })
                        dialog.close()
                        ui.notify(
                            f'Removing {stats.unpinned_count} '
                            f'contacts...',
                            type='info',
                        )

                    ui.button(
                        'Remove',
                        on_click=confirm_purge,
                    ).classes('bg-red-500 text-white')

            dialog.open()
            print("CleanUp: dialog opened successfully")

        except Exception as exc:
            print(f"CleanUp: EXCEPTION — {exc}")
            ui.notify(
                f'Error opening cleanup dialog: {exc}',
                type='negative',
            )

    # ------------------------------------------------------------------
    # Contact click dispatcher
    # ------------------------------------------------------------------

    def _on_contact_click(self, pubkey: str, name: str, ctype: int) -> None:
        """Route contact click to the appropriate dialog.

        Type 3 (Room Server) opens a Room Server add/login dialog.
        All other types open the standard DM dialog.
        """
        if ctype == 3 and self._on_add_room:
            self._open_room_dialog(pubkey, name)
        else:
            self._open_dm_dialog(pubkey, name)

    # ------------------------------------------------------------------
    # Room Server dialog
    # ------------------------------------------------------------------

    def _open_room_dialog(self, pubkey: str, contact_name: str) -> None:
        """Open dialog to add a Room Server panel with password."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label(f'🏠 Add Room Server: {contact_name}').classes(
                'font-bold text-lg'
            )
            pw_input = ui.input(
                placeholder='Room password...',
                password=True,
                password_toggle_button=True,
            ).classes('w-full')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                def add_and_login():
                    password = pw_input.value or ''
                    if self._on_add_room:
                        self._on_add_room(pubkey, contact_name, password)
                    dialog.close()

                ui.button(
                    'Add & Login',
                    on_click=add_and_login,
                ).classes('bg-blue-500 text-white')

        dialog.open()

    # ------------------------------------------------------------------
    # DM dialog
    # ------------------------------------------------------------------

    def _open_dm_dialog(self, pubkey: str, contact_name: str) -> None:
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label(f'💬 DM to {contact_name}').classes('font-bold text-lg')
            msg_input = ui.input(placeholder='Type your message...').classes('w-full')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                def send_dm():
                    text = msg_input.value
                    if text:
                        self._put_command({
                            'action': 'send_dm',
                            'pubkey': pubkey,
                            'text': text,
                            'contact_name': contact_name,
                        })
                        dialog.close()

                ui.button('Send', on_click=send_dm).classes('bg-blue-500 text-white')
        dialog.open()
