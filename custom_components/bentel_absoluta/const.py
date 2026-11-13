"""Constants for the Bentel Absoluta integration."""

from __future__ import annotations

from .itv2.const import DEFAULT_PORT, ArmMode  # noqa: F401

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


# What the Home Assistant Away / Home / Night buttons send to the panel
# (0.3.30, issue #18): the default mode, a forced variant (open zones are
# bypassed) or a customised mode A-D, forced or not.
CONF_ARM_AWAY_AS = "arm_away_as"
CONF_ARM_HOME_AS = "arm_home_as"
CONF_ARM_NIGHT_AS = "arm_night_as"
ARM_AS_DEFAULT = "default"
ARM_AS_OPTIONS = [
    ARM_AS_DEFAULT,
    "default_forced",
    "custom_a",
    "custom_b",
    "custom_c",
    "custom_d",
    "custom_a_forced",
    "custom_b_forced",
    "custom_c_forced",
    "custom_d_forced",
]
_ARM_AS_MODES = {
    "custom_a": ArmMode.CUSTOM_A,
    "custom_b": ArmMode.CUSTOM_B,
    "custom_c": ArmMode.CUSTOM_C,
    "custom_d": ArmMode.CUSTOM_D,
    "custom_a_forced": ArmMode.FORCE_CUSTOM_A,
    "custom_b_forced": ArmMode.FORCE_CUSTOM_B,
    "custom_c_forced": ArmMode.FORCE_CUSTOM_C,
    "custom_d_forced": ArmMode.FORCE_CUSTOM_D,
}


def arm_mode_for(options, key: str, default: ArmMode) -> ArmMode:
    """Panel arm mode sent for a Home Assistant mode (``key`` = CONF_ARM_*_AS)."""
    choice = options.get(key, ARM_AS_DEFAULT)
    if choice == "default_forced":
        return ArmMode(int(default) | 0x80)
    return _ARM_AS_MODES.get(choice, default)
