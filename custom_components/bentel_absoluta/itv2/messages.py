"""Encoding / decoding of ITv2 application payloads used with Absoluta.

All ``parse_*`` functions take the payload that follows the 2-byte command
code (and the app sequence byte, when present) and raise ``ValueError`` when
the payload is too short.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .const import PRODUCT_IDS

# --------------------------------------------------------------------------
# Primitive helpers
# --------------------------------------------------------------------------


def var_bytes(value: int | None) -> bytes:
    """Encode a 'Variable Bytes' number (length prefix + big endian value).

    ``None`` encodes as a zero-length field (a single 0x00 byte).
    """
    if value is None:
        return b"\x00"
    if value < 0:
        raise ValueError("negative value")
    n = max(1, (value.bit_length() + 7) // 8)
    return bytes([n]) + value.to_bytes(n, "big")


def read_var(data: bytes, off: int) -> tuple[int | None, int]:
    """Read a 'Variable Bytes' number. Returns (value or None, new offset)."""
    if off >= len(data):
        raise ValueError("truncated variable-bytes length")
    n = data[off]
    off += 1
    if n == 0:
        return None, off
    if off + n > len(data):
        raise ValueError("truncated variable-bytes value")
    return int.from_bytes(data[off : off + n], "big"), off + n


def bitmask_to_list(mask: bytes, offset: int = 1) -> list[int]:
    """Bit Mask format: byte 0 bit 0 is item ``offset``, byte 0 bit 7 is
    item ``offset + 7``, byte 1 bit 0 is item ``offset + 8`` ..."""
    items = []
    for i, byte in enumerate(mask):
        for bit in range(8):
            if byte & (1 << bit):
                items.append(offset + i * 8 + bit)
    return items


def list_to_bitmask(items: list[int], length: int | None = None) -> bytes:
    top = max(items) if items else 0
    size = length if length is not None else max(1, (top + 7) // 8)
    out = bytearray(size)
    for item in items:
        idx = item - 1
        out[idx // 8] |= 1 << (idx % 8)
    return bytes(out)


def encode_pin(pin: str) -> bytes:
    """User PIN -> 'Programming Access Code' (3 bytes, 0xA filled).

    Example: "12345" -> A1 23 45, "1234" -> AA 12 34.
    """
    if not pin.isdigit() or not 1 <= len(pin) <= 6:
        raise ValueError("PIN must be 1-6 digits")
    digits = "A" * (6 - len(pin)) + pin
    return bytes.fromhex(digits)


def decode_datetime(raw: bytes) -> dt.datetime | None:
    """ITv2 4-byte Date Time format (hour5 min6 sec6 year6 month4 day5)."""
    if len(raw) < 4:
        return None
    v = int.from_bytes(raw[:4], "big")
    hour = (v >> 27) & 0x1F
    minute = (v >> 21) & 0x3F
    second = (v >> 15) & 0x3F
    year = 2000 + ((v >> 9) & 0x3F)
    month = (v >> 5) & 0x0F
    day = v & 0x1F
    try:
        return dt.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def encode_datetime(value: dt.datetime) -> bytes:
    v = (
        (value.hour & 0x1F) << 27
        | (value.minute & 0x3F) << 21
        | (value.second & 0x3F) << 15
        | ((value.year - 2000) & 0x3F) << 9
        | (value.month & 0x0F) << 5
        | (value.day & 0x1F)
    )
    return v.to_bytes(4, "big")


def decode_label(raw: bytes) -> str:
    return raw.replace(b"\xff", b"").replace(b"\x00", b"").decode("cp1252", "replace").strip()


# --------------------------------------------------------------------------
# Status models
# --------------------------------------------------------------------------


@dataclass(slots=True)
class PartitionStatus:
    """Decoded Partition Status (0812), 3 bytes per partition.

    Byte 1 bit 0 is the 'armed' flag; the meaning of bits 1..7 depends on it
    (see protocol spec 6.7.4 - the table in the PDF is laid out right to left).
    """

    raw: bytes = b"\x00\x00\x00"

    def _bit(self, byte: int, bit: int) -> bool:
        return len(self.raw) > byte and bool(self.raw[byte] & (1 << bit))

    # Byte 1
    @property
    def armed(self) -> bool:
        return self._bit(0, 0)

    @property
    def stay(self) -> bool:
        return self.armed and self._bit(0, 1)

    @property
    def away(self) -> bool:
        return self.armed and self._bit(0, 2)

    @property
    def night(self) -> bool:
        return self.armed and self._bit(0, 3)

    @property
    def no_entry_delay(self) -> bool:
        return self.armed and self._bit(0, 4)

    @property
    def exit_delay(self) -> bool:
        return self.armed and self._bit(0, 5)

    @property
    def entry_delay(self) -> bool:
        return self.armed and self._bit(0, 6)

    @property
    def ready(self) -> bool:
        """Disarmed and ready to arm (also ready to force-arm)."""
        return not self.armed and (self._bit(0, 1) or self._bit(0, 2))

    @property
    def not_ready(self) -> bool:
        return not self.armed and self._bit(0, 3)

    # Byte 2
    @property
    def alarm(self) -> bool:
        return self._bit(1, 0)

    @property
    def troubles(self) -> bool:
        return self._bit(1, 1)

    @property
    def bypassed_zones(self) -> bool:
        return self._bit(1, 2)

    @property
    def in_test(self) -> bool:
        return self._bit(1, 3)

    @property
    def alarm_in_memory(self) -> bool:
        return self._bit(1, 4)

    @property
    def siren(self) -> bool:
        return self._bit(1, 6)

    # Byte 3
    @property
    def fire_alarm(self) -> bool:
        return self._bit(2, 1)

    @property
    def troubles_in_memory(self) -> bool:
        return self._bit(2, 5)


@dataclass(slots=True)
class ZoneStatus:
    """Decoded zone status byte (0811)."""

    raw: int = 0

    @property
    def open(self) -> bool:
        return bool(self.raw & 0x01)

    @property
    def tamper(self) -> bool:
        return bool(self.raw & 0x02)

    @property
    def fault(self) -> bool:
        return bool(self.raw & 0x04)

    @property
    def low_battery(self) -> bool:
        return bool(self.raw & 0x08)

    @property
    def delinquency(self) -> bool:
        return bool(self.raw & 0x10)

    @property
    def alarm(self) -> bool:
        return bool(self.raw & 0x20)

    @property
    def alarm_in_memory(self) -> bool:
        return bool(self.raw & 0x40)

    @property
    def bypassed(self) -> bool:
        return bool(self.raw & 0x80)


@dataclass(slots=True)
class PanelInfo:
    firmware: str | None = None
    product_id: int | None = None
    protocol: str | None = None
    identifier: str | None = None  # ABS-IP MAC address
    max_zones: int | None = None
    max_partitions: int | None = None
    max_outputs: int | None = None
    max_users: int | None = None

    @property
    def model(self) -> str:
        if self.product_id is None:
            return "Absoluta"
        return PRODUCT_IDS.get(self.product_id, f"Absoluta (0x{self.product_id:04X})")


@dataclass(slots=True)
class ConfigLabels:
    option: int
    first: int
    labels: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


def parse_partition_status(p: bytes) -> dict[int, PartitionStatus]:
    """0812: mask length, mask, bytes per partition, statuses."""
    mlen = p[0]
    mask = p[1 : 1 + mlen]
    off = 1 + mlen
    size = p[off]
    off += 1
    result = {}
    for part in bitmask_to_list(mask):
        chunk = p[off : off + size]
        if len(chunk) < size:
            break
        result[part] = PartitionStatus(bytes(chunk))
        off += size
    return result


def parse_zone_status(p: bytes) -> dict[int, ZoneStatus]:
    """0811: zone number (var), number of zones (var), status length, data."""
    first, off = read_var(p, 0)
    count, off = read_var(p, off)
    slen = p[off]
    off += 1
    result = {}
    if first is None or count is None or slen == 0:
        return result
    for i in range(count):
        chunk = p[off : off + slen]
        if len(chunk) < slen:
            break
        result[first + i] = ZoneStatus(chunk[0])
        off += slen
    return result


def parse_partition_assignment(p: bytes) -> list[int]:
    """0772: length + bitmask of partitions assigned to the logged user."""
    mlen = p[0]
    return bitmask_to_list(p[1 : 1 + mlen])


def parse_zone_assignment(p: bytes) -> tuple[int | None, list[int]]:
    """0770: partition (var) + fixed 16-byte zone bitmask."""
    part, off = read_var(p, 0)
    return part, bitmask_to_list(p[off:])


def parse_output_activation(p: bytes) -> set[int]:
    """0222: partition mask length (+mask), output mask length, output mask."""
    plen = p[0]
    off = 1 + plen
    olen = p[off]
    return set(bitmask_to_list(p[off + 1 : off + 1 + olen]))


def parse_system_capabilities(p: bytes) -> dict[str, int | None]:
    names = ("zones", "users", "partitions", "fobs", "prox", "outputs")
    out: dict[str, int | None] = {}
    off = 0
    for name in names:
        if off >= len(p):
            break
        out[name], off = read_var(p, off)
    return out


def parse_software_version(p: bytes, info: PanelInfo) -> None:
    """060D: VV SS BN TR PPhi PPlo PIDhi PIDlo Market Customer Approvals."""
    if len(p) < 8:
        raise ValueError("software version too short")
    # e.g. 35 00 00 1E -> "3.50.30" (version 3.5, sub 0, test release 30)
    info.firmware = f"{p[0] >> 4}.{p[0] & 0xF}{p[1]:X}.{p[3]:02d}"
    if p[2]:
        info.firmware += f" (build {p[2]})"
    info.protocol = f"{p[4]:X}.{p[5]:02X}"
    info.product_id = (p[6] << 8) | p[7]


def parse_delay(p: bytes) -> tuple[int | None, int]:
    """0230 / 0231: partition (var), status."""
    part, off = read_var(p, 0)
    return part, p[off]


def parse_configuration(p: bytes) -> ConfigLabels:
    """0771: option (var), from (var), to (var), data length (var), data.

    On a real Absoluta (fw 3.60) "data length" is the TOTAL length of the
    data for the whole range (e.g. 8 labels -> 0x80), as in the usage guide
    example (partitions 7..9 -> 0x30). Older clients requesting one label at
    a time never notice. Accept both interpretations.
    """
    option, off = read_var(p, 0)
    first, off = read_var(p, off)
    last = first
    if first is not None:
        last, off = read_var(p, off)
    dlen, off = read_var(p, off)
    count = 1 if first is None or last is None else max(1, last - first + 1)
    data = p[off:]
    size = dlen or 0
    if count > 1 and size and size % count == 0 and len(data) < size * count:
        size //= count  # total length: split evenly
    labels = []
    if size:
        for i in range(count):
            chunk = data[i * size : (i + 1) * size]
            if len(chunk) < size:
                break
            labels.append(decode_label(chunk))
    return ConfigLabels(option or 0, first or 0, labels)


def parse_section_read_response(p: bytes) -> tuple[int, bytes]:
    """4721 (flag 0x00): flags, section (2 bytes), data."""
    flags = p[0]
    if flags != 0:
        raise ValueError(f"unsupported section flags {flags:02X}")
    section = (p[1] << 8) | p[2]
    return section, p[3:]


# --------------------------------------------------------------------------
# Builders (payload after the app sequence byte)
# --------------------------------------------------------------------------


def build_open_session() -> bytes:
    return bytes(
        [
            0x8F,  # device type: generic 3rd party
            0x00,
            0x00,  # device id
            0x01,
            0x00,  # software version 1.00 (BCD)
            0x02,
            0x03,  # protocol version 2.03 (BCD)
            0x00,
            0x32,  # TX buffer: 50 bytes (must be <= 50)
            0x04,
            0x00,  # RX buffer: 1024 bytes (must be >= 200)
            0x00,
            0x01,  # "future", hard coded to 1
            0x00,  # encryption: none
        ]
    )


def build_request_access(identifier: bytes = b"\x00\x00\x00\x00") -> bytes:
    return bytes([len(identifier)]) + identifier


# Our own Software Version (060D) fields, as sent by working 3rd party clients.
OWN_SOFTWARE_VERSION = bytes.fromhex("350000 1E 0203 0000 01 03 01".replace(" ", ""))


def build_enter_access_level(pin: str) -> bytes:
    code = encode_pin(pin)
    return b"\x00" + bytes([0x02, len(code)]) + code  # partition none, user level


def build_command_request(cmd: int, data: bytes = b"") -> bytes:
    return cmd.to_bytes(2, "big") + data


def build_partition_status_request(partitions: list[int]) -> bytes:
    mask = list_to_bitmask(partitions)
    return bytes([len(mask)]) + mask


def build_zone_status_request(first: int, count: int) -> bytes:
    return var_bytes(first) + var_bytes(count)


def build_label_request(option: int, first: int, last: int) -> bytes:
    return var_bytes(option) + var_bytes(first) + var_bytes(last)


def build_section_read(section: int) -> bytes:
    return bytes([0x00]) + section.to_bytes(2, "big")


def build_arm(partition: int, mode: int) -> bytes:
    return var_bytes(partition or None) + bytes([mode])


def build_disarm(partition: int) -> bytes:
    return var_bytes(partition or None)


def build_command_output(output: int, on: bool) -> bytes:
    return b"\x00" + var_bytes(output) + bytes([0x01 if on else 0x02])


def build_user_activity(activity: int) -> bytes:
    return b"\x00" + bytes([activity])
