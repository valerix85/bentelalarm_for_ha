import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    protocol = hass.data[DOMAIN][entry.entry_id]
    # Supponiamo che protocol.zones sia mappato a lista di zone
    entities = []
    for zone in protocol.zones:
        entities.append(ZoneBinarySensor(protocol, zone))
    async_add_entities(entities)


class ZoneBinarySensor(BinarySensorEntity):
    def __init__(self, protocol, zone):
        self.protocol = protocol
        self.zone = zone
        self._attr_name = f"Zone {zone.id}"
        self._attr_unique_id = f"{DOMAIN}_zone_{zone.id}"
        self._state = None

    @property
    def is_on(self):
        # stato allarme per la zona
        return self._state

    async def async_update(self):
        # richiede lo stato zona 0811
        payload = bytes([self.zone.id])
        data = await self.protocol.send_command(0x0811, payload)
        # parse: data[0] bitmask: bit0=alarm, bit1=tamper...
        alarm = bool(data[0] & 0x01)
        self._state = alarm
