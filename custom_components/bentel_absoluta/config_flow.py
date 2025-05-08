import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)


class BentelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            # Validazione connessione
            host = user_input["host"]
            port = user_input.get("port", DEFAULT_PORT)
            try:
                # Test di apertura sessione
                from .utils import BentelProtocol

                proto = BentelProtocol(host, port)
                await proto.connect()
                await proto.disconnect()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=host,
                    data={"host": host, "port": port},
                )
        data_schema = vol.Schema(
            {
                vol.Required("host"): str,
                vol.Optional("port", default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
