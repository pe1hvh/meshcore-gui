"""
Channel panel — dialog for adding, moving and managing channels.

Triggered by the ``＋ Add Channel`` button or the ``↕`` move button in
the Messages submenu.  Four modes are supported:

Hashtag
    Name must start with ``#``.  The channel key is derived automatically
    from the name by the MeshCore library; no manual key input is required
    and no key export is offered (the name itself is the shared secret).

Private — New
    Name is freely chosen.  A random 16-byte key is generated on demand.
    After submission the dialog shows a QR code and a copy-to-clipboard
    button so the key can be shared with other users.

Private — Existing  (join)
    Used when another user has shared a private channel key.  The user
    pastes the 32-character hex key and the dialog writes it to the
    device verbatim.  No key export is offered.

Move / Reindex
    Select an existing channel and assign it a different slot index.
    The secret is read from the DeviceCache by the command handler; the
    user only needs to pick a source channel and a target index.
"""

from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.services.channel_service import (
    generate_qr_base64,
    generate_secret,
    secret_to_hex,
)


class ChannelPanel:
    """NiceGUI dialog for adding or moving a channel on the MeshCore device.

    Args:
        put_command: Callable to enqueue a command dict for the BLE worker.
    """

    def __init__(self, put_command: Callable[[Dict], None]) -> None:
        self._put_command = put_command
        self._channels: List[Dict] = []

        # Dialog + form widget references (populated in render())
        self._dialog: Optional[ui.dialog] = None
        self._mode_radio: Optional[ui.radio] = None
        self._idx_input: Optional[ui.number] = None
        self._name_input: Optional[ui.input] = None

        # Private-mode widgets
        self._hashtag_info: Optional[ui.label] = None
        self._secret_section: Optional[ui.column] = None
        self._secret_input: Optional[ui.input] = None
        self._generate_row: Optional[ui.row] = None
        self._copy_btn: Optional[ui.button] = None

        # QR section (private-new only, revealed after submit)
        self._qr_section: Optional[ui.column] = None
        self._qr_label: Optional[ui.label] = None
        self._qr_image: Optional[ui.image] = None

        # Move-mode widgets
        self._move_section: Optional[ui.column] = None
        self._move_select: Optional[ui.select] = None

        # Transient state
        self._generated_secret: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Create the dialog widget tree.

        Must be called once during dashboard page rendering (inside the
        NiceGUI ``@ui.page`` context) so that all widgets are bound to the
        correct client session.
        """
        self._dialog = ui.dialog()

        with self._dialog:
            with ui.card().classes('w-full').style(
                'min-width: 340px; max-width: 440px; gap: 0.6rem'
            ):
                ui.label('📡 Channel Manager').classes('font-bold text-gray-600 text-base')

                # ── Mode selection ──────────────────────────────────
                self._mode_radio = ui.radio(
                    options={
                        'hashtag': '# Hashtag channel',
                        'private_new': '🔒 Private – New',
                        'private_existing': '🔒 Private – Existing (join)',
                        'move': '↕️ Move / Reindex',
                    },
                    value='hashtag',
                    on_change=self._on_mode_change,
                ).classes('w-full')

                # ── Channel index ────────────────────────────────────
                self._idx_input = ui.number(
                    label='Channel index (1 – 99)',
                    value=1,
                    min=1,
                    max=99,
                    step=1,
                    format='%d',
                ).classes('w-full')

                # ── Channel name (add modes) ─────────────────────────
                self._name_input = ui.input(
                    label='Channel name',
                    placeholder='e.g. #localmesh',
                ).classes('w-full')

                # ── Hashtag info label ───────────────────────────────
                self._hashtag_info = ui.label(
                    '🔑 Key is derived automatically from the name. '
                    'Anyone who knows the name can join.'
                ).classes('text-xs text-gray-500')

                # ── Private secret section ───────────────────────────
                self._secret_section = ui.column().classes('w-full gap-1')
                with self._secret_section:
                    self._secret_input = ui.input(
                        label='Secret key (32 hex chars)',
                        placeholder='e.g. 8b3387e9c5cdea6ac9e5edbaa115cd72',
                    ).classes('w-full')

                    self._generate_row = ui.row().classes('gap-2 items-center')
                    with self._generate_row:
                        ui.button(
                            '🎲 Generate key',
                            on_click=self._generate_secret,
                        ).props('flat dense no-caps')
                        self._copy_btn = ui.button(
                            '📋 Copy key',
                            on_click=self._copy_key,
                        ).props('flat dense no-caps')

                # ── Move section ─────────────────────────────────────
                self._move_section = ui.column().classes('w-full gap-1')
                with self._move_section:
                    self._move_select = ui.select(
                        options={},
                        label='Channel to move',
                    ).classes('w-full')
                    ui.label(
                        'The channel will be written to the new index and '
                        'removed from its current slot. The secret is '
                        'retrieved automatically from the cache.'
                    ).classes('text-xs text-gray-500')

                # ── Action buttons ───────────────────────────────────
                with ui.row().classes('gap-2 justify-end w-full'):
                    ui.button(
                        'Cancel',
                        on_click=self._close,
                    ).props('flat no-caps')
                    ui.button(
                        'Confirm',
                        on_click=self._submit,
                    ).props('unelevated color=primary no-caps')

                # ── QR code section (shown after private-new submit) ─
                self._qr_section = ui.column().classes('w-full items-center gap-1')
                with self._qr_section:
                    ui.separator()
                    self._qr_label = ui.label('').classes(
                        'text-xs text-gray-500 text-center'
                    )
                    self._qr_image = ui.image('').style('width: 192px; height: 192px')
                    ui.label(
                        'Scan with the MeshCore app to share this channel.'
                    ).classes('text-xs text-gray-400 text-center')

                # Apply initial visibility based on default mode
                self._apply_visibility('hashtag')
                self._qr_section.set_visibility(False)

    def update(self, data: Dict) -> None:
        """Update the channel list from the live data snapshot.

        Called every 500 ms from the dashboard update cycle.  Stores the
        current channel list so ``open()`` can pre-fill sensible defaults
        and populate the move-mode selector.

        Args:
            data: SharedData snapshot dict containing the ``channels`` list.
        """
        self._channels = data.get('channels', [])

    def open(self, mode: str = 'hashtag', preselect_idx: Optional[int] = None) -> None:
        """Open the dialog in the given mode.

        Args:
            mode:          One of ``'hashtag'``, ``'private_new'``,
                           ``'private_existing'``, or ``'move'``.
            preselect_idx: When mode is ``'move'``, pre-select this channel
                           index in the source selector.
        """
        if self._dialog is None:
            return
        self._reset_form(mode=mode, preselect_idx=preselect_idx)
        self._dialog.open()

    # ------------------------------------------------------------------
    # Private — form logic
    # ------------------------------------------------------------------

    def _close(self) -> None:
        """Close the dialog."""
        if self._dialog:
            self._dialog.close()

    def _reset_form(
        self,
        mode: str = 'hashtag',
        preselect_idx: Optional[int] = None,
    ) -> None:
        """Reset all fields to clean state and apply the given mode."""
        self._generated_secret = None

        if self._mode_radio:
            self._mode_radio.value = mode
        if self._name_input:
            self._name_input.value = ''
        if self._secret_input:
            self._secret_input.value = ''
        if self._qr_section:
            self._qr_section.set_visibility(False)
        if self._qr_image:
            self._qr_image.source = ''
        if self._qr_label:
            self._qr_label.text = ''

        # Pre-fill next available index
        if self._channels and mode != 'move':
            next_idx = min(max(ch['idx'] for ch in self._channels) + 1, 99)
        else:
            next_idx = 1
        if self._idx_input:
            self._idx_input.value = next_idx

        # Populate move-mode selector
        self._refresh_move_options(preselect_idx)
        self._apply_visibility(mode)

    def _refresh_move_options(self, preselect_idx: Optional[int] = None) -> None:
        """Rebuild the source-channel selector for move mode."""
        if not self._move_select:
            return
        # Skip index 0 (Public) — slot 0 cannot be moved
        opts = {
            ch['idx']: f"[{ch['idx']}] {ch['name']}"
            for ch in self._channels
            if ch['idx'] != 0
        }
        self._move_select.options = opts
        if opts:
            if preselect_idx is not None and preselect_idx in opts:
                self._move_select.value = preselect_idx
            else:
                self._move_select.value = next(iter(opts))
        self._move_select.update()

    def _on_mode_change(self, event=None) -> None:
        """React to mode-radio change — update field visibility."""
        mode = self._mode_radio.value if self._mode_radio else 'hashtag'
        self._generated_secret = None
        if self._secret_input:
            self._secret_input.value = ''
        if self._qr_section:
            self._qr_section.set_visibility(False)
        if mode == 'move':
            self._refresh_move_options()
        self._apply_visibility(mode)

    def _apply_visibility(self, mode: str) -> None:
        """Show/hide sections according to *mode*."""
        is_hashtag = mode == 'hashtag'
        is_private = mode in ('private_new', 'private_existing')
        is_private_new = mode == 'private_new'
        is_move = mode == 'move'

        if self._hashtag_info:
            self._hashtag_info.set_visibility(is_hashtag)
        if self._secret_section:
            self._secret_section.set_visibility(is_private)
        if self._generate_row:
            self._generate_row.set_visibility(is_private_new)
        if self._copy_btn:
            self._copy_btn.set_visibility(is_private_new)
        if self._name_input:
            self._name_input.set_visibility(not is_move)
        if self._move_section:
            self._move_section.set_visibility(is_move)

        # Adjust index label contextually
        if self._idx_input:
            label = 'Target index (1 – 99)' if is_move else 'Channel index (1 – 99)'
            self._idx_input.props(f'label="{label}"')

        # Adjust name placeholder
        if self._name_input and not is_move:
            placeholder = 'e.g. #localmesh' if is_hashtag else 'e.g. TeamName'
            self._name_input.props(f'placeholder="{placeholder}"')

    # ------------------------------------------------------------------
    # Private — actions
    # ------------------------------------------------------------------

    def _generate_secret(self) -> None:
        """Generate a new random secret and display it in the secret field."""
        self._generated_secret = generate_secret()
        if self._secret_input:
            self._secret_input.value = secret_to_hex(self._generated_secret)

    def _copy_key(self) -> None:
        """Copy the displayed secret to the system clipboard."""
        key = (self._secret_input.value or '').strip() if self._secret_input else ''
        if key:
            ui.run_javascript(
                f'navigator.clipboard.writeText("{key}").catch(()=>{{}})'
            )
            ui.notify('Key copied to clipboard', type='positive', timeout=2000)
        else:
            ui.notify('Generate a key first', type='warning', timeout=2000)

    def _submit(self) -> None:
        """Validate form inputs and queue the appropriate command."""
        mode = self._mode_radio.value if self._mode_radio else 'hashtag'

        if mode == 'move':
            self._submit_move()
            return

        # ── Add modes ────────────────────────────────────────────────
        name = (self._name_input.value or '').strip() if self._name_input else ''
        idx = int(self._idx_input.value or 1) if self._idx_input else 1

        if not name:
            ui.notify('Channel name is required', type='warning', timeout=3000)
            return

        if mode == 'hashtag' and not name.startswith('#'):
            ui.notify(
                'Hashtag channel name must start with #',
                type='warning',
                timeout=3000,
            )
            return

        if mode == 'private_new':
            if not self._generated_secret:
                ui.notify(
                    'Click "Generate key" to create a secret first',
                    type='warning',
                    timeout=3000,
                )
                return
            secret_hex = secret_to_hex(self._generated_secret)

        elif mode == 'private_existing':
            raw = (self._secret_input.value or '').strip().lower() if self._secret_input else ''
            valid_chars = set('0123456789abcdef')
            if len(raw) != 32 or not all(c in valid_chars for c in raw):
                ui.notify(
                    'Secret must be exactly 32 hexadecimal characters',
                    type='warning',
                    timeout=3000,
                )
                return
            secret_hex = raw

        else:
            # Hashtag: library derives the key
            secret_hex = ''

        self._put_command({
            'action': 'add_channel',
            'idx': idx,
            'name': name,
            'secret_hex': secret_hex,
        })

        ui.notify(f"Adding [{idx}] {name}…", type='info', timeout=2500)

        if mode == 'private_new' and self._generated_secret:
            qr_data = generate_qr_base64(name, self._generated_secret)
            if qr_data and self._qr_image and self._qr_label and self._qr_section:
                self._qr_image.source = qr_data
                self._qr_label.text = f'Share key for "{name}"'
                self._qr_section.set_visibility(True)
                return

        self._close()

    def _submit_move(self) -> None:
        """Validate and queue a move_channel command."""
        if not self._move_select or not self._move_select.options:
            ui.notify('No movable channels available', type='warning', timeout=3000)
            return

        old_idx = self._move_select.value
        new_idx = int(self._idx_input.value or 1) if self._idx_input else 1

        if old_idx is None:
            ui.notify('Select a channel to move', type='warning', timeout=3000)
            return

        if old_idx == new_idx:
            ui.notify('Source and target index are the same', type='warning', timeout=3000)
            return

        # Resolve name from channel list
        name = next(
            (ch['name'] for ch in self._channels if ch['idx'] == old_idx),
            '',
        )
        if not name:
            ui.notify('Could not resolve channel name', type='warning', timeout=3000)
            return

        self._put_command({
            'action': 'move_channel',
            'old_idx': old_idx,
            'new_idx': new_idx,
            'name': name,
        })

        ui.notify(
            f"Moving [{old_idx}] {name} → [{new_idx}]…",
            type='info',
            timeout=2500,
        )
        self._close()
