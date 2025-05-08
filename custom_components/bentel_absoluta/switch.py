from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN, CMD_OUTPUT_CTRL

async def async_setup_entry(hass, entry, async_add_entities):
    protocol = hass.data[DOMAIN][entry.entry_id]
    entities = [OutputSwitch(protocol, out) for out in protocol.outputs]
    async_add_entities(entities)

class OutputSwitch(SwitchEntity):
    def __init__(self, protocol, output):
        self.protocol = protocol
        self.output = output
        self._attr_name = f"Output {output.id}"
        self._attr_unique_id = f"{DOMAIN}_output_{output.id}"
        self._state = False

    @property
    def is_on(self):
        return self._state

    async def async_turn_on(self, **kwargs):
        await self.protocol.send_command(CMD_OUTPUT_CTRL, bytes([self.output.id, 1]))
        self._state = True

    async def async_turn_off(self, **kwargs):
        await self.protocol.send_command(CMD_OUTPUT_CTRL, bytes([self.output.id, 0]))
        self._state = False