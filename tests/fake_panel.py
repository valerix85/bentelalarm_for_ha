"""A minimal simulated Absoluta ABS-IP plug-in used by the tests.

It speaks the real ITv2 wire format (framing, CRC, sequence numbers, simple
ACKs, app sequence numbers and 0502 responses) and follows the power-up
session diagram of the Absoluta usage guide.
"""

from __future__ import annotations

import asyncio

from itv2 import messages as m
from itv2.const import Cmd
from itv2.framing import FrameReader, Packet, encode_packet


def cmd_bytes(cmd: int) -> bytes:
    return int(cmd).to_bytes(2, "big")


class FakePanel:
    def __init__(
        self,
        pin: str = "1234",
        *,
        zones=(1, 2, 3, 5),
        partitions=(1, 2),
        multi_zone_ok: bool = True,
        send_zone_assignment: bool = True,
        phantom_zones=(),
        max_zones_per_reply: int | None = None,
        zone_label_limit: int | None = None,
        close_on_logout: bool = True,
    ) -> None:
        self.pin = pin
        self.zones = list(zones)
        self.partitions = list(partitions)
        self.multi_zone_ok = multi_zone_ok
        self.send_zone_assignment = send_zone_assignment
        # In the assignment mask but refused by status requests (seen on an Absoluta 16)
        self.phantom_zones = list(phantom_zones)
        self.max_zones_per_reply = max_zones_per_reply
        # Zone labels above this number are refused (real Absoluta 16 behaviour)
        self.zone_label_limit = zone_label_limit
        self.pending_bypass: dict[int, bool] = {}
        self.event_log: list[bytes] = []  # 13-byte records, most recent first
        self.panel_time: bytes | None = None
        # Real ABS-IP (fw 3.60.37) closes the TCP session after Exit Access Level
        self.close_on_logout = close_on_logout
        self.connections = 0
        self.zone_raw = {z: 0 for z in self.zones}
        self.part_raw = {p: bytearray(b"\x02\x00\x00") for p in self.partitions}
        self.outputs_on: set[int] = set()
        self.log: list[tuple[int, bytes]] = []  # commands received (cmd, payload)
        self.errors: list[str] = []
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.writer: asyncio.StreamWriter | None = None
        self.logged_in = False

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.writer:
            self.writer.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    # -- transport ---------------------------------------------------------

    async def _handle(self, reader, writer) -> None:
        self.writer = writer
        self.connections += 1
        self.seq = 0
        self.first = True
        self.rseq = 0
        self.expect_client_seq = 0
        self.app_seq = 0
        self.awaiting_reply: set[int] = set()  # our app seqs not yet answered by 0502
        frames = FrameReader()
        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                for pkt in frames.feed(data):
                    if not isinstance(pkt, Packet):
                        self.errors.append(f"bad frame {pkt}")
                        continue
                    await self._on_packet(pkt)
        except Exception as err:  # noqa: BLE001
            import traceback

            self.errors.append(traceback.format_exc())
            print(traceback.format_exc())
            raise err
        finally:
            writer.close()

    def _send(self, app: bytes) -> None:
        if not self.first:
            self.seq = self.seq + 1 if self.seq < 255 else 1
        self.first = False
        self.writer.write(encode_packet(Packet(self.seq, self.rseq, app)))

    async def _on_packet(self, pkt: Packet) -> None:
        if pkt.is_ack:
            return
        if pkt.seq != self.expect_client_seq:
            self.errors.append(f"client seq {pkt.seq}, expected {self.expect_client_seq}")
        self.expect_client_seq = pkt.seq + 1 if pkt.seq < 255 else 1
        self.rseq = pkt.seq
        # simple ACK
        self.writer.write(encode_packet(Packet(self.seq, self.rseq)))
        cmd = pkt.command
        p = pkt.payload
        self.log.append((cmd, p))
        await self._on_command(cmd, p)

    def _respond(self, app_seq: int, code: int = 0) -> None:
        self._send(cmd_bytes(Cmd.COMMAND_RESPONSE) + bytes([app_seq, code]))

    def _next_app(self) -> int:
        self.app_seq += 1
        return self.app_seq

    # -- application -------------------------------------------------------

    async def _on_command(self, cmd: int, p: bytes) -> None:
        # Like the real ABS-IP, refuse to go on with the handshake until the
        # client has answered our own 060A / 060E with a 0502.
        if self.awaiting_reply and cmd in (
            Cmd.REQUEST_ACCESS,
            Cmd.SOFTWARE_VERSION,
            Cmd.ENTER_ACCESS_LEVEL,
        ):
            self.errors.append(f"{cmd:04X} received before 0502 to panel command")
            self._send(cmd_bytes(Cmd.COMMAND_ERROR) + cmd_bytes(cmd) + b"\x07")
            return
        if cmd == Cmd.OPEN_SESSION:
            self._respond(p[0])
            self._send(
                cmd_bytes(Cmd.OPEN_SESSION)
                + bytes([self._next_app()])
                + bytes.fromhex("01 0000 0100 0203 00C8 0032 0001 00")
            )
        elif cmd == Cmd.REQUEST_ACCESS:
            self._respond(p[0])
            self._send(
                cmd_bytes(Cmd.REQUEST_ACCESS)
                + bytes([self._next_app()])
                + bytes.fromhex("06 00034F060003")
            )
        elif cmd == Cmd.COMMAND_RESPONSE:
            self.awaiting_reply.discard(p[0])
        elif cmd == Cmd.SOFTWARE_VERSION:
            self._send(
                cmd_bytes(Cmd.SOFTWARE_VERSION) + bytes.fromhex("35 00 00 1E 02 03 00 B3 01 03 01")
            )
        elif cmd == Cmd.ENTER_ACCESS_LEVEL:
            seq, code = p[0], p[4:7]
            if code != m.encode_pin(self.pin):
                self._respond(seq, 0x11)
                return
            self.logged_in = True
            self.log_event(0x0015, where=0x07, who=0x00)  # "Riconosciuto Cod"
            self._respond(seq)
            self._send(
                cmd_bytes(Cmd.ACCESS_LEVEL_LEAD_IN_OUT)
                + bytes.fromhex("00 00 01 01 00 02 9C 7A 9A 69")
            )
            self._send(
                cmd_bytes(Cmd.SYSTEM_CAPABILITIES)
                + bytes.fromhex("01 2A 01 3F 01 08 01 10 01 80 01 14")
            )
            self._send(
                cmd_bytes(Cmd.PARTITION_ASSIGNMENT)
                + b"\x02"
                + m.list_to_bitmask(self.partitions, 2)
            )
            if self.send_zone_assignment:
                self._send(
                    cmd_bytes(Cmd.ZONE_ASSIGNMENT)
                    + b"\x00"
                    + m.list_to_bitmask(self.zones + self.phantom_zones, 16)
                )
            self._send(self._partition_status())
        elif cmd == Cmd.COMMAND_REQUEST:
            await self._on_request(p[0], (p[1] << 8) | p[2], p[3:])
        elif cmd == Cmd.SECTION_READ:
            section = (p[2] << 8) | p[3]
            if section == 1:
                data = bytearray(11)
                data[0] = 0b00001001  # outputs 1 and 4
                data[7] = 0b00000010  # remote command 2
                self._send(cmd_bytes(Cmd.SECTION_READ_RESPONSE) + bytes([0, 0, 1]) + bytes(data))
            else:
                self._respond(p[0], 0x17)
        elif cmd == Cmd.PARTITION_ARM:
            seq, (part, off) = p[0], m.read_var(p, 1)
            mode = p[off]
            targets = self.partitions if not part else [part]
            if not mode & 0x80 and any(self.zone_raw[z] & 1 for z in self.zones):
                self._respond(seq, 0x01)
                self._send(cmd_bytes(Cmd.MISC_ALARM) + bytes.fromhex("00 FF 01"))
                return
            self._respond(seq)
            for t in targets:
                self.part_raw[t][0] = 0x01 | (0x04 if mode == 2 else 0x02)
            self._send(cmd_bytes(Cmd.ARMING_DISARMING) + bytes([0, mode, 1, 0]))
            self._send(self._partition_status())
        elif cmd == Cmd.PARTITION_DISARM:
            seq, (part, _) = p[0], m.read_var(p, 1)
            self._respond(seq)
            for t in self.partitions if not part else [part]:
                self.part_raw[t][0] = 0x02
                self.part_raw[t][1] = 0
            self._send(cmd_bytes(Cmd.ARMING_DISARMING) + bytes([0, 0, 1, 0]))
            self._send(self._partition_status())
        elif cmd == Cmd.COMMAND_OUTPUT:
            seq = p[0]
            out, off = m.read_var(p, 2)
            (self.outputs_on.add if p[off] == 1 else self.outputs_on.discard)(out)
            self._respond(seq)
            self._send(self._outputs())
        elif cmd == Cmd.SINGLE_ZONE_BYPASS_WRITE:
            seq, zone_off = p[0], 2  # app seq, partition (00)
            zone, off = m.read_var(p, zone_off)
            self.pending_bypass[zone] = bool(p[off])
            self._respond(seq)
        elif cmd == Cmd.EXIT_ACCESS_LEVEL:
            # Absoluta finalises programming writes at log-out
            for zone, on in self.pending_bypass.items():
                self.log_event(0x4000 if on else 0x4001, who=zone - 1)  # WHO is 0-based
                self.zone_raw[zone] = (
                    (self.zone_raw[zone] | 0x80) if on else (self.zone_raw[zone] & 0x7F)
                )
            self.pending_bypass.clear()
            self.logged_in = False
            self._respond(p[0])
            if self.close_on_logout:
                await self.writer.drain()
                self.writer.close()
        elif cmd == Cmd.USER_ACTIVITY:
            self._respond(p[0])
        elif cmd == Cmd.EVENT_BUFFER_READ:
            first = (p[2] << 8) | p[3]
            count = (p[4] << 8) | p[5]
            records = self.event_log[first : first + count]
            self._send(
                cmd_bytes(Cmd.EVENT_BUFFER_READ_RESPONSE)
                + bytes([0x03])
                + first.to_bytes(2, "big")
                + len(records).to_bytes(2, "big")
                + b"".join(records)
            )
        elif cmd == Cmd.TIME_DATE_WRITE:
            self.panel_time = p[1:5]
            self._respond(p[0])
        elif cmd == Cmd.END_SESSION:
            self.writer.close()
        else:
            self.errors.append(f"unexpected command {cmd:04X}")

    def _partition_status(self) -> bytes:
        body = b"\x02" + m.list_to_bitmask(self.partitions, 2) + b"\x03"
        for part in self.partitions:
            body += bytes(self.part_raw[part])
        return cmd_bytes(Cmd.PARTITION_STATUS) + body

    def _outputs(self) -> bytes:
        mask = m.list_to_bitmask(sorted(self.outputs_on) or [1], 7)
        if not self.outputs_on:
            mask = bytes(7)
        return cmd_bytes(Cmd.COMMAND_OUTPUT_ACTIVATION) + b"\x00\x07" + mask

    async def _on_request(self, seq: int, req: int, d: bytes) -> None:
        if req == Cmd.PARTITION_STATUS:
            self._send(self._partition_status())
        elif req == Cmd.ZONE_STATUS:
            first, off = m.read_var(d, 0)
            count, _ = m.read_var(d, off)
            if count > 1 and not self.multi_zone_ok:
                return  # some panels never answer multi-zone reads
            if any(z in self.phantom_zones for z in range(first, first + count)):
                self._respond(seq, 0x02)  # invalid data for the requested command
                return
            if self.max_zones_per_reply:
                count = min(count, self.max_zones_per_reply)
            body = m.var_bytes(first) + m.var_bytes(count) + b"\x01"
            body += bytes(self.zone_raw.get(z, 0) for z in range(first, first + count))
            self._send(cmd_bytes(Cmd.ZONE_STATUS) + body)
        elif req == Cmd.COMMAND_OUTPUT_ACTIVATION:
            self._send(self._outputs())
        elif req == Cmd.ZONE_ASSIGNMENT and d[:1] == b"\x01" and d[1] != 0:
            part = d[1]
            mine = [z for z in self.zones if self.zone_partition(z) == part]
            self._send(
                cmd_bytes(Cmd.ZONE_ASSIGNMENT) + bytes([1, part]) + m.list_to_bitmask(mine, 16)
            )
        elif req == Cmd.ZONE_ASSIGNMENT:
            self._send(
                cmd_bytes(Cmd.ZONE_ASSIGNMENT)
                + b"\x00"
                + m.list_to_bitmask(self.zones + self.phantom_zones, 16)
            )
        elif req == Cmd.CONFIGURATION_BROADCAST:
            opt, off = m.read_var(d, 0)
            first, off = m.read_var(d, off)
            last, _ = m.read_var(d, off)
            if opt == 1 and self.zone_label_limit and last > self.zone_label_limit:
                self._respond(seq, 0x02)
                return
            labels = b""
            for n in range(first, last + 1):
                name = {1: "Zona", 3: "Area", 4: "Uscita", 13: "Modo"}.get(opt, "X")
                labels += f"{name} {n:02d}".ljust(16).encode("cp1252")
            self._send(
                cmd_bytes(Cmd.CONFIGURATION_BROADCAST)
                + m.var_bytes(opt)
                + m.var_bytes(first)
                + m.var_bytes(last)
                + m.var_bytes(len(labels))  # real panel: TOTAL length of the range
                + labels
            )
        else:
            self._respond(seq, 0x01)

    # -- helpers for tests -------------------------------------------------

    def zone_partition(self, zone: int) -> int:
        return self.partitions[(zone - 1) % len(self.partitions)]

    def log_event(self, event_id: int, where: int = 0, who: int = 0xFF, parts=(1,)) -> None:
        mask = m.list_to_bitmask(list(parts), 2)
        rec = (
            bytes.fromhex("98829A69")
            + b"\x09"
            + event_id.to_bytes(2, "big")
            + bytes([where, who])
            + bytes([0, 0, mask[1], mask[0]])
        )
        self.event_log.insert(0, rec)

    def push_partition_status(self) -> None:
        self._send(self._partition_status())
