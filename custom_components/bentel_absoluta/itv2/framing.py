"""ITv2 data-link framing for the Bentel Absoluta ABS-IP plug-in.

Wire format (Ethernet and PC-Link profiles are identical, encryption disabled)::

    0x7E | escaped( LEN | SEQ | RSEQ | APP-DATA | CRC_HI | CRC_LO ) | 0x7F

* ``LEN`` ("bytes to follow") counts SEQ, RSEQ, APP-DATA and the two CRC
  bytes. It is one byte (4..127) or, when bit 7 of the first byte is set,
  two bytes big-endian with the top bit masked off.
* ``CRC`` is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no final XOR)
  computed over LEN + SEQ + RSEQ + APP-DATA.
* Byte stuffing: 0x7D -> 7D 00, 0x7E -> 7D 01, 0x7F -> 7D 02.
* A "simple ACK" is a packet with an empty APP-DATA (LEN == 4).

This module is intentionally free of Home Assistant imports so it can be
unit tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

SOF = 0x7E
EOF = 0x7F
ESC = 0x7D

_ESCAPE = {ESC: 0x00, SOF: 0x01, EOF: 0x02}
_UNESCAPE = {v: k for k, v in _ESCAPE.items()}


class FrameError(ValueError):
    """Raised for malformed frames (bad escape, length or CRC)."""


def _build_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def crc16_ccitt(data: bytes | bytearray) -> int:
    """CRC-16/CCITT-FALSE."""
    crc = 0xFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def escape(data: bytes | bytearray) -> bytes:
    out = bytearray()
    for b in data:
        if b in _ESCAPE:
            out.append(ESC)
            out.append(_ESCAPE[b])
        else:
            out.append(b)
    return bytes(out)


def unescape(data: bytes | bytearray) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == ESC:
            if i + 1 >= n:
                raise FrameError("truncated escape sequence")
            nxt = data[i + 1]
            if nxt not in _UNESCAPE:
                raise FrameError(f"invalid escape sequence 7D {nxt:02X}")
            out.append(_UNESCAPE[nxt])
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


@dataclass(slots=True)
class Packet:
    """A transport-layer packet."""

    seq: int
    rseq: int
    app: bytes = b""

    @property
    def is_ack(self) -> bool:
        return not self.app

    @property
    def command(self) -> int | None:
        if len(self.app) < 2:
            return None
        return (self.app[0] << 8) | self.app[1]

    @property
    def payload(self) -> bytes:
        """Application data after the 2-byte command code."""
        return self.app[2:]


def encode_packet(packet: Packet) -> bytes:
    """Build a complete on-wire frame for ``packet``."""
    body = bytes([packet.seq & 0xFF, packet.rseq & 0xFF]) + bytes(packet.app)
    length = len(body) + 2
    if length <= 0x7F:
        hdr = bytes([length])
    elif length <= 0x7FFF:
        hdr = bytes([0x80 | (length >> 8), length & 0xFF])
    else:
        raise FrameError("packet too long")
    data = hdr + body
    crc = crc16_ccitt(data)
    data += bytes([crc >> 8, crc & 0xFF])
    return bytes([SOF]) + escape(data) + bytes([EOF])


def decode_frame_body(raw: bytes) -> Packet:
    """Decode the unescaped bytes found between SOF and EOF."""
    if len(raw) < 5:
        raise FrameError("frame too short")
    if raw[0] & 0x80:
        length = ((raw[0] & 0x7F) << 8) | raw[1]
        hdr_len = 2
    else:
        length = raw[0]
        hdr_len = 1
    if length < 4 or hdr_len + length > len(raw):
        raise FrameError(f"invalid length {length} for {len(raw)} bytes")
    end = hdr_len + length
    crc_rx = (raw[end - 2] << 8) | raw[end - 1]
    crc_calc = crc16_ccitt(raw[: end - 2])
    if crc_rx != crc_calc:
        raise FrameError(f"CRC mismatch (rx {crc_rx:04X}, calc {crc_calc:04X})")
    body = raw[hdr_len : end - 2]
    return Packet(seq=body[0], rseq=body[1], app=bytes(body[2:]))


class FrameReader:
    """Incremental stream parser: feed bytes, get packets out."""

    MAX_FRAME = 4096

    def __init__(self) -> None:
        self._buf = bytearray()
        self._in_frame = False

    def feed(self, data: bytes) -> list[Packet | FrameError]:
        """Return decoded packets (or FrameError instances for bad frames)."""
        out: list[Packet | FrameError] = []
        for b in data:
            if b == SOF:
                # A new start always resynchronises the parser.
                self._buf.clear()
                self._in_frame = True
            elif b == EOF:
                if self._in_frame:
                    try:
                        out.append(decode_frame_body(unescape(self._buf)))
                    except FrameError as err:
                        out.append(err)
                self._buf.clear()
                self._in_frame = False
            elif self._in_frame:
                self._buf.append(b)
                if len(self._buf) > self.MAX_FRAME:
                    out.append(FrameError("frame too long"))
                    self._buf.clear()
                    self._in_frame = False
            # bytes outside a frame are ignored
        return out
