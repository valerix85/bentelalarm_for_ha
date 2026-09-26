"""Switches: programmable outputs enabled for the user and zone bypass."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BentelConfigEntry
from .const import CONF_REQUIRE_CODE, DOMAIN
from .entity import BentelEntity
from .itv2.client import ITv2Error


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[SwitchEntity] = [BentelOutput(entry, n) for n in client.outputs]
    # Bypassing a zone lowers protection: like the arming-mode buttons it cannot
    # ask for a code, so it is not offered when a code is required.
    if not entry.options.get(CONF_REQUIRE_CODE):
        # only zones assigned to the user: bypassing other zones may be refused
        entities += [
            BentelZoneBypass(entry, z) for z in client.user_zones if z in client.assigned_zones
        ]
    async_add_entities(entities)


class BentelOutput(BentelEntity, SwitchEntity):
    def __init__(self, entry: BentelConfigEntry, output: int) -> None:
        super().__init__(entry, f"output_{output}")
        self.output = output
        label = self.client.output_labels.get(output)
        if label:
            self._attr_name = label
        else:
            self._attr_translation_key = "output"
            self._attr_translation_placeholders = {"number": str(output)}

    @property
    def is_on(self) -> bool:
        return self.output in self.client.outputs_on

    async def _set(self, on: bool) -> None:
        try:
            await self.client.set_output(self.output, on)
        except ITv2Error as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class BentelZoneBypass(BentelEntity, SwitchEntity):
    """Zone bypass (esclusione). On = zone bypassed."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, entry: BentelConfigEntry, zone: int) -> None:
        super().__init__(entry, f"zone_{zone}_bypass")
        self.zone = zone
        label = self.client.zone_labels.get(zone)
        if label:
            self._attr_translation_key = "zone_bypass_named"
            self._attr_translation_placeholders = {"zone": label}
        else:
            self._attr_translation_key = "zone_bypass"
            self._attr_translation_placeholders = {"number": str(zone)}

    @property
    def is_on(self) -> bool | None:
        status = self.client.zones.get(self.zone)
        return None if status is None else status.bypassed

    async def _set(self, bypass: bool) -> None:
        try:
            await self.client.set_zone_bypass(self.zone, bypass)
        except ITv2Error as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
