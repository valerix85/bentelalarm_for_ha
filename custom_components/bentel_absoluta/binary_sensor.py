"""Binary sensors: zones, partition troubles/ready and panel connection."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BentelConfigEntry
from .entity import BentelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BentelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    entities: list[BinarySensorEntity] = [BentelConnection(entry), BentelTroubles(entry)]
    entities += [BentelZone(entry, z) for z in client.user_zones]
    for part in client.user_partitions:
        entities.append(BentelPartitionFlag(entry, part, "trouble"))
        entities.append(BentelPartitionFlag(entry, part, "ready"))
    async_add_entities(entities)


class BentelZone(BentelEntity, BinarySensorEntity):
    """Zone open/closed. Device class can be changed from the HA UI."""

    def __init__(self, entry: BentelConfigEntry, zone: int) -> None:
        super().__init__(entry, f"zone_{zone}")
        self.zone = zone
        label = self.client.zone_labels.get(zone)
        if label:
            self._attr_name = label
        else:
            self._attr_translation_key = "zone"
            self._attr_translation_placeholders = {"number": str(zone)}

    @property
    def is_on(self) -> bool | None:
        status = self.client.zones.get(self.zone)
        return None if status is None else status.open

    @property
    def extra_state_attributes(self) -> dict:
        status = self.client.zones.get(self.zone)
        if status is None:
            return {"zone": self.zone}
        return {
            "zone": self.zone,
            "alarm": status.alarm,
            "alarm_in_memory": status.alarm_in_memory,
            "tamper": status.tamper,
            "fault": status.fault,
            "low_battery": status.low_battery,
            "bypassed": status.bypassed,
            "delinquency": status.delinquency,
        }


class BentelPartitionFlag(BentelEntity, BinarySensorEntity):
    """Partition 'trouble' (problem) or 'ready to arm'."""

    def __init__(self, entry: BentelConfigEntry, partition: int, kind: str) -> None:
        super().__init__(entry, f"partition_{partition}_{kind}")
        self.partition = partition
        self.kind = kind
        label = self.client.partition_labels.get(partition)
        if label:
            self._attr_translation_key = f"partition_{kind}_named"
            self._attr_translation_placeholders = {"partition": label}
        else:
            self._attr_translation_key = f"partition_{kind}"
            self._attr_translation_placeholders = {"number": str(partition)}
        if kind == "trouble":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        # Per-partition flags are usually identical: the panel-wide "Troubles"
        # sensor is the one enabled by default.
        self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool | None:
        status = self.client.partitions.get(self.partition)
        if status is None:
            return None
        return status.troubles if self.kind == "trouble" else status.ready


class BentelConnection(BentelEntity, BinarySensorEntity):
    """ITv2 session state (always available)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connection"

    def __init__(self, entry: BentelConfigEntry) -> None:
        super().__init__(entry, "connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.client.connected

    @property
    def extra_state_attributes(self) -> dict:
        info = self.client.info
        return {
            "model": info.model,
            "firmware": info.firmware,
            "mac": info.identifier,
            "system_label": self.client.system_label,
            "panel_time": self.client.panel_time.isoformat() if self.client.panel_time else None,
        }


class BentelTroubles(BentelEntity, BinarySensorEntity):
    """On when any partition of the user reports troubles (faults, mains, battery...)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "troubles"

    def __init__(self, entry: BentelConfigEntry) -> None:
        super().__init__(entry, "troubles")

    @property
    def is_on(self) -> bool | None:
        if not self.client.partitions:
            return None
        return any(s.troubles for s in self.client.partitions.values())

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "partitions_with_troubles": [
                self.client.partition_labels.get(p, str(p))
                for p, s in sorted(self.client.partitions.items())
                if s.troubles
            ],
            "troubles_in_memory": any(
                s.troubles_in_memory for s in self.client.partitions.values()
            ),
        }
