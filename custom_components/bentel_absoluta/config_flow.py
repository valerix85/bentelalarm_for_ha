"""Config flow for Bentel Absoluta."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from .const import (
    ARM_MODES_ALL,
    CONF_ARM_MODES,
    CONF_EXTRA_ZONES,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_REQUIRE_CODE,
    DEFAULT_ARM_MODES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    parse_zone_list,
)
from .itv2.client import (
    AbsolutaClient,
    AuthenticationFailed,
    HandshakeFailed,
    ITv2Error,
    TcpConnectFailed,
)

_LOGGER = logging.getLogger(__name__)

PIN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_PIN): PIN_SELECTOR,
    }
)


async def _validate(host: str, port: int, pin: str) -> AbsolutaClient:
    """Open a session, log in and close it. Returns the client (for its info)."""
    client = AbsolutaClient(host, pin, port, load_labels=False)
    try:
        await client.connect(discover=False)
    finally:
        await client.disconnect()
    return client


def _valid_pin(pin: str) -> bool:
    return pin.isdigit() and 1 <= len(pin) <= 6


class BentelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    MINOR_VERSION = 2

    _error_detail = ""

    async def _try(self, host: str, port: int, pin: str, errors: dict) -> AbsolutaClient | None:
        self._error_detail = ""
        if not _valid_pin(pin):
            errors[CONF_PIN] = "invalid_pin"
            return None
        try:
            return await _validate(host, port, pin)
        except AuthenticationFailed:
            errors["base"] = "invalid_auth"
        except TcpConnectFailed as err:
            _LOGGER.warning("Bentel Absoluta %s:%s: %s", host, port, err)
            self._error_detail = str(err)
            errors["base"] = "cannot_connect"
        except HandshakeFailed as err:
            _LOGGER.warning("Bentel Absoluta %s:%s: %s", host, port, err)
            self._error_detail = str(err)
            errors["base"] = "handshake_failed"
        except ITv2Error as err:
            _LOGGER.warning("Bentel Absoluta %s:%s: %s", host, port, err)
            self._error_detail = str(err)
            errors["base"] = "cannot_connect"
        except Exception as err:
            _LOGGER.exception("Unexpected error")
            self._error_detail = repr(err)
            errors["base"] = "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            pin = str(user_input[CONF_PIN]).strip()
            client = await self._try(host, port, pin, errors)
            if client is not None:
                unique = format_mac(client.info.identifier) if client.info.identifier else host
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                return self.async_create_entry(
                    title=f"Bentel {client.info.model}",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_PIN: pin},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
            description_placeholders={"error_detail": self._error_detail},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            pin = str(user_input[CONF_PIN]).strip()
            if await self._try(entry.data[CONF_HOST], entry.data[CONF_PORT], pin, errors):
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PIN: pin})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): PIN_SELECTOR}),
            errors=errors,
            description_placeholders={"error_detail": self._error_detail},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host/port/PIN of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            pin = str(user_input[CONF_PIN]).strip()
            # The panel accepts a single ITv2 connection: free it first.
            await self.hass.config_entries.async_unload(entry.entry_id)
            client = await self._try(host, port, pin, errors)
            if client is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_PORT: port, CONF_PIN: pin}
                )
            await self.hass.config_entries.async_setup(entry.entry_id)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
            description_placeholders={"error_detail": self._error_detail},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BentelOptionsFlow()


class BentelOptionsFlow(OptionsFlow):
    """Polling interval and code requirement."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_ARM_MODES):
                errors[CONF_ARM_MODES] = "no_arm_mode"
            try:
                zones = parse_zone_list(user_input.get(CONF_EXTRA_ZONES))
            except ValueError:
                errors[CONF_EXTRA_ZONES] = "invalid_zone_list"
            if not errors:
                user_input[CONF_EXTRA_ZONES] = ", ".join(str(z) for z in zones)
                return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_ARM_MODES, default=DEFAULT_ARM_MODES): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=ARM_MODES_ALL,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="arm_modes",
                    )
                ),
                vol.Required(CONF_REQUIRE_CODE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_EXTRA_ZONES, default=""): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options),
            errors=errors,
        )
