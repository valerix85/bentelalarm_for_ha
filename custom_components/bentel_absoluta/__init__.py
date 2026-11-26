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
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_PIN,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    EVENT_BENTEL,
)
from .itv2.client import AbsolutaClient, AuthenticationFailed, CommandFailed, ITv2Error

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

type BentelConfigEntry = ConfigEntry[AbsolutaClient]

SERVICE_SMS_PREVIEW = "sms_preview"


async def _sms_preview(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Read-only diagnostic: ask each panel for its SMS preview (ITv2 0103) and
    return / log the raw answer. Nothing is deleted."""
    result: dict = {}
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state.name == "LOADED"
    ]
    if not entries:
        raise HomeAssistantError("Bentel Absoluta is not loaded")
    for entry in entries:
        try:
            raw = await entry.runtime_data.sms_preview(call.data.get("count", 5))
            answer = {"supported": True, "raw": raw.hex(" ")}
        except CommandFailed as err:
            answer = {"supported": False, "error": str(err), "code": err.code}
        except (ITv2Error, TimeoutError) as err:
            answer = {"supported": None, "error": f"no answer: {err}"}
        _LOGGER.info("SMS preview (0103) answer from %s: %s", entry.title, answer)
        result[entry.entry_id] = answer
    return result


async def async_setup_entry(hass: HomeAssistant, entry: BentelConfigEntry) -> bool:
    """Connect to the panel and set up the platforms."""
    client = AbsolutaClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PIN],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        poll_interval=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    # Arm modes survive a restart: the panel only reports "armed", not how
    store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.arming")
    client.load_arming_snapshot(await store.async_load())
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

    saved: list[dict | None] = [None]

    @callback
    def _save_arming() -> None:
        snapshot = client.arming_snapshot()
        if snapshot != saved[0]:
            saved[0] = snapshot
            store.async_delay_save(client.arming_snapshot, 5)

    client.on_auth_failed = _auth_failed
    entry.async_on_unload(client.add_listener(_save_arming))
    entry.async_on_unload(client.add_event_listener(_panel_event))

    async def _stop(_: Event) -> None:
        await client.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    entry.runtime_data = client
    if not hass.services.has_service(DOMAIN, SERVICE_SMS_PREVIEW):

        async def _handle_sms_preview(call: ServiceCall) -> ServiceResponse:
            return await _sms_preview(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SMS_PREVIEW,
            _handle_sms_preview,
            supports_response=SupportsResponse.ONLY,
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: BentelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BentelConfigEntry) -> bool:
    """Unload platforms and close the ITv2 session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
        others = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state.name == "LOADED"
        ]
        if not others:
            hass.services.async_remove(DOMAIN, SERVICE_SMS_PREVIEW)
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
