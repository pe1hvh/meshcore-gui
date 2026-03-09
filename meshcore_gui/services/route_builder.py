"""
Route data builder for MeshCore GUI.

Pure data logic — no UI code.  Given a message and a data snapshot, this
module constructs a route dictionary that describes the path the message
has taken through the mesh network (sender → repeaters → receiver).

v4.1 changes
~~~~~~~~~~~~~
- ``build()`` now accepts a :class:`~meshcore_gui.models.Message`
  dataclass instead of a plain dict.
- Route nodes returned as :class:`~meshcore_gui.models.RouteNode`.
"""

from typing import Dict, List, Optional

from meshcore_gui.config import debug_print
from meshcore_gui.core.models import Message, RouteNode
from meshcore_gui.core.protocols import ContactLookup


class RouteBuilder:
    """
    Builds route data for a message from available contact information.

    Uses only data already in memory — no extra commands are sent.

    Args:
        shared: ContactLookup for resolving pubkey prefixes to contacts
    """

    def __init__(self, shared: ContactLookup) -> None:
        self._shared = shared

    def build(self, msg: Message, data: Dict) -> Dict:
        """
        Build route data for a single message.

        Args:
            msg:  Message dataclass instance.
            data: Snapshot dictionary from SharedData.get_snapshot().

        Returns:
            Dictionary with keys:
                sender:        RouteNode or None
                self_node:     RouteNode
                path_nodes:    List[RouteNode]
                snr:           float or None
                msg_path_len:  int — hop count from the message itself
                has_locations: bool — True if any node has GPS coords
                path_source:   str — 'rx_log', 'contact_out_path' or 'none'
        """
        result: Dict = {
            'sender': None,
            'self_node': RouteNode(
                name=data['name'] or 'Me',
                lat=data['adv_lat'],
                lon=data['adv_lon'],
            ),
            'path_nodes': [],
            'snr': msg.snr,
            'msg_path_len': msg.path_len,
            'has_locations': False,
            'path_source': 'none',
        }

        # Look up sender in contacts
        pubkey = msg.sender_pubkey
        contact: Optional[Dict] = None

        debug_print(
            f"Route build: sender_pubkey={pubkey!r} "
            f"(len={len(pubkey)}, first2={pubkey[:2]!r})"
        )

        if pubkey:
            contact = self._shared.get_contact_by_prefix(pubkey)
            debug_print(
                f"Route build: contact lookup "
                f"{'FOUND ' + contact.get('adv_name', '?') if contact else 'NOT FOUND'}"
            )
            if contact:
                result['sender'] = RouteNode(
                    name=contact.get('adv_name') or pubkey[:8],
                    lat=contact.get('adv_lat', 0),
                    lon=contact.get('adv_lon', 0),
                    type=contact.get('type', 0),
                    pubkey=pubkey,
                )

        # Always try name-based fallback if sender still unresolved
        if result['sender'] is None:
            sender_name = msg.sender
            if sender_name:
                match = self._shared.get_contact_by_name(sender_name)
                if match:
                    found_pubkey, contact_data = match
                    contact = contact_data
                    result['sender'] = RouteNode(
                        name=contact_data.get('adv_name') or found_pubkey[:8],
                        lat=contact_data.get('adv_lat', 0),
                        lon=contact_data.get('adv_lon', 0),
                        type=contact_data.get('type', 0),
                        pubkey=found_pubkey,
                    )
                    debug_print(
                        f"Route build: name fallback "
                        f"'{sender_name}' → pubkey={found_pubkey[:16]!r}"
                    )

        # Fallback 3: direct lookup in snapshot contacts by pubkey
        if result['sender'] is None and pubkey:
            snapshot_contact = self._find_contact_by_pubkey(
                pubkey, data['contacts'],
            )
            if snapshot_contact:
                contact = snapshot_contact
                result['sender'] = RouteNode(
                    name=snapshot_contact.get('adv_name') or pubkey[:8],
                    lat=snapshot_contact.get('adv_lat', 0),
                    lon=snapshot_contact.get('adv_lon', 0),
                    type=snapshot_contact.get('type', 0),
                    pubkey=pubkey,
                )
                debug_print(
                    f"Route build: snapshot pubkey fallback "
                    f"→ {snapshot_contact.get('adv_name', '?')}"
                )

        # Fallback 4: direct lookup in snapshot contacts by name
        if result['sender'] is None and msg.sender:
            name_match = self._find_contact_by_adv_name(
                msg.sender, data['contacts'],
            )
            if name_match:
                found_pubkey, snapshot_contact = name_match
                contact = snapshot_contact
                result['sender'] = RouteNode(
                    name=snapshot_contact.get('adv_name') or msg.sender,
                    lat=snapshot_contact.get('adv_lat', 0),
                    lon=snapshot_contact.get('adv_lon', 0),
                    type=snapshot_contact.get('type', 0),
                    pubkey=found_pubkey,
                )
                debug_print(
                    f"Route build: snapshot name fallback "
                    f"'{msg.sender}' → pubkey={found_pubkey[:16]!r}"
                )

        # --- Resolve path nodes (priority order) ---

        # Priority 1: path_hashes from RX_LOG decode
        rx_hashes = msg.path_hashes

        if rx_hashes:
            result['path_nodes'] = self._resolve_hashes(
                rx_hashes, data['contacts'], msg.path_names,
            )
            result['path_source'] = 'rx_log'

            debug_print(
                f"Route from RX_LOG: {len(rx_hashes)} hashes → "
                f"{len(result['path_nodes'])} nodes"
            )

        # Priority 2: out_path from sender's contact record
        elif contact:
            out_path = contact.get('out_path', '')
            out_path_len = contact.get('out_path_len', 0)

            debug_print(
                f"Route: sender={contact.get('adv_name')}, "
                f"out_path={out_path!r}, out_path_len={out_path_len}, "
                f"msg_path_len={result['msg_path_len']}"
            )

            if out_path and out_path_len and out_path_len > 0:
                result['path_nodes'] = self._parse_out_path(
                    out_path, out_path_len, data['contacts'],
                )
                result['path_source'] = 'contact_out_path'

        # Determine if any node has GPS coordinates
        all_nodes: List[RouteNode] = [result['self_node']]
        if result['sender']:
            all_nodes.append(result['sender'])
        all_nodes.extend(result['path_nodes'])

        result['has_locations'] = any(n.has_location for n in all_nodes)

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_hashes(
        hashes: List[str],
        contacts: Dict,
        stored_names: Optional[List[str]] = None,
    ) -> List[RouteNode]:
        """Resolve a list of 1-byte path hashes into RouteNode objects.

        Args:
            hashes:       List of 2-char hex strings.
            contacts:     Contact dict from snapshot.
            stored_names: Pre-resolved names from the archive (same
                          length as *hashes*).  Used as fallback when
                          the contact lookup fails (e.g. contact renamed
                          or not yet loaded).
        """
        nodes: List[RouteNode] = []

        for idx, hop_hash in enumerate(hashes):
            if not hop_hash or len(hop_hash) < 2:
                continue

            hop_contact = RouteBuilder._find_contact_by_pubkey_hash(
                hop_hash, contacts,
            )

            if hop_contact:
                nodes.append(RouteNode(
                    name=hop_contact.get('adv_name') or f'0x{hop_hash}',
                    lat=hop_contact.get('adv_lat', 0),
                    lon=hop_contact.get('adv_lon', 0),
                    type=hop_contact.get('type', 0),
                    pubkey=hop_hash,
                ))
            else:
                # Fallback: use the name that was stored at receive time
                fallback_name = '-'
                if stored_names and idx < len(stored_names):
                    fallback_name = stored_names[idx] or '-'
                if fallback_name == '-':
                    fallback_name = f'0x{hop_hash.upper()}'

                nodes.append(RouteNode(
                    name=fallback_name,
                    pubkey=hop_hash,
                ))

        return nodes

    @staticmethod
    def _parse_out_path(
        out_path: str,
        out_path_len: int,
        contacts: Dict,
    ) -> List[RouteNode]:
        """Parse out_path hex string into a list of RouteNode objects."""
        hashes: List[str] = []
        hop_hex_len = 2

        for i in range(0, min(len(out_path), out_path_len * 2), hop_hex_len):
            hop_hash = out_path[i:i + hop_hex_len]
            if hop_hash and len(hop_hash) == 2:
                hashes.append(hop_hash)

        return RouteBuilder._resolve_hashes(hashes, contacts)

    @staticmethod
    def _find_contact_by_pubkey_hash(
        hash_hex: str, contacts: Dict,
    ) -> Optional[Dict]:
        hash_hex = hash_hex.lower()
        for pubkey, contact in contacts.items():
            if pubkey.lower().startswith(hash_hex):
                return contact
        return None

    @staticmethod
    def _find_contact_by_pubkey(
        pubkey_prefix: str, contacts: Dict,
    ) -> Optional[Dict]:
        """Find a contact by full or partial pubkey (bidirectional prefix match).

        Mirrors the matching logic of
        :meth:`SharedData.get_contact_by_prefix` but operates on the
        snapshot contacts dict directly, avoiding a lock acquisition.

        Args:
            pubkey_prefix: Full or partial public key (hex string).
            contacts:      Contact dict from snapshot.

        Returns:
            Contact dict or ``None``.
        """
        if not pubkey_prefix:
            return None
        prefix_lower = pubkey_prefix.lower()
        for key, contact in contacts.items():
            key_lower = key.lower()
            if key_lower.startswith(prefix_lower) or prefix_lower.startswith(key_lower):
                return contact
        return None

    @staticmethod
    def _find_contact_by_adv_name(
        name: str, contacts: Dict,
    ) -> Optional[tuple]:
        """Find a contact by advertised name (case-insensitive).

        Mirrors the matching logic of
        :meth:`SharedData.get_contact_by_name` but operates on the
        snapshot contacts dict directly.

        Args:
            name:     Display name to search for.
            contacts: Contact dict from snapshot.

        Returns:
            ``(pubkey, contact_dict)`` tuple or ``None``.
        """
        if not name:
            return None
        name_lower = name.lower()
        # Exact match first
        for key, contact in contacts.items():
            if contact.get('adv_name', '') == name:
                return (key, contact)
        # Case-insensitive fallback
        for key, contact in contacts.items():
            if contact.get('adv_name', '').lower() == name_lower:
                return (key, contact)
        return None
