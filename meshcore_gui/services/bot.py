"""
Keyword-triggered auto-reply bot for MeshCore GUI.

Extracted from SerialWorker to satisfy the Single Responsibility Principle.
The bot listens on a configured channel and replies to messages that
contain recognised keywords.

Open/Closed
~~~~~~~~~~~
New keywords are added via ``BotConfig.keywords`` (data) without
modifying the ``MeshBot`` class (code).  Custom matching strategies
can be implemented by subclassing and overriding ``_match_keyword``.

BBS separation
~~~~~~~~~~~~~~
BBS commands (``!bbs``, ``!p``, ``!r``) are handled by
:class:`~meshcore_gui.services.bbs_service.BbsCommandHandler` which is
wired directly into
:class:`~meshcore_gui.ble.events.EventHandler`.  They never pass
through ``MeshBot`` — the bot is a pure keyword/channel-message
responder only.

Private mode
~~~~~~~~~~~~
When ``private_mode`` is enabled in :class:`BotConfigStore`, the bot
only responds to senders whose public-key prefix is found in the
:class:`~meshcore_gui.services.pin_store.PinStore`.  Private mode can
only be activated when at least one contact is pinned; this constraint
is enforced in the UI layer.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from meshcore_gui.config import debug_print

if TYPE_CHECKING:
    from meshcore_gui.services.bot_config_store import BotConfigStore


# ==============================================================================
# Bot defaults (previously in config.py)
# ==============================================================================

# Channel indices the bot listens on (must match device channels).
BOT_CHANNELS: frozenset = frozenset({1, 4})  # #test, #bot

# Display name prepended to every bot reply.
BOT_NAME: str = "ZwolsBotje"

# Minimum seconds between two bot replies (prevents reply-storms).
BOT_COOLDOWN_SECONDS: float = 5.0

# Keyword -> reply template mapping.
# Available variables: {bot}, {sender}, {snr}, {path}
# The bot checks whether the incoming message text *contains* the keyword
# (case-insensitive).  First match wins.
BOT_KEYWORDS: Dict[str, str] = {
    '#test': '@[{sender}], rcvd | SNR {snr} | {path}',
    'ping': 'Pong!',
#    'help': 'test, ping, help',
}


@dataclass
class BotConfig:
    """Static configuration for :class:`MeshBot`.

    This dataclass holds default values.  When a :class:`BotConfigStore`
    is provided to :class:`MeshBot`, runtime channel selection and
    private-mode state are read from the store instead.

    Attributes:
        channels:         Default channel indices to listen on (fallback
                          when BotConfigStore has no saved channel selection).
        name:             Display name prepended to replies.
        cooldown_seconds: Minimum seconds between replies.
        keywords:         Keyword -> reply template mapping.
    """

    channels: frozenset = field(default_factory=lambda: frozenset(BOT_CHANNELS))
    name: str = BOT_NAME
    cooldown_seconds: float = BOT_COOLDOWN_SECONDS
    keywords: Dict[str, str] = field(default_factory=lambda: dict(BOT_KEYWORDS))


class MeshBot:
    """Keyword-triggered auto-reply bot.

    The bot checks incoming messages against a set of keyword -> template
    pairs.  When a keyword is found (case-insensitive substring match,
    first match wins), the template is expanded and queued as a channel
    message via *command_sink*.

    Args:
        config:        Static bot configuration (defaults).
        command_sink:  Callable that enqueues a command dict for the
                       worker (typically ``shared.put_command``).
        enabled_check: Callable that returns ``True`` when the bot is
                       enabled (typically ``shared.is_bot_enabled``).
        config_store:  Optional :class:`BotConfigStore` for persistent
                       channel selection and private-mode flag.  When
                       provided, channel filtering and private-mode are
                       read from the store on every call to
                       :meth:`check_and_reply`.
        pinned_check:  Optional callable ``(pubkey: str) -> bool`` that
                       returns ``True`` when *pubkey* belongs to a pinned
                       contact.  Required for private mode to function;
                       when absent, private mode blocks all unknown senders.
    """

    def __init__(
        self,
        config: BotConfig,
        command_sink: Callable[[Dict], None],
        enabled_check: Callable[[], bool],
        config_store: Optional["BotConfigStore"] = None,
        pinned_check: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._config = config
        self._sink = command_sink
        self._enabled = enabled_check
        self._config_store = config_store
        self._pinned_check = pinned_check
        self._last_reply: float = 0.0

    def check_and_reply(
        self,
        sender: str,
        text: str,
        channel_idx: Optional[int],
        snr: Optional[float],
        path_len: int,
        path_hashes: Optional[List[str]] = None,
        sender_pubkey: Optional[str] = None,
    ) -> None:
        """Evaluate an incoming channel message and queue a reply if appropriate.

        Guards (in order):
            1.   Bot is enabled (checkbox in GUI).
            1.5. Private mode: sender must be a pinned contact.
            2.   Message is on the configured channel.
            3.   Sender is not the bot itself.
            4.   Sender name does not end with 'Bot' (prevent loops).
            5.   Cooldown period has elapsed.
            6.   Message text contains a recognised keyword.

        Note: BBS commands (``!bbs``, ``!p``, ``!r``) are NOT handled here.
        They arrive as DMs and are handled by ``BbsCommandHandler`` directly
        inside ``EventHandler.on_contact_msg``.

        Args:
            sender:        Display name of the message sender.
            text:          Message body.
            channel_idx:   Channel index the message arrived on.
            snr:           Signal-to-noise ratio (dB), or ``None``.
            path_len:      Number of hops in the path.
            path_hashes:   Optional list of 2-char hop hashes.
            sender_pubkey: Optional public-key prefix of the sender.
                           Used for private-mode pin lookup.
        """
        # Guard 1: enabled?
        if not self._enabled():
            return

        # Guard 1.5: private mode -- only respond to pinned contacts.
        # Reads live from config_store so changes take effect immediately.
        if self._config_store is not None:
            settings = self._config_store.get_settings()
            if settings.private_mode:
                if not sender_pubkey:
                    debug_print(
                        f"BOT: private mode active, no pubkey for '{sender}' -- skip"
                    )
                    return
                if self._pinned_check is None or not self._pinned_check(sender_pubkey):
                    debug_print(
                        f"BOT: private mode active, '{sender}' not pinned -- skip"
                    )
                    return

        # Guard 2: correct channel?
        active_channels = self._get_active_channels()
        if channel_idx not in active_channels:
            return

        # Guard 3: own messages?
        if sender == "Me" or (text and text.startswith(self._config.name)):
            return

        # Guard 4: other bots?
        if sender and sender.rstrip().lower().endswith("bot"):
            debug_print(f"BOT: skipping message from other bot '{sender}'")
            return

        # Guard 5: cooldown?
        now = time.time()
        if now - self._last_reply < self._config.cooldown_seconds:
            debug_print("BOT: cooldown active, skipping")
            return

        # Guard 6: keyword match
        template = self._match_keyword(text)
        if template is None:
            return

        # Build reply
        path_str = self._format_path(path_len, path_hashes)
        snr_str = f"{snr:.1f}" if snr is not None else "?"
        reply = template.format(
            bot=self._config.name,
            sender=sender or "?",
            snr=snr_str,
            path=path_str,
        )

        self._last_reply = now

        self._sink({
            "action": "send_message",
            "channel": channel_idx,
            "text": reply,
            "_bot": True,
        })
        debug_print(f"BOT: queued reply to '{sender}': {reply}")

    # ------------------------------------------------------------------
    # Extension point (OCP)
    # ------------------------------------------------------------------

    def _match_keyword(self, text: str) -> Optional[str]:
        """Return the reply template for the first matching keyword.

        Override this method for custom matching strategies (regex,
        exact match, priority ordering, etc.).

        Returns:
            Template string, or ``None`` if no keyword matched.
        """
        text_lower = (text or "").lower()
        for keyword, template in self._config.keywords.items():
            if keyword in text_lower:
                return template
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_active_channels(self) -> frozenset:
        """Return the effective channel set.

        When a :class:`BotConfigStore` is present, its channel selection
        is always authoritative — including an empty set (bot silent on
        all channels until the user saves a selection in the BOT panel).
        The hardcoded :attr:`BotConfig.channels` fallback is only used
        when no config store is wired (e.g. in unit tests).

        Returns:
            Frozenset of active channel indices.
        """
        if self._config_store is not None:
            return frozenset(self._config_store.get_settings().channels)
        return self._config.channels

    @staticmethod
    def _format_path(
        path_len: int,
        path_hashes: Optional[List[str]],
    ) -> str:
        """Format path info as ``path(N)`` or ``path(0)``."""
        if not path_len:
            return "path(0)"
        return f"path({path_len})"
