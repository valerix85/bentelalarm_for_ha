"""Constants for the Bentel Absoluta integration."""

from __future__ import annotations

from .itv2.const import DEFAULT_PORT  # noqa: F401

DOMAIN = "bentel_absoluta"
MANUFACTURER = "Bentel Security"

CONF_PIN = "pin"
CONF_POLL_INTERVAL = "poll_interval"
CONF_REQUIRE_CODE = "require_code"
CONF_ARM_MODES = "arm_modes"
CONF_EXTRA_ZONES = "extra_zones"


def parse_zone_list(text: str | None) -> list[int]:
    """Parse "15, 16" / "15 16" / "20-22" into a sorted list of zone numbers.

    Raises ValueError on anything else or on numbers outside 1..128.
    """
    zones: set[int] = set()
    for part in (text or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, last = (int(x) for x in part.split("-", 1))
            if first > last:
                raise ValueError(part)
            zones.update(range(first, last + 1))
        else:
            zones.add(int(part))
    if any(not 1 <= z <= 128 for z in zones):
        raise ValueError("zone out of range")
    return sorted(zones)


# Arm modes offered on each partition entity. Absoluta partitions are usually
# just "armed" (away); stay and instant-stay are optional panel features.
ARM_MODE_AWAY = "away"  # Absoluta "inserimento totale"
ARM_MODE_HOME = "home"  # Absoluta "stay" / inserimento parziale
ARM_MODE_NIGHT = "night"  # Absoluta "instant stay" / parziale istantaneo
ARM_MODE_FORCED = "forced"  # Absoluta "forcing away arm": arms even with open zones
ARM_MODES_ALL = [ARM_MODE_AWAY, ARM_MODE_HOME, ARM_MODE_NIGHT, ARM_MODE_FORCED]
DEFAULT_ARM_MODES = [ARM_MODE_AWAY]

DEFAULT_POLL_INTERVAL = 5
MIN_POLL_INTERVAL = 2
MAX_POLL_INTERVAL = 60

EVENT_BENTEL = f"{DOMAIN}_event"
