"""Base entity for Bentel Absoluta."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import BentelConfigEntry
from .const import DOMAIN, MANUFACTURER
from .itv2.client import AbsolutaClient


class BentelEntity(Entity):
    """Common behaviour: one device per panel, push updates from the client."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: BentelConfigEntry, key: str) -> None:
        self.client: AbsolutaClient = entry.runtime_data
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_{key}"
        info = self.client.info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base)},
            manufacturer=MANUFACTURER,
            model=info.model,
            name=f"Bentel {info.model}",
            sw_version=info.firmware,
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        return self.client.connected

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.client.add_listener(self.async_write_ha_state))
