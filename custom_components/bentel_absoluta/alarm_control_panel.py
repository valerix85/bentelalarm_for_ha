"""Alarm control panel entities.

One entity per partition assigned to the user, plus a "Global" entity that
arms/disarms all of them at once (Absoluta partition 0 in 0900/0901).
"""

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
from .const import (
    ARM_MODE_AWAY,
    ARM_MODE_FORCED,
    ARM_MODE_HOME,
    ARM_MODE_NIGHT,
    CONF_ARM_MODES,
    CONF_PIN,
    CONF_REQUIRE_CODE,
    DEFAULT_ARM_MODES,
    DOMAIN,
)
from .entity import BentelEntity
from .itv2.client import CommandFailed, ITv2Error
from .itv2.const import ArmMode, Cmd


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[BentelPartition] = [BentelPartition(entry, p) for p in client.user_partitions]
    if len(client.user_partitions) > 1:
        entities.insert(0, BentelGlobal(entry))
    async_add_entities(entities)


def partition_state(client, partition: int) -> AlarmControlPanelState | None:
    """HA state of one Absoluta partition."""
    status = client.partitions.get(partition)
    if status is None:
        return None
    if status.alarm or status.siren:
        return AlarmControlPanelState.TRIGGERED
    if partition in client.entry_delay or status.entry_delay:
        return AlarmControlPanelState.PENDING
    if not status.armed:
        if partition in client.arming_requested:
            return AlarmControlPanelState.ARMING
        return AlarmControlPanelState.DISARMED
    if partition in client.exit_delay or status.exit_delay:
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


class BentelPartition(BentelEntity, AlarmControlPanelEntity):
    """An Absoluta partition."""

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
        modes = entry.options.get(CONF_ARM_MODES, DEFAULT_ARM_MODES)
        features = AlarmControlPanelEntityFeature(0)
        if ARM_MODE_AWAY in modes:
            features |= AlarmControlPanelEntityFeature.ARM_AWAY
        if ARM_MODE_HOME in modes:
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if ARM_MODE_NIGHT in modes:
            features |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if ARM_MODE_FORCED in modes:
            # HA "custom bypass" = Absoluta forced arming (open zones are bypassed)
            features |= AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        self._attr_supported_features = features

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        return partition_state(self.client, self.partition)

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
            "zones": [
                self.client.zone_labels.get(z, str(z))
                for z in self.client.partition_zones.get(self.partition, [])
            ],
            "open_zones": [
                self.client.zone_labels.get(z, str(z))
                for z in self.client.open_zones(self.partition)
            ]
            if self.partition in self.client.partition_zones
            else None,
            "raw_status": status.raw.hex(),
        }

    def _check_code(self, code: str | None) -> None:
        if self._require_code and code != self._pin:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_code")

    async def _run(self, coro) -> None:
        try:
            await coro
        except CommandFailed as err:
            if (
                err.command == Cmd.PARTITION_ARM
                and not err.is_command_error
                and err.code
                in (
                    0x01,
                    0x04,
                )
            ):
                # Refused: typically a zone left open or a blocking condition
                # (mains/battery/tamper fault, notified separately by 0841).
                open_zones = [
                    self.client.zone_labels.get(z, str(z))
                    for z in self.client.open_zones(self.partition)
                ]
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="arm_failed_open_zones" if open_zones else "arm_failed",
                    translation_placeholders={"zones": ", ".join(open_zones)},
                ) from err
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
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

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Forced away arming: the panel arms even with zones left open."""
        self._check_code(code)
        await self._run(self.client.arm(self.partition, ArmMode.FORCE_AWAY))


_ARMED = {
    AlarmControlPanelState.ARMED_AWAY,
    AlarmControlPanelState.ARMED_HOME,
    AlarmControlPanelState.ARMED_NIGHT,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
}


class BentelGlobal(BentelPartition):
    """All partitions of the logged user at once (Absoluta partition 0)."""

    def __init__(self, entry: BentelConfigEntry) -> None:
        super().__init__(entry, 0)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_global"
        self._attr_translation_key = "global"
        self._attr_translation_placeholders = {}

    def _states(self) -> dict[int, AlarmControlPanelState | None]:
        return {p: partition_state(self.client, p) for p in self.client.user_partitions}

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        states = [s for s in self._states().values() if s is not None]
        if not states:
            return None
        for priority in (
            AlarmControlPanelState.TRIGGERED,
            AlarmControlPanelState.PENDING,
            AlarmControlPanelState.ARMING,
        ):
            if priority in states:
                return priority
        armed = [s for s in states if s in _ARMED]
        if not armed:
            return AlarmControlPanelState.DISARMED
        if len(armed) == len(states) and len(set(armed)) == 1:
            return armed[0]  # every partition armed the same way
        # Partially armed (or mixed modes): HA has no "partial" state
        return AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    @property
    def extra_state_attributes(self) -> dict:
        states = self._states()
        name = self.client.partition_labels.get
        return {
            "armed_partitions": [name(p, str(p)) for p, s in states.items() if s in _ARMED],
            "disarmed_partitions": [
                name(p, str(p)) for p, s in states.items() if s == AlarmControlPanelState.DISARMED
            ],
            "partially_armed": any(s in _ARMED for s in states.values())
            and not all(s in _ARMED for s in states.values()),
            "ready": all(st.ready for st in self.client.partitions.values() if not st.armed),
        }
