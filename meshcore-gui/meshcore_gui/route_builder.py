"""
Route data builder for MeshCore GUI.

Pure data logic — no UI code.  Given a message and a data snapshot, this
module constructs a route dictionary that describes the path the message
has taken through the mesh network (sender → repeaters → receiver).

Path data sources (in priority order):

1. **path_hashes** (from the message) — decoded from the raw LoRa
   packet by ``meshcoredecoder`` via ``RX_LOG_DATA``.  Each entry is a
   2-char hex string representing the first byte of a repeater's public
   key.  Always available when the packet was successfully decrypted
   (single-source architecture).

2. **out_path** (from the sender's contact record) — hex string where
   each byte (2 hex chars) is the first byte of a repeater's public
   key.  Only available for known contacts with a stored route.  This
   is the *last known* route to/from that contact, not necessarily the
   route of *this* message.

3. **path_len only** — hop count from the message frame.  Always
   available for received messages but contains no repeater identities.
"""

from typing import Dict, List, Optional

from meshcore_gui.config import debug_print
from meshcore_gui.protocols import ContactLookup


class RouteBuilder:
    """
    Builds route data for a message from available contact information.

    Uses only data already in memory — no extra BLE commands are sent.

    Args:
        shared: ContactLookup for resolving pubkey prefixes to contacts
    """

    def __init__(self, shared: ContactLookup) -> None:
        self._shared = shared

    def build(self, msg: Dict, data: Dict) -> Dict:
        """
        Build route data for a single message.

        Args:
            msg:  Message dict (must contain 'sender_pubkey', may contain
                  'path_len', 'snr' and 'path_hashes')
            data: Snapshot dictionary from SharedData.get_snapshot()

        Returns:
            Dictionary with keys:
                sender:        {name, lat, lon, type, pubkey} or None
                self_node:     {name, lat, lon}
                path_nodes:    [{name, lat, lon, type, pubkey}, …]
                snr:           float or None
                msg_path_len:  int — hop count from the message itself
                has_locations: bool — True if any node has GPS coords
                path_source:   str — 'rx_log', 'contact_out_path' or 'none'
        """
        result: Dict = {
            'sender': None,
            'self_node': {
                'name': data['name'] or 'Me',
                'lat': data['adv_lat'],
                'lon': data['adv_lon'],
            },
            'path_nodes': [],
            'snr': msg.get('snr'),
            'msg_path_len': msg.get('path_len', 0),
            'has_locations': False,
            'path_source': 'none',
        }

        # Look up sender in contacts
        pubkey = msg.get('sender_pubkey', '')
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
                result['sender'] = {
                    'name': contact.get('adv_name', pubkey[:8]),
                    'lat': contact.get('adv_lat', 0),
                    'lon': contact.get('adv_lon', 0),
                    'type': contact.get('type', 0),
                    'pubkey': pubkey,
                }
                debug_print(
                    f"Route build: sender hash will be "
                    f"{pubkey[:2].upper()!r}"
                )
        else:
            # Deferred sender lookup: try fuzzy name match
            # Use sender_full (untruncated) if available, fall back to sender
            sender_name = msg.get('sender_full') or msg.get('sender', '')
            if sender_name:
                match = self._shared.get_contact_by_name(sender_name)
                if match:
                    pubkey, contact_data = match
                    contact = contact_data
                    result['sender'] = {
                        'name': contact_data.get('adv_name', pubkey[:8]),
                        'lat': contact_data.get('adv_lat', 0),
                        'lon': contact_data.get('adv_lon', 0),
                        'type': contact_data.get('type', 0),
                        'pubkey': pubkey,
                    }
                    debug_print(
                        f"Route build: deferred name lookup "
                        f"'{sender_name}' → pubkey={pubkey[:16]!r}, "
                        f"hash={pubkey[:2].upper()!r}"
                    )
                else:
                    debug_print(
                        f"Route build: deferred name lookup "
                        f"'{sender_name}' → NOT FOUND"
                    )
            else:
                debug_print("Route build: sender_pubkey is EMPTY, no name → hash will be '-'")

        # --- Resolve path nodes (priority order) ---

        # Priority 1: path_hashes from RX_LOG decode (single-source)
        rx_hashes = msg.get('path_hashes', [])

        if rx_hashes:
            result['path_nodes'] = self._resolve_hashes(
                rx_hashes, data['contacts'],
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
        all_points = [result['self_node']]
        if result['sender']:
            all_points.append(result['sender'])
        all_points.extend(result['path_nodes'])

        result['has_locations'] = any(
            p.get('lat', 0) != 0 or p.get('lon', 0) != 0
            for p in all_points
        )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_hashes(
        hashes: List[str],
        contacts: Dict,
    ) -> List[Dict]:
        """
        Resolve a list of 1-byte path hashes into hop node dicts.

        Args:
            hashes:   List of 2-char hex strings (e.g. ["8d", "a8"])
            contacts: Contacts dictionary from snapshot

        Returns:
            List of hop node dicts.
        """
        nodes: List[Dict] = []

        for hop_hash in hashes:
            if not hop_hash or len(hop_hash) < 2:
                continue

            hop_contact = RouteBuilder._find_contact_by_pubkey_hash(
                hop_hash, contacts,
            )

            if hop_contact:
                nodes.append({
                    'name': hop_contact.get('adv_name', f'0x{hop_hash}'),
                    'lat': hop_contact.get('adv_lat', 0),
                    'lon': hop_contact.get('adv_lon', 0),
                    'type': hop_contact.get('type', 0),
                    'pubkey': hop_hash,
                })
            else:
                nodes.append({
                    'name': '-',
                    'lat': 0,
                    'lon': 0,
                    'type': 0,
                    'pubkey': hop_hash,
                })

        return nodes

    @staticmethod
    def _parse_out_path(
        out_path: str,
        out_path_len: int,
        contacts: Dict,
    ) -> List[Dict]:
        """
        Parse out_path hex string into a list of hop nodes.

        Each byte (2 hex chars) in out_path is the first byte of a
        repeater's public key.

        Returns:
            List of hop node dicts.
        """
        hashes: List[str] = []
        hop_hex_len = 2  # 1 byte = 2 hex chars

        for i in range(0, min(len(out_path), out_path_len * 2), hop_hex_len):
            hop_hash = out_path[i:i + hop_hex_len]
            if hop_hash and len(hop_hash) == 2:
                hashes.append(hop_hash)

        return RouteBuilder._resolve_hashes(hashes, contacts)

    @staticmethod
    def _find_contact_by_pubkey_hash(
        hash_hex: str, contacts: Dict,
    ) -> Optional[Dict]:
        """
        Find a contact whose pubkey starts with the given 1-byte hash.

        Note: with only 256 possible values, collisions are possible
        when there are many contacts.  Returns the first match.
        """
        hash_hex = hash_hex.lower()
        for pubkey, contact in contacts.items():
            if pubkey.lower().startswith(hash_hex):
                return contact
        return None
