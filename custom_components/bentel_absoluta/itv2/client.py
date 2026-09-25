"""Asyncio ITv2 client for the Bentel Absoluta ABS-IP plug-in.

Session life cycle (see "ITv2 Usage Guide for Absoluta", Appendix A)::

    3rd party                               ABS-IP
    Open Session 060A          ------->
                               <-------     Command Response 0502 (success)
                               <-------     Open Session 060A
    Command Response 0502      ------->
    Request Access 060E        ------->
                               <-------     Command Response 0502
                               <-------     Request Access 060E (MAC address)
    Command Response 0502      ------->
    Software Version 060D      ------->
                               <-------     Software Version 060D
    Enter Access Level 0400    ------->     (user PIN)
                               <-------     Command Response 0502
                               <-------     Lead In 0402, System Capabilities 0613,
                                            Partition Assignment 0772,
                                            Zone Assignment 0770, Partition Status 0812
    ... polling / keep alive / commands ...

Every non-empty packet is acknowledged at transport level either by a
"simple ACK" (empty packet) or by any packet carrying the right remote
sequence number. We always send a simple ACK straight away, and we keep a
single outgoing packet in flight until the panel acknowledges it.

Zone open/close is *not* notified spontaneously by the ABS-IP plug-in, so
zone status is polled (default every 5 seconds, which also works as the
recommended keep alive).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import messages as msg
from .const import (
    ARMING_TYPES,
    CMDS_WITH_APP_SEQ,
    COMMAND_ERRORS,
    DEFAULT_PORT,
    MAX_OUTPUTS,
    MAX_PARTITIONS,
    MAX_REMOTE_COMMANDS,
    MAX_ZONES,
    MISC_ALARM_TYPES,
    OPT_ARMING_MODE_LABEL,
    OPT_OUTPUT_LABEL,
    OPT_PARTITION_LABEL,
    OPT_ZONE_LABEL,
    REMOTE_COMMAND_OUTPUT_OFFSET,
    RESP_INVALID_ACCESS_CODE,
    RESPONSE_CODES,
    SECTION_ENABLED_OUTPUTS,
    ArmMode,
    Cmd,
    UserActivity,
)
from .framing import FrameError, FrameReader, Packet, encode_packet

_LOGGER = logging.getLogger(__name__)

TRANSPORT_RETRIES = 4
TRANSPORT_TIMEOUT = 1.5
APP_TIMEOUT = 6.0
KEEP_ALIVE_INTERVAL = 5.0
LABEL_CHUNK = 8
MAX_ZONE_RUN = 64


class ITv2Error(Exception):
    """Base error."""


class ConnectionFailed(ITv2Error):
    """TCP connection or session establishment failed."""


class TcpConnectFailed(ConnectionFailed):
    """The TCP connection itself could not be opened."""


class HandshakeFailed(ConnectionFailed):
    """TCP is up but the ITv2 handshake/login did not complete."""

    def __init__(self, message: str, *, stage: str = "") -> None:
        super().__init__(message)
        self.stage = stage


class AuthenticationFailed(ITv2Error):
    """The panel rejected the user PIN."""


class CommandFailed(ITv2Error):
    """The panel answered a command with an error."""

    def __init__(self, command: int, code: int, *, is_command_error: bool = False) -> None:
        self.command = command
        self.code = code
        self.is_command_error = is_command_error
        table = COMMAND_ERRORS if is_command_error else RESPONSE_CODES
        text = table.get(code, f"error 0x{code:02X}")
        kind = "command error" if is_command_error else "response"
        super().__init__(f"command 0x{command:04X} failed: {kind} 0x{code:02X} ({text})")


def _next(n: int) -> int:
    """Sequence numbers roll over from 255 to 1 (0 is reserved for resync)."""
    return n + 1 if n < 255 else 1


def _runs(items: list[int], max_len: int) -> list[tuple[int, int]]:
    """Split a sorted list of ints into contiguous (first, count) runs."""
    runs: list[tuple[int, int]] = []
    for item in sorted(set(items)):
        if runs and runs[-1][0] + runs[-1][1] == item and runs[-1][1] < max_len:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((item, 1))
    return runs


@dataclass(slots=True)
class _Pending:
    cmd: int
    app_seq: int
    matcher: Callable[[int, bytes], Any] | None
    future: asyncio.Future


class AbsolutaClient:
    """Client for one Absoluta panel."""

    def __init__(
        self,
        host: str,
        pin: str,
        port: int = DEFAULT_PORT,
        *,
        poll_interval: float = 5.0,
        connect_timeout: float = 10.0,
        load_labels: bool = True,
    ) -> None:
        msg.encode_pin(pin)  # validate early
        self.host = host
        self.port = port
        self._pin = pin
        self.poll_interval = max(0.1, poll_interval)
        self._connect_timeout = connect_timeout
        self._load_labels = load_labels

        # Public state
        self.info = msg.PanelInfo()
        self.partitions: dict[int, msg.PartitionStatus] = {}
        self.zones: dict[int, msg.ZoneStatus] = {}
        self.user_partitions: list[int] = []
        self.user_zones: list[int] = []
        self.outputs: list[int] = []  # programmable outputs usable by the user
        self.remote_commands: list[int] = []  # remote commands 1..32
        self.outputs_on: set[int] = set()
        self.exit_delay: set[int] = set()
        # Partitions with an accepted arm command not yet confirmed by 0812
        self.arming_requested: set[int] = set()
        self.entry_delay: set[int] = set()
        self.zone_labels: dict[int, str] = {}
        self.partition_labels: dict[int, str] = {}
        self.output_labels: dict[int, str] = {}
        self.remote_command_labels: dict[int, str] = {}
        self.arming_mode_labels: dict[str, str] = {}
        self.system_label: str | None = None
        self.panel_time = None
        self.gsm_signal: int | None = None
        self.connected = False
        self.stage = "idle"
        self.rx_packets = 0
        self.invalid_zones: set[int] = set()
        self.invalid_zone_reasons: dict[int, str] = {}

        # Listeners
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[str, dict], None]] = []
        self.on_auth_failed: Callable[[], None] | None = None

        # Connection internals
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._supervisor: asyncio.Task | None = None
        self._frames = FrameReader()
        self._seq = 0
        self._sent_first = False
        self._rseq = 0
        self._rx_started = False
        self._last_ack = -1
        self._ack_event = asyncio.Event()
        self._tx_lock = asyncio.Lock()
        self._app_lock = asyncio.Lock()
        self._app_seq = 0
        self._pending: _Pending | None = None
        self._expected: dict[int, list[asyncio.Future]] = {}
        self._closed_event = asyncio.Event()
        self._last_tx = 0.0
        self._single_zone_mode = False
        self._refresh_requested = asyncio.Event()
        self._stopping = False
        self._background: set[asyncio.Task] = set()
        self._reply_tasks: dict[int, asyncio.Task] = {}
        self._reconnect_now = False
        self._labels_loaded = False

    # ------------------------------------------------------------------
    # Listener API
    # ------------------------------------------------------------------

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def add_event_listener(self, callback: Callable[[str, dict], None]) -> Callable[[], None]:
        self._event_listeners.append(callback)
        return lambda: (
            self._event_listeners.remove(callback) if callback in self._event_listeners else None
        )

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in state listener")

    def _event(self, event_type: str, data: dict) -> None:
        _LOGGER.debug("Event %s: %s", event_type, data)
        for cb in list(self._event_listeners):
            try:
                cb(event_type, data)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in event listener")

    # ------------------------------------------------------------------
    # Life cycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect, log in, discover the panel and start background polling.

        Raises ConnectionFailed / AuthenticationFailed if the first
        connection fails; afterwards reconnection is automatic.
        """
        self._stopping = False
        await self.connect()
        self._supervisor = asyncio.create_task(self._supervise(), name="absoluta-supervisor")

    async def stop(self) -> None:
        self._stopping = True
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._supervisor
            self._supervisor = None
        await self.disconnect()

    async def connect(self, *, discover: bool = True) -> None:
        """Open the TCP connection and run handshake, login and discovery.

        With ``discover=False`` only handshake and login are performed
        (used by the config flow to validate host and PIN).
        """
        self._reset_session()
        self.stage = "tcp_connect"
        self.rx_packets = 0
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self._connect_timeout
            )
        except (TimeoutError, OSError) as err:
            raise TcpConnectFailed(
                f"TCP connection to {self.host}:{self.port} failed: {err or 'timeout'}"
            ) from err
        _LOGGER.debug("TCP connected to %s:%s", self.host, self.port)
        self._closed_event.clear()
        self._read_task = asyncio.create_task(self._read_loop(), name="absoluta-reader")
        try:
            await self._handshake()
            self.stage = "login"
            await self._login()
        except AuthenticationFailed:
            await self._close_transport()
            raise
        except (TimeoutError, ITv2Error, OSError) as err:
            await self._close_transport()
            detail = str(err) or type(err).__name__
            raise HandshakeFailed(
                f"ITv2 session failed at stage '{self.stage}' "
                f"({self.rx_packets} packets received from panel): {detail}",
                stage=self.stage,
            ) from err
        if discover:
            # Discovery / first poll failures must not prevent the session.
            self.stage = "discover"
            try:
                await self._discover()
                self.stage = "first_poll"
                await self.refresh()
                await self._probe_missing_zones()
                if self.invalid_zones:
                    self.user_zones = [z for z in self.user_zones if z not in self.invalid_zones]
            except (TimeoutError, ITv2Error) as err:
                _LOGGER.warning(
                    "Absoluta %s: %s failed (%s), continuing",
                    self.host,
                    self.stage,
                    str(err) or type(err).__name__,
                )
                if self._closed_event.is_set():
                    await self._close_transport()
                    raise ConnectionFailed("connection closed during discovery") from err
        self.stage = "connected"
        self._set_connected(True)

    async def disconnect(self) -> None:
        """Log out and end the session politely, then close the socket."""
        if self._writer is not None and not self._closed_event.is_set():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._request(Cmd.EXIT_ACCESS_LEVEL, b"\x00"), 3)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._send_app(Cmd.END_SESSION.to_bytes(2, "big")), 3)
        await self._close_transport()
        self._set_connected(False)

    def _reset_session(self) -> None:
        self._frames = FrameReader()
        self._seq = 0
        self._sent_first = False
        self._rseq = 0
        self._rx_started = False
        self._last_ack = -1
        self._app_seq = 0
        self._pending = None
        self._expected.clear()
        self._reply_tasks.clear()
        self._single_zone_mode = False
        self.exit_delay.clear()
        self.entry_delay.clear()

    async def _close_transport(self) -> None:
        if self._read_task and self._read_task is not asyncio.current_task():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._read_task
        self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._writer = None
        self._reader = None
        self._closed_event.set()
        self._fail_waiters(ConnectionFailed("connection closed"))

    def _fail_waiters(self, err: Exception) -> None:
        if self._pending and not self._pending.future.done():
            self._pending.future.set_exception(err)
        for futures in self._expected.values():
            for fut in futures:
                fut.cancel()
        self._expected.clear()
        self._ack_event.set()

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            self._notify()

    async def _supervise(self) -> None:
        """Poll while connected, reconnect with back-off when the link drops."""
        backoff = 10.0
        while not self._stopping:
            planned = False
            if self.connected:
                try:
                    await self._poll_loop()
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    planned = self._reconnect_now
                    if planned:
                        _LOGGER.debug("Planned reconnection to %s (%s)", self.host, err)
                    else:
                        _LOGGER.warning("Connection to Absoluta %s lost: %s", self.host, err)
                await self._close_transport()
                if not planned:
                    self._set_connected(False)
                backoff = 10.0
            if self._stopping:
                break
            delay = 0.5 if planned else backoff
            self._reconnect_now = False
            _LOGGER.debug("Reconnecting to %s in %.1f s", self.host, delay)
            await asyncio.sleep(delay)
            try:
                await self.connect()
                _LOGGER.info("Reconnected to Absoluta %s", self.host)
            except AuthenticationFailed:
                self._set_connected(False)
                _LOGGER.error("Absoluta %s rejected the user PIN, giving up", self.host)
                if self.on_auth_failed:
                    self.on_auth_failed()
                return
            except ITv2Error as err:
                self._set_connected(False)
                _LOGGER.debug("Reconnect failed: %s", err)
                backoff = min(backoff * 2, 300.0)

    async def _poll_loop(self) -> None:
        last_poll = time.monotonic()
        while not self._closed_event.is_set():
            wait = max(0.0, min(self.poll_interval - (time.monotonic() - last_poll), 1.0))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._refresh_requested.wait(), wait)
            if self._closed_event.is_set():
                break
            now = time.monotonic()
            if self._refresh_requested.is_set() or now - last_poll >= self.poll_interval:
                self._refresh_requested.clear()
                last_poll = now
                await self.refresh()
            elif now - self._last_tx >= KEEP_ALIVE_INTERVAL:
                await self._request(
                    Cmd.USER_ACTIVITY, msg.build_user_activity(UserActivity.KEEP_ALIVE)
                )
        raise ConnectionFailed("connection closed")

    def request_refresh(self) -> None:
        """Ask the background loop for an immediate status poll."""
        self._refresh_requested.set()

    # ------------------------------------------------------------------
    # Transport layer
    # ------------------------------------------------------------------

    def _write(self, packet: Packet) -> None:
        if self._writer is None or self._closed_event.is_set():
            raise ConnectionFailed("not connected")
        data = encode_packet(packet)
        _LOGGER.debug("TX seq=%d rseq=%d %s", packet.seq, packet.rseq, packet.app.hex(" "))
        self._writer.write(data)

    def _send_simple_ack(self) -> None:
        with contextlib.suppress(ConnectionFailed):
            self._write(Packet(self._seq, self._rseq))

    async def _send_app(self, app: bytes) -> None:
        """Send one application packet and wait for its transport ACK."""
        async with self._tx_lock:
            if self._sent_first:
                self._seq = _next(self._seq)
            self._sent_first = True
            seq = self._seq
            for attempt in range(TRANSPORT_RETRIES):
                self._ack_event.clear()
                self._write(Packet(seq, self._rseq, app))
                self._last_tx = time.monotonic()
                assert self._writer is not None
                await self._writer.drain()
                deadline = time.monotonic() + TRANSPORT_TIMEOUT
                while self._last_ack != seq:
                    if self._closed_event.is_set():
                        raise ConnectionFailed("connection closed")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._ack_event.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._ack_event.wait(), remaining)
                if self._last_ack == seq:
                    return
                _LOGGER.debug("No ACK for seq %d (attempt %d)", seq, attempt + 1)
            raise ConnectionFailed(f"no transport ACK for packet seq {seq}")

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                data = await self._reader.read(1024)
                if not data:
                    raise ConnectionFailed("connection closed by panel")
                for item in self._frames.feed(data):
                    if isinstance(item, FrameError):
                        _LOGGER.debug("Discarding bad frame: %s", item)
                        continue
                    self._on_packet(item)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Reader stopped: %s", err)
            self._closed_event.set()
            self._fail_waiters(ConnectionFailed(str(err)))
            self._refresh_requested.set()

    def _on_packet(self, pkt: Packet) -> None:
        _LOGGER.debug("RX seq=%d rseq=%d %s", pkt.seq, pkt.rseq, pkt.app.hex(" "))
        self.rx_packets += 1
        self._last_ack = pkt.rseq
        self._ack_event.set()
        if pkt.is_ack:
            return
        if self._rx_started and pkt.seq == self._rseq:
            _LOGGER.debug("Duplicate packet seq %d ignored", pkt.seq)
            self._send_simple_ack()
            return
        if self._rx_started and pkt.seq == 0:
            _LOGGER.warning("Panel requested a sequence reset, reconnecting")
            self._send_simple_ack()
            self._closed_event.set()
            self._fail_waiters(ConnectionFailed("sequence reset by panel"))
            return
        self._rseq = pkt.seq
        self._rx_started = True
        self._send_simple_ack()
        cmd = pkt.command
        if cmd is None:
            return
        payload = pkt.payload
        app_seq = None
        if cmd in CMDS_WITH_APP_SEQ and payload:
            app_seq, payload = payload[0], payload[1:]
        try:
            self._dispatch(cmd, app_seq, payload)
        except (ValueError, IndexError) as err:
            _LOGGER.debug("Cannot parse command 0x%04X (%s): %s", cmd, payload.hex(" "), err)

    # ------------------------------------------------------------------
    # Application layer
    # ------------------------------------------------------------------

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _await_reply_sent(self, cmd: int) -> None:
        task = self._reply_tasks.pop(cmd, None)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), APP_TIMEOUT)

    async def _safe_send(self, app: bytes) -> None:
        try:
            await self._send_app(app)
        except ITv2Error as err:
            _LOGGER.debug("Send failed: %s", err)

    def _expect(self, cmd: int) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self._expected.setdefault(cmd, []).append(fut)
        return fut

    async def _request(
        self,
        cmd: int,
        payload: bytes = b"",
        matcher: Callable[[int, bytes], Any] | None = None,
        timeout: float = APP_TIMEOUT,
    ) -> Any:
        """Send a command with app sequence number and wait for its answer.

        Without ``matcher`` the answer is a Command Response (0502) and
        ``None`` is returned on success. With ``matcher`` the first incoming
        command for which ``matcher(cmd, payload)`` is not None resolves the
        request (used for Command Request 0800 and Section Read 0721).
        """
        async with self._app_lock:
            self._app_seq = _next(self._app_seq)
            fut = asyncio.get_running_loop().create_future()
            self._pending = _Pending(int(cmd), self._app_seq, matcher, fut)
            try:
                await self._send_app(int(cmd).to_bytes(2, "big") + bytes([self._app_seq]) + payload)
                return await asyncio.wait_for(fut, timeout)
            finally:
                self._pending = None

    def _check_pending(self, cmd: int, payload: bytes) -> None:
        pending = self._pending
        if pending is None or pending.future.done():
            return
        if cmd == Cmd.COMMAND_RESPONSE and len(payload) >= 2 and payload[0] == pending.app_seq:
            code = payload[1]
            if code:
                pending.future.set_exception(CommandFailed(pending.cmd, code))
            elif pending.matcher is None:
                pending.future.set_result(None)
            return
        if cmd == Cmd.COMMAND_ERROR and len(payload) >= 3:
            if ((payload[0] << 8) | payload[1]) == pending.cmd:
                pending.future.set_exception(
                    CommandFailed(pending.cmd, payload[2], is_command_error=True)
                )
            return
        if pending.matcher is not None:
            result = pending.matcher(cmd, payload)
            if result is not None:
                pending.future.set_result(result)

    def _dispatch(self, cmd: int, app_seq: int | None, p: bytes) -> None:
        # Commands from the panel carrying an app sequence want a 0502 back.
        if app_seq is not None and cmd in (Cmd.OPEN_SESSION, Cmd.REQUEST_ACCESS):
            # The handshake awaits this task so that our 0502 always reaches
            # the panel before we send the next handshake command.
            self._reply_tasks[cmd] = self._spawn(
                self._safe_send(Cmd.COMMAND_RESPONSE.to_bytes(2, "big") + bytes([app_seq, 0x00]))
            )

        for fut in self._expected.pop(cmd, []):
            if not fut.done():
                fut.set_result(p)

        self._check_pending(cmd, p)

        changed = False
        if cmd == Cmd.PARTITION_STATUS:
            status = msg.parse_partition_status(p)
            self.partitions.update(status)
            self.arming_requested.difference_update(status)
            changed = True
        elif cmd == Cmd.ZONE_STATUS:
            self.zones.update(msg.parse_zone_status(p))
            changed = True
        elif cmd == Cmd.COMMAND_OUTPUT_ACTIVATION:
            self.outputs_on = msg.parse_output_activation(p)
            changed = True
        elif cmd == Cmd.EXIT_DELAY:
            part, status = msg.parse_delay(p)
            if part:
                (self.exit_delay.add if status & 0x80 else self.exit_delay.discard)(part)
                changed = True
                self.request_refresh()
        elif cmd == Cmd.ENTRY_DELAY:
            part, status = msg.parse_delay(p)
            if part:
                (self.entry_delay.add if status else self.entry_delay.discard)(part)
                changed = True
                self.request_refresh()
        elif cmd == Cmd.ARMING_DISARMING:
            if len(p) >= 2:
                _, off = msg.read_var(p, 0)
                arm_type = p[off]
                self._event("arming", {"type": ARMING_TYPES.get(arm_type, arm_type)})
            self.request_refresh()
        elif cmd == Cmd.MISC_ALARM:
            _, off = msg.read_var(p, 0)
            alarm = p[off]
            self._event("blocking_condition", {"condition": MISC_ALARM_TYPES.get(alarm, alarm)})
        elif cmd == Cmd.TROUBLE_DETAIL_NOTIFICATION:
            self._handle_troubles(p)
            self.request_refresh()
        elif cmd == Cmd.ARMING_PRE_ALERT:
            part, off = msg.read_var(p, 0)
            self._event("arming_pre_alert", {"partition": part, "active": bool(p[off + 1])})
        elif cmd == Cmd.PARTITION_ASSIGNMENT:
            self.user_partitions = msg.parse_partition_assignment(p)
        elif cmd == Cmd.ZONE_ASSIGNMENT:
            part, zones = msg.parse_zone_assignment(p)
            if not part:
                self.user_zones = zones
        elif cmd == Cmd.SYSTEM_CAPABILITIES:
            caps = msg.parse_system_capabilities(p)
            self.info.max_zones = caps.get("zones")
            self.info.max_partitions = caps.get("partitions")
            self.info.max_outputs = caps.get("outputs")
            self.info.max_users = caps.get("users")
        elif cmd == Cmd.SOFTWARE_VERSION:
            msg.parse_software_version(p, self.info)
        elif cmd == Cmd.REQUEST_ACCESS:
            ident, off = p[0], 1
            self.info.identifier = ":".join(f"{b:02X}" for b in p[off : off + ident])
        elif cmd == Cmd.TIME_DATE:
            self.panel_time = msg.decode_datetime(p)
        elif cmd == Cmd.SIGNAL_STRENGTH:
            if len(p) >= 5:
                self.gsm_signal = p[4]
                changed = True
        elif cmd == Cmd.END_SESSION:
            _LOGGER.warning(
                "Absoluta closed the ITv2 session (BOSS or mobile app session started?)"
            )
            self._closed_event.set()
            self._fail_waiters(ConnectionFailed("session ended by panel"))
            self._refresh_requested.set()
        if changed:
            self._notify()

    def _handle_troubles(self, p: bytes) -> None:
        off = 0
        while off < len(p):
            dev_type, off = msg.read_var(p, off)
            trouble, off = msg.read_var(p, off)
            number, off = msg.read_var(p, off)
            status = p[off]
            off += 1
            self._event(
                "trouble",
                {
                    "device_type": dev_type,
                    "trouble_type": trouble,
                    "device_number": number,
                    "status": {0: "restore", 1: "trouble", 2: "memory"}.get(status, status),
                },
            )

    # ------------------------------------------------------------------
    # Session establishment
    # ------------------------------------------------------------------

    async def _handshake(self) -> None:
        self.stage = "open_session"
        panel_open = self._expect(Cmd.OPEN_SESSION)
        panel_access = self._expect(Cmd.REQUEST_ACCESS)
        await self._request(Cmd.OPEN_SESSION, msg.build_open_session())
        self.stage = "wait_panel_open_session"
        await asyncio.wait_for(panel_open, APP_TIMEOUT)
        await self._await_reply_sent(Cmd.OPEN_SESSION)
        self.stage = "request_access"
        await self._request(Cmd.REQUEST_ACCESS, msg.build_request_access())
        self.stage = "wait_panel_request_access"
        await asyncio.wait_for(panel_access, APP_TIMEOUT)
        await self._await_reply_sent(Cmd.REQUEST_ACCESS)
        self.stage = "software_version"
        version = self._expect(Cmd.SOFTWARE_VERSION)
        await self._send_app(Cmd.SOFTWARE_VERSION.to_bytes(2, "big") + msg.OWN_SOFTWARE_VERSION)
        try:
            await asyncio.wait_for(version, APP_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning("Panel did not send its software version")

    async def _login(self) -> None:
        lead_in = self._expect(Cmd.ACCESS_LEVEL_LEAD_IN_OUT)
        part_assign = self._expect(Cmd.PARTITION_ASSIGNMENT)
        zone_assign = self._expect(Cmd.ZONE_ASSIGNMENT)
        try:
            await self._request(Cmd.ENTER_ACCESS_LEVEL, msg.build_enter_access_level(self._pin))
        except CommandFailed as err:
            if err.code == RESP_INVALID_ACCESS_CODE and not err.is_command_error:
                raise AuthenticationFailed("invalid user PIN") from err
            raise
        # Login notifications: order is not guaranteed, wait a little for them.
        done, _ = await asyncio.wait({lead_in, part_assign, zone_assign}, timeout=5)
        if lead_in not in done:
            _LOGGER.debug("No Access Level Lead-In received")

    async def _discover(self) -> None:
        # Partitions assigned to the user
        if not self.user_partitions:
            try:
                status = await self._request_status(
                    Cmd.PARTITION_STATUS,
                    msg.build_partition_status_request(list(range(1, MAX_PARTITIONS + 1))),
                )
                self.user_partitions = sorted(status)
            except (TimeoutError, ITv2Error) as err:
                _LOGGER.debug("Partition discovery failed: %s", err)
        # Zones assigned to the user
        if not self.user_zones:
            try:
                data = await self._request(
                    Cmd.COMMAND_REQUEST,
                    msg.build_command_request(Cmd.ZONE_ASSIGNMENT, msg.var_bytes(0)),
                    lambda c, p: p if c == Cmd.ZONE_ASSIGNMENT else None,
                )
                self.user_zones = msg.parse_zone_assignment(data)[1]
            except (TimeoutError, ITv2Error, ValueError) as err:
                _LOGGER.debug("Zone assignment request failed: %s", err)
        if not self.user_zones:
            count = self.info.max_zones or MAX_ZONES
            _LOGGER.info("Zone assignment unavailable, using zones 1..%d", count)
            self.user_zones = list(range(1, min(count, MAX_ZONES) + 1))
        # NB: do not filter by 0613 "max zones": an Absoluta 16 (fw 3.60.37) reports
        # 16 but has radio zones 17, 18, 20 configured. Missing zones are
        # detected by probing them after the first poll instead.

        # Outputs / remote commands enabled for the user
        try:
            data = await self._request(
                Cmd.SECTION_READ,
                msg.build_section_read(SECTION_ENABLED_OUTPUTS),
                self._section_matcher(SECTION_ENABLED_OUTPUTS),
            )
            enabled = msg.bitmask_to_list(data)
            self.outputs = [n for n in enabled if n <= MAX_OUTPUTS]
            self.remote_commands = [
                n - REMOTE_COMMAND_OUTPUT_OFFSET
                for n in enabled
                if REMOTE_COMMAND_OUTPUT_OFFSET
                < n
                <= REMOTE_COMMAND_OUTPUT_OFFSET + MAX_REMOTE_COMMANDS
            ]
        except (TimeoutError, ITv2Error, ValueError) as err:
            _LOGGER.debug("Enabled outputs read failed: %s", err)
        if self.outputs:
            with contextlib.suppress(ITv2Error, asyncio.TimeoutError):
                await self._request(
                    Cmd.COMMAND_REQUEST,
                    msg.build_command_request(Cmd.COMMAND_OUTPUT_ACTIVATION, b"\x00"),
                    lambda c, p: True if c == Cmd.COMMAND_OUTPUT_ACTIVATION else None,
                )

        if self._load_labels and not self._labels_loaded:
            await self._read_labels()
            self._labels_loaded = True

    @staticmethod
    def _section_matcher(section: int) -> Callable[[int, bytes], bytes | None]:
        def match(cmd: int, payload: bytes) -> bytes | None:
            if cmd != Cmd.SECTION_READ_RESPONSE:
                return None
            sec, data = msg.parse_section_read_response(payload)
            return data if sec == section else None

        return match

    async def _read_label_range(self, option: int, first: int, last: int) -> list[str]:
        def match(cmd: int, payload: bytes):
            if cmd != Cmd.CONFIGURATION_BROADCAST:
                return None
            cfg = msg.parse_configuration(payload)
            return cfg if cfg.option == option and cfg.first == first else None

        cfg = await self._request(
            Cmd.COMMAND_REQUEST,
            msg.build_command_request(
                Cmd.CONFIGURATION_BROADCAST, msg.build_label_request(option, first, last)
            ),
            match,
            timeout=4,
        )
        return cfg.labels

    async def _read_labels_into(
        self, option: int, items: list[int], offset: int, target: dict[int, str]
    ) -> None:
        """Read labels in blocks; a refused block is retried item by item and a
        refused item is skipped, so one bad block never loses the other labels."""
        for first, count in _runs(items, LABEL_CHUNK):
            try:
                labels = await self._read_label_range(
                    option, first + offset, first + offset + count - 1
                )
            except (TimeoutError, ITv2Error, ValueError) as err:
                _LOGGER.debug("Labels %d/%d+%d refused (%s)", option, first, count, err)
                if count == 1:
                    continue
                for item in range(first, first + count):
                    with contextlib.suppress(TimeoutError, ITv2Error, ValueError):
                        single = await self._read_label_range(option, item + offset, item + offset)
                        if single and single[0]:
                            target[item] = single[0]
                continue
            for i, label in enumerate(labels):
                if label:
                    target[first + i] = label

    async def _read_labels(self) -> None:
        try:
            system = await self._read_label_range(OPT_PARTITION_LABEL, 1, 1)
            self.system_label = system[0] if system and system[0] else None
        except (TimeoutError, ITv2Error, ValueError) as err:
            _LOGGER.debug("System label not available: %s", err)
        await self._read_labels_into(
            OPT_PARTITION_LABEL, self.user_partitions, 1, self.partition_labels
        )
        await self._read_labels_into(OPT_ZONE_LABEL, self.user_zones, 0, self.zone_labels)
        await self._read_labels_into(OPT_OUTPUT_LABEL, self.outputs, 0, self.output_labels)
        await self._read_labels_into(
            OPT_OUTPUT_LABEL, self.remote_commands, MAX_OUTPUTS, self.remote_command_labels
        )
        modes: dict[int, str] = {}
        await self._read_labels_into(OPT_ARMING_MODE_LABEL, [1, 2, 3, 4], 0, modes)
        self.arming_mode_labels = {"ABCD"[k - 1]: v for k, v in modes.items()}

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    async def _request_status(self, cmd: int, data: bytes) -> dict:
        def match(c: int, payload: bytes):
            if c != cmd:
                return None
            if cmd == Cmd.PARTITION_STATUS:
                return msg.parse_partition_status(payload)
            return msg.parse_zone_status(payload)

        return await self._request(Cmd.COMMAND_REQUEST, msg.build_command_request(cmd, data), match)

    async def refresh(self) -> None:
        """Poll partition and zone status once."""
        if self.user_partitions:
            await self._request_status(
                Cmd.PARTITION_STATUS, msg.build_partition_status_request(self.user_partitions)
            )
        run_len = 1 if self._single_zone_mode else MAX_ZONE_RUN
        zones = [z for z in self.user_zones if z not in self.invalid_zones]
        for first, count in _runs(zones, run_len):
            try:
                got = await self._request_status(
                    Cmd.ZONE_STATUS, msg.build_zone_status_request(first, count)
                )
                # Some panels truncate multi-zone answers (e.g. to 16 zones):
                # read the zones left out one by one.
                for zone in range(first, first + count):
                    if zone not in got and zone in zones:
                        await self._read_single_zone(zone)
                continue
            except CommandFailed as err:
                if count == 1:
                    self._zone_unavailable(first, err)
                    continue
                _LOGGER.debug(
                    "Zone status %d..%d refused (%s), probing singly", first, first + count - 1, err
                )
            except TimeoutError:
                if count == 1:
                    self._zone_timeout(first)
                    continue
                _LOGGER.warning(
                    "Panel did not answer a multi-zone status request, "
                    "switching to single-zone polling"
                )
                self._single_zone_mode = True
            for zone in range(first, first + count):
                if zone in zones:
                    await self._read_single_zone(zone)

    async def _read_single_zone(self, zone: int) -> None:
        try:
            got = await self._request_status(
                Cmd.ZONE_STATUS, msg.build_zone_status_request(zone, 1)
            )
            if zone not in got:
                self._zone_unavailable(zone, f"answer did not include it: zones {sorted(got)}")
        except CommandFailed as err:
            self._zone_unavailable(zone, err)
        except TimeoutError:
            self._zone_timeout(zone)

    async def _probe_missing_zones(self) -> None:
        """Zones still without status after the first poll are checked one by one."""
        for zone in [z for z in self.user_zones if z not in self.zones]:
            if zone not in self.invalid_zones:
                await self._read_single_zone(zone)

    def _zone_unavailable(self, zone: int, reason: object) -> None:
        """The panel refuses to report this zone: it does not exist on this model."""
        if zone not in self.invalid_zones:
            _LOGGER.warning(
                "Zone %d is assigned to the user but the panel does not report its status "
                "(%s); ignoring it. The ABS-IP reports status only up to the model's zone "
                "limit (%s)",
                zone,
                reason,
                self.info.max_zones or "unknown",
            )
            self.invalid_zones.add(zone)
            self.invalid_zone_reasons[zone] = str(reason)

    def _zone_timeout(self, zone: int) -> None:
        # A zone that never answered is treated as missing; one that used to
        # answer means the link is in trouble.
        if zone in self.zones:
            raise TimeoutError(f"no status for zone {zone}")
        self._zone_unavailable(zone, "no answer")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _targets(self, partition: int) -> list[int]:
        return list(self.user_partitions) if not partition else [partition]

    async def arm(self, partition: int, mode: int = ArmMode.AWAY) -> None:
        """Arm a partition (0 = all partitions of the logged user)."""
        await self._request(Cmd.PARTITION_ARM, msg.build_arm(partition, int(mode)))
        # The panel accepted the command: show the exit delay right away,
        # the real status follows with the 0812 notification / next poll.
        self.arming_requested.update(self._targets(partition))
        self._notify()
        self.request_refresh()

    async def disarm(self, partition: int) -> None:
        await self._request(Cmd.PARTITION_DISARM, msg.build_disarm(partition))
        # Accepted: reflect it immediately (bytes 1-2 reset, keep byte 3)
        for part in self._targets(partition):
            old = self.partitions.get(part)
            if old is not None and old.armed:
                raw = bytearray(old.raw)
                raw[0] = 0x02  # disarmed, ready
                if len(raw) > 1:
                    raw[1] &= ~0x41 & 0xFF  # clear alarm / siren
                self.partitions[part] = msg.PartitionStatus(bytes(raw))
            self.exit_delay.discard(part)
            self.entry_delay.discard(part)
        self._notify()
        self.request_refresh()

    async def set_zone_bypass(self, zone: int, bypass: bool) -> None:
        """Bypass / un-bypass a zone (Single Zone Bypass Write 074A).

        Absoluta applies programming writes only when the user logs out, and
        the ABS-IP closes the TCP session after the log-out (seen on fw
        3.60.37). So: write, Exit Access Level (0401), then an immediate,
        planned reconnection handled by the supervisor (no error, no
        "unavailable" flicker).
        """
        await self._request(
            Cmd.SINGLE_ZONE_BYPASS_WRITE,
            b"\x00" + msg.var_bytes(zone) + bytes([0x01 if bypass else 0x00]),
        )
        status = self.zones.get(zone)
        if status is not None:
            raw = (status.raw | 0x80) if bypass else (status.raw & 0x7F)
            self.zones[zone] = msg.ZoneStatus(raw)
        self._notify()
        self._reconnect_now = True
        with contextlib.suppress(ITv2Error, TimeoutError):
            await self._request(Cmd.EXIT_ACCESS_LEVEL, b"\x00", timeout=3)
        if self._supervisor is None:
            # Not running under the supervisor (e.g. scripts): reconnect inline
            await self._close_transport()
            self._reconnect_now = False
            await self.connect()
            return
        # Wake the poll loop so the supervisor reconnects right away
        self._closed_event.set()
        self._refresh_requested.set()

    async def set_output(self, output: int, on: bool) -> None:
        await self._request(Cmd.COMMAND_OUTPUT, msg.build_command_output(output, on))
        if on:
            self.outputs_on.add(output)
        else:
            self.outputs_on.discard(output)
        self._notify()

    async def trigger_remote_command(self, number: int) -> None:
        await self._request(
            Cmd.COMMAND_OUTPUT,
            msg.build_command_output(REMOTE_COMMAND_OUTPUT_OFFSET + number, True),
        )

    async def user_activity(self, activity: int) -> None:
        await self._request(Cmd.USER_ACTIVITY, msg.build_user_activity(int(activity)))
        self.request_refresh()
