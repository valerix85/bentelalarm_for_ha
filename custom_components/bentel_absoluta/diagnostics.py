"""Diagnostics for Bentel Absoluta (PIN redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import BentelConfigEntry
from .const import CONF_PIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BentelConfigEntry
) -> dict[str, Any]:
    client = entry.runtime_data
    info = client.info
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_PIN}),
        "options": dict(entry.options),
        "connected": client.connected,
        "panel": {
            "model": info.model,
            "product_id": info.product_id,
            "firmware": info.firmware,
            "protocol": info.protocol,
            "max_zones": info.max_zones,
            "max_partitions": info.max_partitions,
            "max_outputs": info.max_outputs,
        },
        "user_partitions": client.user_partitions,
        "user_zones": client.user_zones,
        "assigned_zones": client.assigned_zones,
        "extra_zones": client.extra_zones,
        "invalid_zones": sorted(client.invalid_zones),
        "invalid_zone_reasons": client.invalid_zone_reasons,
        "zone_labels": client.zone_labels,
        "outputs": client.outputs,
        "remote_commands": client.remote_commands,
        "partitions": {p: s.raw.hex() for p, s in client.partitions.items()},
        "zones": {z: f"{s.raw:02x}" for z, s in client.zones.items()},
        "outputs_on": sorted(client.outputs_on),
        "single_zone_mode": client._single_zone_mode,  # noqa: SLF001
    }
