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
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from meshcore_gui.config import debug_print


# ==============================================================================
# Bot defaults (previously in config.py)
# ==============================================================================

# Channel indices the bot listens on (must match device channels).
BOT_CHANNELS: frozenset = frozenset({1, 4})  # #test, #bot

# Display name prepended to every bot reply.
BOT_NAME: str = "Zwolle Bot"

# Minimum seconds between two bot replies (prevents reply-storms).
BOT_COOLDOWN_SECONDS: float = 5.0

# Keyword → reply template mapping.
# Available variables: {bot}, {sender}, {snr}, {path}
# The bot checks whether the incoming message text *contains* the keyword
# (case-insensitive).  First match wins.
BOT_KEYWORDS: Dict[str, str] = {
    'test': '{sender}, rcvd | SNR {snr} | {path}',
    'ping': 'Pong!',
    'help': 'test, ping, help',
}


@dataclass
class BotConfig:
    """Configuration for :class:`MeshBot`.

    Attributes:
        channels:         Channel indices to listen on.
        name:             Display name prepended to replies.
        cooldown_seconds: Minimum seconds between replies.
        keywords:         Keyword → reply template mapping.
    """

    channels: frozenset = field(default_factory=lambda: frozenset(BOT_CHANNELS))
    name: str = BOT_NAME
    cooldown_seconds: float = BOT_COOLDOWN_SECONDS
    keywords: Dict[str, str] = field(default_factory=lambda: dict(BOT_KEYWORDS))


class MeshBot:
    """Keyword-triggered auto-reply bot.

    The bot checks incoming messages against a set of keyword → template
    pairs.  When a keyword is found (case-insensitive substring match,
    first match wins), the template is expanded and queued as a channel
    message via *command_sink*.

    Args:
        config:        Bot configuration.
        command_sink:  Callable that enqueues a command dict for the
                       worker (typically ``shared.put_command``).
        enabled_check: Callable that returns ``True`` when the bot is
                       enabled (typically ``shared.is_bot_enabled``).
    """

    def __init__(
        self,
        config: BotConfig,
        command_sink: Callable[[Dict], None],
        enabled_check: Callable[[], bool],
    ) -> None:
        self._config = config
        self._sink = command_sink
        self._enabled = enabled_check
        self._last_reply: float = 0.0

    def check_and_reply(
        self,
        sender: str,
        text: str,
        channel_idx: Optional[int],
        snr: Optional[float],
        path_len: int,
        path_hashes: Optional[List[str]] = None,
    ) -> None:
        """Evaluate an incoming message and queue a reply if appropriate.

        Guards (in order):
            1. Bot is enabled (checkbox in GUI).
            2. Message is on the configured channel.
            3. Sender is not the bot itself.
            4. Sender name does not end with ``'Bot'`` (prevent loops).
            5. Cooldown period has elapsed.
            6. Message text contains a recognised keyword.
        """
        # Guard 1: enabled?
        if not self._enabled():
            return

        # Guard 2: correct channel?
        if channel_idx not in self._config.channels:
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

    @staticmethod
    def _format_path(
        path_len: int,
        path_hashes: Optional[List[str]],
    ) -> str:
        """Format path info as ``path(N); 8D>A8`` or ``path(0)``."""
        if not path_len:
            return "path(0)"

        if not path_hashes:
            return f"path({path_len})"

        hop_names = [h.upper() for h in path_hashes if h and len(h) >= 2]
        if hop_names:
            return f"path({path_len}); {'>'.join(hop_names)}"
        return f"path({path_len})"
