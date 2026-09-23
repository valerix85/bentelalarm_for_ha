"""Alarm control panel entities: one per partition assigned to the user."""

from __future__ import annotations

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BentelConfigEntry
from .const import CONF_PIN, CONF_REQUIRE_CODE, DOMAIN
from .entity import BentelEntity
from .itv2.client import ITv2Error
from .itv2.const import ArmMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    async_add_entities(BentelPartition(entry, p) for p in client.user_partitions)


class BentelPartition(BentelEntity, AlarmControlPanelEntity):
    """An Absoluta partition."""

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )

    def __init__(self, entry: BentelConfigEntry, partition: int) -> None:
        super().__init__(entry, f"partition_{partition}")
        self.partition = partition
        label = self.client.partition_labels.get(partition)
        if label:
            self._attr_name = label
        else:
            self._attr_translation_key = "partition"
            self._attr_translation_placeholders = {"number": str(partition)}
        self._pin = entry.data[CONF_PIN]
        self._require_code = entry.options.get(CONF_REQUIRE_CODE, False)
        self._attr_code_arm_required = self._require_code
        self._attr_code_format = CodeFormat.NUMBER if self._require_code else None

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = self.client.partitions.get(self.partition)
        if status is None:
            return None
        if status.alarm or status.siren:
            return AlarmControlPanelState.TRIGGERED
        if self.partition in self.client.entry_delay or status.entry_delay:
            return AlarmControlPanelState.PENDING
        if not status.armed:
            return AlarmControlPanelState.DISARMED
        if self.partition in self.client.exit_delay or status.exit_delay:
            return AlarmControlPanelState.ARMING
        if status.away:
            return AlarmControlPanelState.ARMED_AWAY
        if status.stay and (status.no_entry_delay or status.night):
            return AlarmControlPanelState.ARMED_NIGHT
        if status.stay:
            return AlarmControlPanelState.ARMED_HOME
        if status.night:
            return AlarmControlPanelState.ARMED_NIGHT
        # Customised arming modes can arm a partition without a stay/away flag
        return AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    @property
    def extra_state_attributes(self) -> dict:
        status = self.client.partitions.get(self.partition)
        if status is None:
            return {}
        return {
            "ready": status.ready,
            "troubles": status.troubles,
            "alarm_in_memory": status.alarm_in_memory,
            "bypassed_zones": status.bypassed_zones,
            "in_test": status.in_test,
            "fire_alarm": status.fire_alarm,
            "raw_status": status.raw.hex(),
        }

    def _check_code(self, code: str | None) -> None:
        if self._require_code and code != self._pin:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_code")

    async def _run(self, coro) -> None:
        try:
            await coro
        except ITv2Error as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        self._check_code(code)
        await self._run(self.client.disarm(self.partition))

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        self._check_code(code)
        await self._run(self.client.arm(self.partition, ArmMode.AWAY))

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        self._check_code(code)
        await self._run(self.client.arm(self.partition, ArmMode.STAY))

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        self._check_code(code)
        await self._run(self.client.arm(self.partition, ArmMode.INSTANT_STAY))
