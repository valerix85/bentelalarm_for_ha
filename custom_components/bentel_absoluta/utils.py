import asyncio
import struct
from .const import (
    FRAME_START,
    FRAME_END,
    ESCAPE,
    CRC_POLY,
    CRC_INIT,
    CRC_XOROUT,
    CMD_OPEN_SESSION,
    DEFAULT_TIMEOUT,
)


class BentelProtocol:
    def __init__(self, host, port, timeout=DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reader = None
        self.writer = None
        self.seq = 0
        self.remote_seq = 0

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        await self._open_session()

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    async def _open_session(self):
        """
        Invia il comando Open Session (0x060A) con payload completo secondo specifica ITv2.
        """
        # Payload Open Session:
        # Device Type (0x8F), Device ID (0x0000), SW Version 1.00, Proto Version 2.00,
        # TX buf 48, RX buf 200, Encryption none
        payload = bytes(
            [
                0x8F,  # Device Type
                0x00,
                0x00,  # Device ID
                0x01,
                0x00,  # Software Version 1.00
                0x02,
                0x00,  # Protocol Version 2.00
                0x00,
                0x32,  # TX buffer size = 50
                0x00,
                0xC8,  # RX buffer size = 200
                0x00,  # Encryption none
            ]
        )
        frame = self._build_frame(CMD_OPEN_SESSION, payload)
        await self._send_frame(frame)
        # Attende la risposta di Open Session
        await self._recv_response()

    def _build_frame(self, cmd, payload: bytes) -> bytes:
        # Header: CMD + Seq + Remote Seq
        hdr = struct.pack(">B B B", cmd, self.seq, self.remote_seq)
        body = hdr + payload
        crc = self._crc16_ccitt(body)
        body += struct.pack(">H", crc)
        framed = bytearray([FRAME_START])
        for b in body:
            if b in (FRAME_START, FRAME_END, ESCAPE):
                framed.append(ESCAPE)
                framed.append(b ^ 0x20)
            else:
                framed.append(b)
        framed.append(FRAME_END)
        self.seq = (self.seq + 1) & 0xFF
        return bytes(framed)

    async def _send_frame(self, frame: bytes):
        self.writer.write(frame)
        await self.writer.drain()

    async def _recv_response(self) -> bytes:
        buf = bytearray()
        # Legge fino a FRAME_END
        while True:
            b = await asyncio.wait_for(self.reader.readexactly(1), timeout=self.timeout)
            if b[0] == FRAME_END:
                break
            buf.append(b[0])
        data = self._unescape(bytes(buf))
        # Verifica CRC e restituisce content
        content, ok = self._check_crc(data)
        if not ok:
            raise IOError("CRC error nel pacchetto ricevuto")
        # content include cmd, seq, remote_seq, app_seq, status, data...
        return content

    def _unescape(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        while i < len(data):
            if data[i] == ESCAPE:
                i += 1
                out.append(data[i] ^ 0x20)
            else:
                out.append(data[i])
            i += 1
        return bytes(out)

    def _crc16_ccitt(self, data: bytes) -> int:
        crc = CRC_INIT
        for b in data:
            crc ^= b << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ CRC_POLY
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc ^ CRC_XOROUT

    def _check_crc(self, data: bytes) -> (bytes, bool):
        content = data[:-2]
        recv_crc = struct.unpack(">H", data[-2:])[0]
        calc_crc = self._crc16_ccitt(content)
        return content, recv_crc == calc_crc


async def send_command(self, cmd, payload: bytes) -> bytes:
    for attempt in range(4):
        frame = self._build_frame(cmd, payload)
        await self._send_frame(frame)
        try:
            resp = await self._recv_response()
            # resp layout: [cmd_rsp(1), seq(1), remote_seq(1), app_seq(1), status(1), data...]
            # Update remote_seq to panel's sequence number for ACK
            panel_seq = resp[1]
            self.remote_seq = panel_seq
            # Return application data skipping header and status
            return resp[5:]
        except (asyncio.TimeoutError, IOError):
            continue
    raise ConnectionError(f"Nessuna risposta valida per comando {cmd:#04x}")(
        f"Nessuna risposta valida per comando {cmd:#04x}"
    )
