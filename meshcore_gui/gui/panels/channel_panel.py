"""
Channel panel — dialog for adding hashtag and private channels.

Triggered by the ``＋ Add Channel`` button in the Messages submenu.
Three modes are supported:

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
"""

from typing import Callable, Dict, List, Optional

from nicegui import ui

from meshcore_gui.services.channel_service import (
    generate_qr_base64,
    generate_secret,
    secret_to_hex,
)


class ChannelPanel:
    """NiceGUI dialog for adding a channel to the connected MeshCore device.

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
                ui.label('📡 Add Channel').classes('font-bold text-gray-600 text-base')

                # ── Mode selection ──────────────────────────────────
                self._mode_radio = ui.radio(
                    options={
                        'hashtag': '# Hashtag channel',
                        'private_new': '🔒 Private – New',
                        'private_existing': '🔒 Private – Existing (join)',
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

                # ── Channel name ─────────────────────────────────────
                self._name_input = ui.input(
                    label='Channel name',
                    placeholder='e.g. #localmesh',
                ).classes('w-full')

                # ── Hashtag info label (hashtag mode only) ───────────
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

                    # Generate + copy row (private-new only)
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

                # ── Action buttons ───────────────────────────────────
                with ui.row().classes('gap-2 justify-end w-full'):
                    ui.button(
                        'Cancel',
                        on_click=self._close,
                    ).props('flat no-caps')
                    ui.button(
                        'Add Channel',
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
        """Update the next-available channel index from the live channel list.

        Called every 500 ms from the dashboard update cycle.  Stores the
        current channel list so ``open()`` can pre-fill a sensible index.

        Args:
            data: SharedData snapshot dict containing the ``channels`` list.
        """
        self._channels = data.get('channels', [])

    def open(self) -> None:
        """Open the dialog and reset the form to a clean state."""
        if self._dialog is None:
            return
        self._reset_form()
        self._dialog.open()

    # ------------------------------------------------------------------
    # Private — form logic
    # ------------------------------------------------------------------

    def _close(self) -> None:
        """Close the dialog."""
        if self._dialog:
            self._dialog.close()

    def _reset_form(self) -> None:
        """Reset all fields to their defaults and hide the QR section."""
        self._generated_secret = None

        if self._mode_radio:
            self._mode_radio.value = 'hashtag'
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
        if self._channels:
            next_idx = min(max(ch['idx'] for ch in self._channels) + 1, 99)
        else:
            next_idx = 1
        if self._idx_input:
            self._idx_input.value = next_idx

        self._apply_visibility('hashtag')

    def _on_mode_change(self, event=None) -> None:
        """React to mode-radio change — update field visibility."""
        mode = self._mode_radio.value if self._mode_radio else 'hashtag'
        self._generated_secret = None
        if self._secret_input:
            self._secret_input.value = ''
        if self._qr_section:
            self._qr_section.set_visibility(False)
        self._apply_visibility(mode)

    def _apply_visibility(self, mode: str) -> None:
        """Show/hide sections according to *mode*."""
        is_hashtag = mode == 'hashtag'
        is_private = mode in ('private_new', 'private_existing')
        is_private_new = mode == 'private_new'

        if self._hashtag_info:
            self._hashtag_info.set_visibility(is_hashtag)
        if self._secret_section:
            self._secret_section.set_visibility(is_private)
        if self._generate_row:
            self._generate_row.set_visibility(is_private_new)
        if self._copy_btn:
            self._copy_btn.set_visibility(is_private_new)

        # Adjust name placeholder to hint correct input format
        if self._name_input:
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
        """Validate form inputs and queue the ``add_channel`` command."""
        mode = self._mode_radio.value if self._mode_radio else 'hashtag'
        name = (self._name_input.value or '').strip() if self._name_input else ''
        idx = int(self._idx_input.value or 1) if self._idx_input else 1

        # ── Validation ──────────────────────────────────────────────
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
            # Hashtag: library derives the key; pass empty string so the
            # command handler passes secret=None to set_channel().
            secret_hex = ''

        # ── Queue command ────────────────────────────────────────────
        self._put_command({
            'action': 'add_channel',
            'idx': idx,
            'name': name,
            'secret_hex': secret_hex,
        })

        ui.notify(f"Adding [{idx}] {name}…", type='info', timeout=2500)

        # ── QR code for new private channels ─────────────────────────
        if mode == 'private_new' and self._generated_secret:
            qr_data = generate_qr_base64(name, self._generated_secret)
            if qr_data and self._qr_image and self._qr_label and self._qr_section:
                self._qr_image.source = qr_data
                self._qr_label.text = f'Share key for "{name}"'
                self._qr_section.set_visibility(True)
                # Keep dialog open so the user can scan / copy the key
                return

        self._close()
