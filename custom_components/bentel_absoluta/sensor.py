"""Sensors: last event of the panel log."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BentelConfigEntry
from .entity import BentelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([BentelLastEvent(entry, hass.config.language.startswith("it"))])


class BentelLastEvent(BentelEntity, SensorEntity):
    """Most recent record of the panel event log (e.g. "Inser. eseguito")."""

    _attr_translation_key = "last_event"
    _attr_icon = "mdi:history"

    def __init__(self, entry: BentelConfigEntry, italian: bool) -> None:
        super().__init__(entry, "last_event")
        self._italian = italian
        self._last_documented = None

    def _describe(self, event) -> str:
        text = event.text(self._italian)
        if event.zone:
            text += f" – {self.client.zone_labels.get(event.zone, event.zone)}"
        elif event.partition:
            text += f" – {self.client.partition_labels.get(event.partition, event.partition)}"
        return text[:255]

    def _latest(self):
        """Most recent documented event. Undocumented codes are skipped, also when
        they fill the whole window of recent records: the previous documented
        event is kept instead (only shown as a last resort)."""
        events = self.client.last_events
        latest = next((e for e in events if e.documented), None)
        if latest is not None:
            self._last_documented = latest
            return latest
        return self._last_documented or (events[0] if events else None)

    @property
    def native_value(self) -> str | None:
        event = self._latest()
        return self._describe(event) if event else None

    @property
    def extra_state_attributes(self) -> dict:
        event = self._latest()
        if event is None:
            return {}
        ts = (
            event.timestamp.replace(tzinfo=dt_util.get_default_time_zone()).isoformat()
            if event.timestamp
            else None
        )
        return {
            "timestamp": ts,
            "event_id": f"0x{event.event_id:04X}",
            "class": event.cls,
            "restore": event.restore,
            "zone": event.zone,
            "partitions": [self.client.partition_labels.get(p, str(p)) for p in event.partitions],
            "where": event.where,
            "who": event.who,
            "recent": [self._describe(e) for e in self.client.last_events],
        }
