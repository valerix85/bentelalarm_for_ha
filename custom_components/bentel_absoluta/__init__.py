"""Bentel Absoluta integration (ITv2 over TCP via the ABS-IP plug-in)."""

from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_PIN,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    EVENT_BENTEL,
)
from .itv2.client import AbsolutaClient, AuthenticationFailed, ITv2Error

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

type BentelConfigEntry = ConfigEntry[AbsolutaClient]


async def async_setup_entry(hass: HomeAssistant, entry: BentelConfigEntry) -> bool:
    """Connect to the panel and set up the platforms."""
    client = AbsolutaClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PIN],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        poll_interval=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    try:
        await client.start()
    except AuthenticationFailed as err:
        raise ConfigEntryAuthFailed("The panel rejected the user PIN") from err
    except ITv2Error as err:
        raise ConfigEntryNotReady(f"Cannot connect to the Absoluta panel: {err}") from err

    @callback
    def _auth_failed() -> None:
        entry.async_start_reauth(hass)

    @callback
    def _panel_event(event_type: str, data: dict) -> None:
        hass.bus.async_fire(EVENT_BENTEL, {"entry_id": entry.entry_id, "type": event_type, **data})

    client.on_auth_failed = _auth_failed
    entry.async_on_unload(client.add_event_listener(_panel_event))

    async def _stop(_: Event) -> None:
        await client.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BentelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BentelConfigEntry) -> bool:
    """Unload platforms and close the ITv2 session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded


_PARTITION_FLAG = re.compile(r"_partition_\d+_(trouble|ready)$")


async def async_migrate_entry(hass: HomeAssistant, entry: BentelConfigEntry) -> bool:
    """1.1 -> 1.2: per-partition trouble/ready sensors are now disabled by default
    (replaced by the panel-wide "Troubles" sensor): disable the ones created
    enabled by older versions, unless the user already changed them."""
    if entry.version == 1 and entry.minor_version < 2:
        registry = er.async_get(hass)
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg.disabled_by is None and _PARTITION_FLAG.search(reg.unique_id):
                registry.async_update_entity(
                    reg.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
        hass.config_entries.async_update_entry(entry, minor_version=2)
        _LOGGER.debug("Migrated %s to version 1.2", entry.entry_id)
    return True
