"""Service helpers for the browser-managed Leaflet map."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MapNodeSnapshot:
    """Serializable snapshot for a single map node."""

    id: str
    name: str
    short_key: str
    node_type: int
    lat: float
    lon: float


@dataclass(frozen=True)
class MapDeviceSnapshot:
    """Serializable snapshot for the local device marker."""

    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class MapSnapshot:
    """Serializable snapshot consumed by the browser Leaflet runtime."""

    device: Optional[MapDeviceSnapshot]
    contacts: List[MapNodeSnapshot]
    theme: str
    force_center: bool

    def to_dict(self) -> Dict:
        """Return the snapshot as a plain JSON-serializable dict."""
        return {
            'device': asdict(self.device) if self.device else None,
            'contacts': [asdict(contact) for contact in self.contacts],
            'theme': self.theme,
            'force_center': self.force_center,
        }


class MapSnapshotService:
    """Build compact browser snapshots from SharedData payloads."""

    def build_snapshot(
        self,
        data: Dict,
        theme_mode: str,
        ui_dark: bool,
        force_center: bool = False,
    ) -> MapSnapshot:
        """Create a full map snapshot for the browser-side Leaflet runtime."""
        return MapSnapshot(
            device=self._build_device(data),
            contacts=self._build_contacts(data),
            theme=self.resolve_theme(theme_mode, ui_dark),
            force_center=force_center or bool(data.get('force_center', False)),
        )

    def _build_device(self, data: Dict) -> Optional[MapDeviceSnapshot]:
        """Return the local device snapshot when valid coordinates exist."""
        lat = self._coerce_coordinate(data.get('adv_lat'))
        lon = self._coerce_coordinate(data.get('adv_lon'))
        if lat is None or lon is None:
            return None
        return MapDeviceSnapshot(
            name=str(data.get('name') or 'Device'),
            lat=lat,
            lon=lon,
        )

    def _build_contacts(self, data: Dict) -> List[MapNodeSnapshot]:
        """Return all valid contact marker snapshots sorted by display name."""
        contacts: List[MapNodeSnapshot] = []
        raw_contacts = data.get('contacts', {}) or {}
        for key, contact in raw_contacts.items():
            lat = self._coerce_coordinate(contact.get('adv_lat'))
            lon = self._coerce_coordinate(contact.get('adv_lon'))
            if lat is None or lon is None:
                continue
            key_str = str(key)
            name = str(contact.get('adv_name') or key_str[:12])
            node_type = self._coerce_node_type(contact.get('type'))
            contacts.append(
                MapNodeSnapshot(
                    id=key_str,
                    name=name,
                    short_key=key_str[:12],
                    node_type=node_type,
                    lat=lat,
                    lon=lon,
                )
            )
        contacts.sort(key=lambda item: (item.name.lower(), item.short_key.lower()))
        return contacts

    @staticmethod
    def resolve_theme(theme_mode: str, ui_dark: bool) -> str:
        """Resolve the effective tile theme from the configured mode."""
        if theme_mode == 'dark':
            return 'dark'
        if theme_mode == 'light':
            return 'light'
        return 'dark' if ui_dark else 'light'

    @staticmethod
    def _coerce_coordinate(value: object) -> Optional[float]:
        """Normalize latitude/longitude values; return None for empty/zero."""
        if value in (None, '', 0, 0.0):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric == 0.0:
            return None
        return numeric

    @staticmethod
    def _coerce_node_type(value: object) -> int:
        """Normalize node type values to the supported marker range."""
        try:
            node_type = int(value)
        except (TypeError, ValueError):
            return 0
        return node_type if node_type in (0, 1, 2, 3) else 0
