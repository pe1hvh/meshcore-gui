"""Room Server panel — per-room messaging with login and password storage."""

from typing import Callable, Dict, List, Set

from nicegui import ui

from meshcore_gui.core.models import Message
from meshcore_gui.services.room_password_store import RoomPasswordStore


class RoomServerPanel:
    """Displays one card per configured Room Server in the centre column.

    Each card contains a password field, login/logout button, message
    display and message input.  Cards are created by calling
    :meth:`add_room` (triggered from ContactsPanel when the user clicks
    a type-3 contact).

    Args:
        put_command:         Callable to enqueue a command dict for the worker.
        room_password_store: Persistent store for room passwords.
    """

    def __init__(
        self,
        put_command: Callable[[Dict], None],
        room_password_store: RoomPasswordStore,
    ) -> None:
        self._put_command = put_command
        self._store = room_password_store

        # Outer container that holds all room cards
        self._container = None

        # Per-room UI state keyed by pubkey
        self._room_cards: Dict[str, Dict] = {}

        # Login state tracked locally (not persisted)
        self._logged_in: Set[str] = set()

    # ------------------------------------------------------------------
    # Render — restore persisted rooms on startup
    # ------------------------------------------------------------------

    def render(self) -> None:
        """Build the outer container and restore persisted rooms."""
        self._container = ui.column().classes('w-full gap-2')

        with self._container:
            for entry in self._store.get_rooms():
                self._render_room_card(
                    entry.pubkey, entry.name, entry.password,
                )

    # ------------------------------------------------------------------
    # Public — add a room (called from Dashboard/ContactsPanel)
    # ------------------------------------------------------------------

    def add_room(self, pubkey: str, name: str, password: str) -> None:
        """Add a new Room Server card and persist it.

        If the room is already shown, updates password and re-logins.

        Args:
            pubkey:   Full public key (hex string).
            name:     Display name.
            password: Room password.
        """
        # Persist
        self._store.add_room(pubkey, name, password)

        if pubkey in self._room_cards:
            # Already visible — update password field and re-login
            card_state = self._room_cards[pubkey]
            card_state['password'].value = password
            self._login_room(card_state, pubkey)
            return

        # Create new card
        if not self._container:
            return

        with self._container:
            self._render_room_card(pubkey, name, password)

        # Auto-login
        if pubkey in self._room_cards:
            self._login_room(self._room_cards[pubkey], pubkey)

    def get_room_pubkeys(self) -> Set[str]:
        """Return the set of all room server pubkeys currently tracked.

        Used by :class:`MessagesPanel` to filter out room messages from
        the general DM view.
        """
        return set(self._room_cards.keys())

    # ------------------------------------------------------------------
    # Update (called from dashboard timer)
    # ------------------------------------------------------------------

    def update(self, data: Dict) -> None:
        """Refresh messages and login state for each room card.

        Args:
            data: Snapshot dict from SharedData.
        """
        if not self._container:
            return

        # Process room login state changes from the worker
        login_states: Dict = data.get('room_login_states', {})
        self._apply_login_states(login_states)

        # Room messages from archive cache (keyed by 12-char pubkey prefix)
        room_messages: Dict = data.get('room_messages', {})
        # Live messages from current session's rolling buffer
        live_messages: List[Message] = data.get('messages', [])

        for pubkey, card_state in self._room_cards.items():
            self._update_room_messages(
                pubkey, card_state, room_messages, live_messages,
            )

    # ------------------------------------------------------------------
    # Internal — login state feedback from worker
    # ------------------------------------------------------------------

    def _apply_login_states(self, login_states: Dict) -> None:
        """Apply server-confirmed login states to room cards.

        Called every update tick.  Matches login_states (keyed by
        pubkey prefix from the device packet) against known room cards
        (keyed by full pubkey) using prefix matching.

        Args:
            login_states: ``{pubkey_prefix: {'state': str, 'detail': str}}``
                          from SharedData.
        """
        for pubkey, card_state in self._room_cards.items():
            # Find matching login state (prefix match)
            matched_state = None
            for prefix, state_info in login_states.items():
                if pubkey.startswith(prefix) or prefix.startswith(pubkey[:16]):
                    matched_state = state_info
                    break  # Use first match only; prevents stale keys overriding

            if matched_state is None:
                continue

            state = matched_state.get('state', '')

            if state == 'ok' and pubkey not in self._logged_in:
                # Server confirmed login
                self._logged_in.add(pubkey)
                card_state['status'].text = (
                    '✅ Logged in — history arriving over RF…'
                )
                card_state['pw_row'].set_visibility(False)
                card_state['logout_btn'].set_visibility(True)
                card_state['login_btn'].enable()
                card_state['msg_input'].enable()
                card_state['send_btn'].enable()

            elif state == 'fail' and pubkey not in self._logged_in:
                # Login failed or timed out — revert to login form
                detail = matched_state.get('detail', 'Unknown error')
                card_state['status'].text = f'❌ Login failed: {detail}'
                card_state['pw_row'].set_visibility(True)
                card_state['logout_btn'].set_visibility(False)
                card_state['login_btn'].enable()
                card_state['msg_input'].disable()
                card_state['send_btn'].disable()

            elif state == 'pending':
                card_state['status'].text = '⏳ Logging in…'

            elif state == 'logged_out' and pubkey in self._logged_in:
                # Server confirmed logout — ensure UI is fully reset
                # (catches edge cases where _logout_room UI update was
                # overridden by a stale 'ok' state from previous tick)
                self._logged_in.discard(pubkey)
                card_state['status'].text = '⏳ Not logged in'
                card_state['pw_row'].set_visibility(True)
                card_state['logout_btn'].set_visibility(False)
                card_state['login_btn'].enable()
                card_state['msg_input'].disable()
                card_state['send_btn'].disable()

    # ------------------------------------------------------------------
    # Internal — single room card
    # ------------------------------------------------------------------

    def _render_room_card(
        self,
        pubkey: str,
        name: str,
        password: str,
    ) -> None:
        """Render a single Room Server card.

        Args:
            pubkey:   Public key of the room.
            name:     Display name.
            password: Stored password.
        """
        card_state: Dict = {}
        is_logged_in = pubkey in self._logged_in

        with ui.card().classes('w-full') as card:
            card_state['card'] = card

            # Header row: title + remove button
            with ui.row().classes('w-full items-center justify-between'):
                card_state['title'] = ui.label(
                    f'🏠 Room Server: {name}'
                ).classes('font-bold text-gray-600')

                ui.button(
                    '✕',
                    on_click=lambda e, pk=pubkey: self._remove_room(pk),
                ).props('flat dense round size=sm')

            # Password + Login row (hidden after login)
            card_state['pw_row'] = ui.row().classes('w-full items-center gap-2')
            with card_state['pw_row']:
                card_state['password'] = ui.input(
                    placeholder='Password...',
                    value=password,
                    password=True,
                    password_toggle_button=True,
                ).classes('flex-grow')

                card_state['login_btn'] = ui.button(
                    'Login',
                    on_click=lambda e, pk=pubkey: self._on_login_click(pk),
                ).classes('bg-blue-500 text-white')

            # Logout button (hidden before login)
            card_state['logout_btn'] = ui.button(
                'Logout',
                on_click=lambda e, pk=pubkey: self._on_login_click(pk),
            ).classes('bg-red-500 text-white')

            # Set initial visibility
            if is_logged_in:
                card_state['pw_row'].set_visibility(False)
                card_state['logout_btn'].set_visibility(True)
            else:
                card_state['pw_row'].set_visibility(True)
                card_state['logout_btn'].set_visibility(False)

            # Status label
            card_state['status'] = ui.label(
                '✅ Logged in' if is_logged_in
                else '⏳ Not logged in'
            ).classes('text-xs text-gray-500')

            # Messages container (scrollable)
            card_state['msg_container'] = ui.column().classes(
                'w-full h-32 overflow-y-auto gap-0 text-sm font-mono '
                'bg-gray-50 p-2 rounded'
            )

            # Send row
            with ui.row().classes('w-full items-center gap-2'):
                card_state['msg_input'] = ui.input(
                    placeholder='Message...',
                ).classes('flex-grow')

                card_state['send_btn'] = ui.button(
                    'Send',
                    on_click=lambda e, pk=pubkey: self._send_room_message(pk),
                ).classes('bg-blue-500 text-white')

            # Disable send controls if not logged in
            if not is_logged_in:
                card_state['msg_input'].disable()
                card_state['send_btn'].disable()

        self._room_cards[pubkey] = card_state

    # ------------------------------------------------------------------
    # Internal — actions
    # ------------------------------------------------------------------

    def _on_login_click(self, pubkey: str) -> None:
        """Dispatch login or logout based on current state."""
        card_state = self._room_cards.get(pubkey)
        if not card_state:
            return

        if pubkey in self._logged_in:
            self._logout_room(card_state, pubkey)
        else:
            self._login_room(card_state, pubkey)

    def _login_room(self, card_state: Dict, pubkey: str) -> None:
        """Send login command to a Room Server.

        Sets the UI to 'pending' state.  The actual logged-in state
        is updated later in :meth:`update` when the worker reports
        LOGIN_SUCCESS via ``room_login_states`` in SharedData.
        """
        password = card_state['password'].value or ''
        name = card_state['title'].text.replace('🏠 Room Server: ', '')

        # Persist password update
        self._store.update_password(pubkey, password)

        # Send login command via worker
        self._put_command({
            'action': 'login_room',
            'pubkey': pubkey,
            'password': password,
            'room_name': name,
        })

        # Pending UI update — real state comes from SharedData
        card_state['status'].text = '⏳ Logging in…'
        card_state['login_btn'].disable()

        ui.notify(f'Logging in to {name}...', type='info')

    def _logout_room(self, card_state: Dict, pubkey: str) -> None:
        """Logout from a Room Server.

        Sends a logout command via worker so the companion radio stops
        keep-alive pings and the room server deregisters the client.
        This ensures a clean ``sync_since`` reset on re-login.
        """
        name = card_state['title'].text.replace('🏠 Room Server: ', '')

        # Send logout command to companion radio / room server
        self._put_command({
            'action': 'logout_room',
            'pubkey': pubkey,
            'room_name': name,
        })

        self._logged_in.discard(pubkey)

        # Clear messages — user should not see room history after logout
        msg_container = card_state.get('msg_container')
        if msg_container:
            msg_container.clear()

        card_state['status'].text = '⏳ Not logged in'
        card_state['pw_row'].set_visibility(True)
        card_state['logout_btn'].set_visibility(False)
        card_state['login_btn'].enable()
        card_state['msg_input'].disable()
        card_state['send_btn'].disable()

        ui.notify(f'Logged out from {name}', type='info')

    def _send_room_message(self, pubkey: str) -> None:
        """Send a message to a Room Server."""
        card_state = self._room_cards.get(pubkey)
        if not card_state:
            return

        if pubkey not in self._logged_in:
            ui.notify('Not logged in', type='warning')
            return

        msg_input = card_state.get('msg_input')
        if not msg_input or not msg_input.value:
            return

        text = msg_input.value
        name = card_state['title'].text.replace('🏠 Room Server: ', '')

        self._put_command({
            'action': 'send_room_msg',
            'pubkey': pubkey,
            'text': text,
            'room_name': name,
        })

        msg_input.value = ''

    def _remove_room(self, pubkey: str) -> None:
        """Remove a Room Server card and its stored data."""
        self._store.remove_room(pubkey)
        self._logged_in.discard(pubkey)

        card_state = self._room_cards.pop(pubkey, None)
        if card_state and card_state.get('card'):
            self._container.remove(card_state['card'])

    # ------------------------------------------------------------------
    # Internal — message display
    # ------------------------------------------------------------------

    def _update_room_messages(
        self,
        pubkey: str,
        card_state: Dict,
        room_messages: Dict,
        live_messages: List[Message],
    ) -> None:
        """Update the message display for a single room card.

        Only shows messages when logged in.  Merges archived room
        messages (from ``room_messages`` cache) with live messages
        from the current session.  Displays newest-first so the most
        recent message is always visible at the top without scrolling.

        Args:
            pubkey:         Full public key of the room server.
            card_state:     UI state dict for this room card.
            room_messages:  ``{12-char-prefix: [Message, …]}`` from archive cache.
            live_messages:  Current session's rolling message buffer.
        """
        msg_container = card_state.get('msg_container')
        if not msg_container:
            return

        # Login gate — show nothing before login
        if pubkey not in self._logged_in:
            msg_container.clear()
            return

        norm = pubkey[:12]

        # 1. Archived room messages (loaded from disk cache)
        archived: List[Message] = room_messages.get(norm, [])

        # 2. Live room messages from rolling buffer (current session)
        live_room: List[Message] = []
        for msg in live_messages:
            if not msg.sender_pubkey:
                continue
            if (msg.sender_pubkey.startswith(norm)
                    or norm.startswith(msg.sender_pubkey[:12])):
                live_room.append(msg)

        # 3. Merge and dedup (archive may already contain live messages
        #    because add_message() appends to both)
        seen = set()
        merged: List[Message] = []
        for msg in archived + live_room:
            key = (msg.time, msg.text)
            if key not in seen:
                seen.add(key)
                merged.append(msg)

        # 4. Take last 30 then reverse: newest message at top
        display = merged[-30:]
        display.reverse()

        msg_container.clear()

        with msg_container:
            for msg in display:
                direction = '→' if msg.direction == 'out' else '←'
                sender = msg.sender or '?'
                line = f"{msg.time} {direction} {sender}: {msg.text}"

                ui.label(line).classes(
                    'text-xs leading-tight px-1'
                )
