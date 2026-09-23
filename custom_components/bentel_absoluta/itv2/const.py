"""ITv2 command codes and constants used with the Absoluta ABS-IP plug-in.

References: "Interactive Protocol V2.00 R2.03" and "ITv2 Usage Guide for
Absoluta Rev 1.05" (Tyco / Bentel Security).
"""

from __future__ import annotations

from enum import IntEnum


class Cmd(IntEnum):
    """ITv2 command codes (two bytes, big endian on the wire)."""

    # Notifications (panel -> 3rd party)
    TIME_DATE = 0x0220
    COMMAND_OUTPUT_ACTIVATION = 0x0222
    EXIT_DELAY = 0x0230
    ENTRY_DELAY = 0x0231
    ARMING_DISARMING = 0x0232
    ARMING_PRE_ALERT = 0x0233
    GENERAL_ACTIVITY = 0x0242
    SIGNAL_STRENGTH = 0x0243
    # Log
    EVENT_BUFFER_READ = 0x0101
    EVENT_BUFFER_READ_RESPONSE = 0x4101
    # Access level
    ENTER_ACCESS_LEVEL = 0x0400
    EXIT_ACCESS_LEVEL = 0x0401
    ACCESS_LEVEL_LEAD_IN_OUT = 0x0402
    # General response
    COMMAND_ERROR = 0x0501
    COMMAND_RESPONSE = 0x0502
    # Connection
    POLL = 0x0600
    OPEN_SESSION = 0x060A
    END_SESSION = 0x060B
    SOFTWARE_VERSION = 0x060D
    REQUEST_ACCESS = 0x060E
    SYSTEM_CAPABILITIES = 0x0613
    # Configuration
    SECTION_READ = 0x0721
    SECTION_READ_RESPONSE = 0x4721
    TIME_DATE_WRITE = 0x0741
    SINGLE_ZONE_BYPASS_WRITE = 0x074A
    ZONE_ASSIGNMENT = 0x0770
    CONFIGURATION_BROADCAST = 0x0771
    PARTITION_ASSIGNMENT = 0x0772
    # Module status
    COMMAND_REQUEST = 0x0800
    ZONE_STATUS = 0x0811
    PARTITION_STATUS = 0x0812
    TROUBLE_DETAIL_NOTIFICATION = 0x0823
    MISC_ALARM = 0x0841
    # Module control
    PARTITION_ARM = 0x0900
    PARTITION_DISARM = 0x0901
    COMMAND_OUTPUT = 0x0902
    USER_ACTIVITY = 0x0912


# Commands that carry an application sequence number right after the
# command code. When the panel sends one of these we must answer with a
# Command Response (0502).
CMDS_WITH_APP_SEQ = {
    Cmd.OPEN_SESSION,
    Cmd.REQUEST_ACCESS,
    Cmd.ENTER_ACCESS_LEVEL,
    Cmd.EXIT_ACCESS_LEVEL,
    Cmd.COMMAND_REQUEST,
    Cmd.SECTION_READ,
    Cmd.EVENT_BUFFER_READ,
    Cmd.TIME_DATE_WRITE,
    Cmd.SINGLE_ZONE_BYPASS_WRITE,
    Cmd.PARTITION_ARM,
    Cmd.PARTITION_DISARM,
    Cmd.COMMAND_OUTPUT,
    Cmd.USER_ACTIVITY,
}


class ArmMode(IntEnum):
    """Arm modes accepted by Partition Arm Control (0900) on Absoluta."""

    STAY = 0x01
    AWAY = 0x02
    INSTANT_STAY = 0x07
    CUSTOM_A = 0x0D
    CUSTOM_B = 0x0E
    CUSTOM_C = 0x0F
    CUSTOM_D = 0x10
    FORCE_STAY = 0x81
    FORCE_AWAY = 0x82
    FORCE_INSTANT_STAY = 0x87


class UserActivity(IntEnum):
    KEEP_ALIVE = 0x04
    CLEAR_ALARM_MEMORY = 0x08
    CLEAR_CALL_QUEUE = 0x09
    CLEAR_FAULTS = 0x0A
    CLEAR_TAMPERS = 0x0B
    CLEAR_ALL = 0x0C


# Command Error (0501) codes
COMMAND_ERRORS = {
    0x01: "command length wrong",
    0x02: "unknown/unsupported command",
    0x03: "wrong sequence number",
    0x04: "panel not responsive",
    0x05: "invalid pass through command",
    0x06: "invalid destination",
    0x07: "invalid or inactive session",
    0x08: "insufficient buffer size",
    0x09: "system is locked out",
    0x0A: "unknown/unsupported sub command",
    0x0B: "power up shunt in effect",
}

# Command Response (0502) codes (generic ones; 0x01..0x04 are per command)
RESPONSE_CODES = {
    0x00: "success",
    0x10: "not in correct programming mode",
    0x11: "invalid access code",
    0x12: "access code required",
    0x13: "system/partition busy",
    0x14: "invalid partition",
    0x17: "function not available",
    0x18: "internal error",
    0x19: "command timed out",
    0x1A: "no troubles present",
    0x1B: "no requested alarms found",
    0x1C: "invalid device/module",
    0x1D: "invalid trouble type",
}

RESP_INVALID_ACCESS_CODE = 0x11

# Product IDs reported in Software Version (060D)
PRODUCT_IDS = {
    0x00BD: "Absoluta 128",
    0x00BE: "Absoluta 48",
    0x00BF: "Absoluta 18",
    0x00B2: "Absoluta 104",
    0x00B3: "Absoluta 42",
    0x00B4: "Absoluta 16",
    0x00BC: "Absoluta 630",
}

# Arming types reported by Arming/Disarming notification (0232)
ARMING_TYPES = {
    0x00: "disarm",
    0x01: "stay",
    0x02: "away",
    0x06: "user",
    0x0D: "custom_a",
    0x0E: "custom_b",
    0x0F: "custom_c",
    0x10: "custom_d",
    0x11: "instant_stay",
}

# Miscellaneous alarm (0841) blocking conditions
MISC_ALARM_TYPES = {
    0x00: "interconnection",
    0x01: "siren",
    0x0D: "battery",
    0x0E: "tamper",
    0x10: "communication",
    0xFF: "mains",
}

# Configuration Broadcast (0771) option IDs
OPT_ZONE_LABEL = 0x01
OPT_PARTITION_LABEL = 0x03  # offset 1 = system label, 2..17 = partitions 1..16
OPT_OUTPUT_LABEL = 0x04  # 1..50 outputs, 51..82 remote commands 1..32
OPT_ARMING_MODE_LABEL = 0x0D  # 1..4 = modes A..D

# Section Read (0721) sections
SECTION_ENABLED_OUTPUTS = 0x0001

MAX_ZONES = 128
MAX_PARTITIONS = 16
MAX_OUTPUTS = 50
MAX_REMOTE_COMMANDS = 32
REMOTE_COMMAND_OUTPUT_OFFSET = 56  # remote command n == output number 56 + n

DEFAULT_PORT = 3064
