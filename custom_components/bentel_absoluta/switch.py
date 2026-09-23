"""Switches for the programmable outputs enabled for the user."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BentelConfigEntry
from .const import DOMAIN
from .entity import BentelEntity
from .itv2.client import ITv2Error


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    async_add_entities(BentelOutput(entry, n) for n in client.outputs)


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
