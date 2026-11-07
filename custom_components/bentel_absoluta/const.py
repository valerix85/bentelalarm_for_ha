"""Constants for the Bentel Absoluta integration."""

from __future__ import annotations

from .itv2.const import DEFAULT_PORT  # noqa: F401

DOMAIN = "bentel_absoluta"
MANUFACTURER = "Bentel Security"

CONF_PIN = "pin"
CONF_POLL_INTERVAL = "poll_interval"
CONF_REQUIRE_CODE = "require_code"
# Also require the code to arm (only with CONF_REQUIRE_CODE). Missing in
# entries created before 0.3.26: it then follows CONF_REQUIRE_CODE.
CONF_REQUIRE_CODE_ARM = "require_code_arm"


def code_required(options, *, arm: bool) -> bool:
    """Whether Home Assistant must ask for the PIN to disarm (arm=False) or arm."""
    if not options.get(CONF_REQUIRE_CODE, False):
        return False
    return options.get(CONF_REQUIRE_CODE_ARM, True) if arm else True


CONF_ARM_MODES = "arm_modes"


# Arm modes offered on each partition entity. Absoluta partitions are usually
# just "armed" (away); stay and instant-stay are optional panel features.
ARM_MODE_AWAY = "away"  # Absoluta "inserimento totale"
ARM_MODE_HOME = "home"  # Absoluta "stay" / inserimento parziale
ARM_MODE_NIGHT = "night"  # Absoluta "instant stay" / parziale istantaneo
ARM_MODE_FORCED = "forced"  # Absoluta "forcing away arm": arms even with open zones
ARM_MODES_ALL = [ARM_MODE_AWAY, ARM_MODE_HOME, ARM_MODE_NIGHT, ARM_MODE_FORCED]
DEFAULT_ARM_MODES = [ARM_MODE_AWAY]

DEFAULT_POLL_INTERVAL = 5
MIN_POLL_INTERVAL = 1
MAX_POLL_INTERVAL = 60

EVENT_BENTEL = f"{DOMAIN}_event"
