import logging
from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity
from .const import DOMAIN, CMD_PARTITION_ARM, CMD_PARTITION_DISARM

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    protocol = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for part in protocol.partitions:
        entities.append(BentelAlarmEntity(protocol, part))
    async_add_entities(entities)


class BentelAlarmEntity(AlarmControlPanelEntity):
    def __init__(self, protocol, partition):
        self.protocol = protocol
        self.partition = partition
        self._attr_name = f"Partition {partition.id}"
        self._attr_unique_id = f"{DOMAIN}_partition_{partition.id}"
        self._state = None

    @property
    def state(self):
        return self._state

    async def async_update(self):
        data = await self.protocol.send_command(0x0812, bytes([self.partition.id]))
        # parse status: 0=disarmed, 1=armed
        self._state = "armed_away" if data[0] == 1 else "disarmed"

    async def async_alarm_arm_away(self, code=None):
        # comando arm away
        await self.protocol.send_command(
            CMD_PARTITION_ARM, bytes([self.partition.id, 0x02])
        )
        self._state = "armed_away"

    async def async_alarm_disarm(self, code=None):
        # comando disarm
        await self.protocol.send_command(
            CMD_PARTITION_DISARM, bytes([self.partition.id])
        )
        self._state = "disarmed"
