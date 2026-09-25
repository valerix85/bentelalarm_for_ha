"""Buttons: remote commands, customised arming modes A-D, clear memory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BentelConfigEntry
from .const import CONF_REQUIRE_CODE, DOMAIN
from .entity import BentelEntity
from .itv2.client import AbsolutaClient, ITv2Error
from .itv2.const import ArmMode, UserActivity

ARM_MODES = {
    "A": ArmMode.CUSTOM_A,
    "B": ArmMode.CUSTOM_B,
    "C": ArmMode.CUSTOM_C,
    "D": ArmMode.CUSTOM_D,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[BentelButton] = []
    for n in client.remote_commands:
        label = client.remote_command_labels.get(n)
        entities.append(
            BentelButton(
                entry,
                f"remote_command_{n}",
                lambda c, n=n: c.trigger_remote_command(n),
                name=label,
                translation_key=None if label else "remote_command",
                placeholders={"number": str(n)},
            )
        )
    # Arming-mode buttons bypass the code check, so skip them if a code is required
    arm_modes = {} if entry.options.get(CONF_REQUIRE_CODE) else ARM_MODES
    for letter, mode in arm_modes.items():
        label = client.arming_mode_labels.get(letter)
        entities.append(
            BentelButton(
                entry,
                f"arm_mode_{letter.lower()}",
                lambda c, mode=mode: c.arm(0, mode),
                translation_key="arm_mode",
                placeholders={"mode": label or letter},
                enabled_default=bool(label),
            )
        )
    entities.append(
        BentelButton(
            entry,
            "clear_alarm_memory",
            lambda c: c.user_activity(UserActivity.CLEAR_ALARM_MEMORY),
            translation_key="clear_alarm_memory",
            category=EntityCategory.CONFIG,
        )
    )
    entities.append(
        BentelButton(
            entry,
            "sync_time",
            lambda c: c.sync_time(dt_util.now().replace(tzinfo=None, microsecond=0)),
            translation_key="sync_time",
            category=EntityCategory.CONFIG,
        )
    )
    entities.append(
        BentelButton(
            entry,
            "clear_all",
            lambda c: c.user_activity(UserActivity.CLEAR_ALL),
            translation_key="clear_all",
            category=EntityCategory.CONFIG,
        )
    )
    async_add_entities(entities)


class BentelButton(BentelEntity, ButtonEntity):
    def __init__(
        self,
        entry: BentelConfigEntry,
        key: str,
        action: Callable[[AbsolutaClient], Awaitable[None]],
        *,
        name: str | None = None,
        translation_key: str | None = None,
        placeholders: dict[str, str] | None = None,
        category: EntityCategory | None = None,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(entry, key)
        self._action = action
        if name:
            self._attr_name = name
        else:
            self._attr_translation_key = translation_key
            self._attr_translation_placeholders = placeholders or {}
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled_default

    async def async_press(self) -> None:
        try:
            await self._action(self.client)
        except ITv2Error as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
