"""Tests for the ITv2 protocol library (no Home Assistant needed)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "bentel_absoluta"))
sys.path.insert(0, str(Path(__file__).parent))

from fake_panel import FakePanel  # noqa: E402
from itv2 import messages as m  # noqa: E402
from itv2.client import AbsolutaClient, AuthenticationFailed, CommandFailed  # noqa: E402
from itv2.const import ArmMode, Cmd  # noqa: E402
from itv2.framing import (  # noqa: E402
    FrameReader,
    Packet,
    crc16_ccitt,
    encode_packet,
    escape,
    unescape,
)

# ---------------------------------------------------------------- framing


def test_crc_ccitt_false_check_value():
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_escape_example_from_spec():
    # spec 3.1.1: 01 7D 91 -> 01 7D 00 91
    assert escape(bytes([0x01, 0x7D, 0x91])) == bytes([0x01, 0x7D, 0x00, 0x91])
    assert unescape(escape(bytes(range(256)))) == bytes(range(256))


def test_simple_ack_layout():
    frame = encode_packet(Packet(5, 9))
    raw = unescape(frame[1:-1])
    assert raw[:3] == bytes([0x04, 5, 9])  # bytes-to-follow == 4 for a simple ACK


def test_roundtrip_and_resync():
    pkt = Packet(0x7E, 0x7F, bytes.fromhex("0812 02 A500 03") + bytes(range(0x70, 0x80)))
    reader = FrameReader()
    out = reader.feed(b"\x00garbage\x7e\x01" + encode_packet(pkt) + encode_packet(Packet(1, 2)))
    assert out[0] == pkt
    assert out[1].is_ack


def test_long_length_prefix():
    pkt = Packet(1, 1, bytes(300))
    assert FrameReader().feed(encode_packet(pkt)) == [pkt]


# ---------------------------------------------------------------- messages


def test_pin_encoding():
    assert m.encode_pin("12345") == bytes([0xA1, 0x23, 0x45])
    assert m.encode_pin("0001") == bytes([0xAA, 0x00, 0x01])
    with pytest.raises(ValueError):
        m.encode_pin("12a4")


def test_guide_examples():
    # Arm partition 3 away: 09 00 04 01 03 02
    assert m.build_arm(3, ArmMode.AWAY) == bytes.fromhex("01 03 02")
    # Output 4 on: 09 02 05 00 01 04 01
    assert m.build_command_output(4, True) == bytes.fromhex("00 01 04 01")
    # Zone status: zone 1 bypassed, zone 2 in alarm
    z = m.parse_zone_status(bytes.fromhex("01 01 01 10 01 80 20") + bytes(14))
    assert z[1].bypassed and not z[1].alarm
    assert z[2].alarm
    assert len(z) == 16
    # Partition status: 4 partitions (1,3,6,8) disarmed and ready
    p = m.parse_partition_status(bytes.fromhex("02 A5 00 03") + bytes.fromhex("020000") * 4)
    assert sorted(p) == [1, 3, 6, 8]
    assert all(s.ready and not s.armed for s in p.values())
    # Command output activation: outputs 4 and 5 on
    assert m.parse_output_activation(bytes.fromhex("00 01 18")) == {4, 5}


def test_datetime_example():
    # spec 5.5: 35 B3 8A C1 == June 1st 2005 06:45:39
    d = m.decode_datetime(bytes.fromhex("35B38AC1"))
    assert (d.year, d.month, d.day, d.hour, d.minute, d.second) == (2005, 6, 1, 6, 45, 39)
    assert m.encode_datetime(d) == bytes.fromhex("35B38AC1")


def test_software_version():
    info = m.PanelInfo()
    m.parse_software_version(bytes.fromhex("35 00 00 1E 02 03 00 B2 01 03 01"), info)
    assert info.firmware == "3.50.30"
    assert info.model == "Absoluta 104"


# ---------------------------------------------------------------- client


async def _started(panel: FakePanel, pin: str = "1234", **kw) -> AbsolutaClient:
    await panel.start()
    client = AbsolutaClient("127.0.0.1", pin, panel.port, poll_interval=0.3, **kw)
    await client.start()
    return client


@pytest.mark.asyncio
async def test_full_session():
    panel = FakePanel()
    client = await _started(panel)
    try:
        assert client.connected
        assert client.info.identifier == "00:03:4F:06:00:03"
        assert client.info.model == "Absoluta 42"
        assert client.user_partitions == [1, 2]
        assert client.user_zones == [1, 2, 3, 5]
        assert client.outputs == [1, 4]
        assert client.remote_commands == [2]
        assert client.zone_labels[5] == "Zona 05"
        assert client.partition_labels[2] == "Area 03"  # offset +1 on the panel
        assert client.arming_mode_labels["A"] == "Modo 01"
        assert set(client.zones) == {1, 2, 3, 5}
        assert client.partitions[1].ready

        # zone opens -> seen at next poll
        panel.zone_raw[3] = 0x01
        await asyncio.sleep(0.8)
        assert client.zones[3].open

        # arming refused while a zone is open
        events = []
        client.add_event_listener(lambda t, d: events.append((t, d)))
        with pytest.raises(CommandFailed):
            await client.arm(1, ArmMode.AWAY)
        await asyncio.sleep(0.2)
        assert ("blocking_condition", {"condition": "mains"}) in events

        panel.zone_raw[3] = 0
        await client.arm(1, ArmMode.AWAY)
        await asyncio.sleep(0.3)
        assert client.partitions[1].armed and client.partitions[1].away
        await client.disarm(0)
        await asyncio.sleep(0.3)
        assert not client.partitions[1].armed

        await client.set_output(4, True)
        await asyncio.sleep(0.2)
        assert 4 in client.outputs_on
        assert not panel.errors
    finally:
        await client.stop()
        await panel.stop()
    assert any(c == Cmd.EXIT_ACCESS_LEVEL for c, _ in panel.log)


@pytest.mark.asyncio
async def test_wrong_pin():
    panel = FakePanel(pin="9999")
    await panel.start()
    client = AbsolutaClient("127.0.0.1", "1234", panel.port)
    with pytest.raises(AuthenticationFailed):
        await client.connect()
    await panel.stop()


@pytest.mark.asyncio
async def test_multi_zone_fallback_and_zone_request():
    panel = FakePanel(multi_zone_ok=False, send_zone_assignment=False)
    client = await _started(panel, load_labels=False)
    try:
        assert client.user_zones == [1, 2, 3, 5]  # obtained via Command Request 0770
        assert set(client.zones) == {1, 2, 3, 5}
        assert client._single_zone_mode
    finally:
        await client.stop()
        await panel.stop()


@pytest.mark.asyncio
async def test_sequence_rollover():
    panel = FakePanel()
    client = await _started(panel, load_labels=False)
    try:
        for _ in range(300):
            await client.refresh()
        assert client.connected
        assert not panel.errors
    finally:
        await client.stop()
        await panel.stop()


@pytest.mark.asyncio
async def test_reconnect_after_panel_drop(monkeypatch):
    panel = FakePanel()
    client = await _started(panel, load_labels=False)
    try:
        import itv2.client as c

        orig_sleep = asyncio.sleep
        monkeypatch.setattr(c.asyncio, "sleep", lambda s: orig_sleep(min(s, 0.05)))
        panel.writer.close()
        for _ in range(100):
            await orig_sleep(0.05)
            if not client.connected:
                break
        assert not client.connected
        for _ in range(100):
            await orig_sleep(0.05)
            if client.connected:
                break
        assert client.connected
    finally:
        await client.stop()
        await panel.stop()


def test_labels_total_length_and_per_label_length():
    names = [f"Label {i}".ljust(16).encode() for i in range(1, 9)]
    data = b"".join(names)
    # real Absoluta: data length = total (8 x 16 = 0x80)
    total = m.parse_configuration(bytes.fromhex("01 01 01 01 01 08 01 80") + data)
    # one-at-a-time style: data length = single label
    single = m.parse_configuration(bytes.fromhex("01 01 01 01 01 08 01 10") + data)
    assert total.labels == single.labels == [f"Label {i}" for i in range(1, 9)]
    # guide example: partitions 7..9, 3 labels, total length 0x30
    three = m.parse_configuration(bytes.fromhex("01 03 01 08 01 0A 01 30") + b"".join(names[:3]))
    assert three.labels == ["Label 1", "Label 2", "Label 3"]


async def test_absoluta16_like_panel():
    """Real config seen on an Absoluta 16: radio zones 1-18 and 20 (19 disabled),
    labels returned in blocks, multi-zone answers truncated to 16 zones, and a
    zone in the mask that the panel refuses."""
    zones = [*range(1, 19), 20]
    panel = FakePanel(
        zones=zones,
        partitions=range(1, 9),
        phantom_zones=(25,),
        max_zones_per_reply=16,
        zone_label_limit=16,
    )
    client = await _started(panel)
    try:
        assert client.user_zones == zones
        assert client.invalid_zones == {25}
        assert set(client.zones) == set(zones)
        assert client.zone_labels[16] == "Zona 16"
        assert 17 not in client.zone_labels  # refused by the panel...
        assert client.arming_mode_labels["A"] == "Modo 01"  # ...without losing the rest
        assert client.partition_labels[8] == "Area 09"  # partition 8 -> offset 9
        panel.zone_raw[18] = 0x01
        await asyncio.sleep(0.8)  # zones beyond the truncated answer keep updating
        assert client.zones[18].open
        assert client.connected
        assert not panel.errors
    finally:
        await client.stop()
        await panel.stop()


async def test_zone_bypass_and_optimistic_disarm():
    panel = FakePanel()  # closes the session after log-out, like the real ABS-IP
    client = await _started(panel, load_labels=False)
    states = []
    client.add_listener(lambda: states.append(client.connected))
    try:
        await client.set_zone_bypass(2, True)  # must not raise
        assert client.zones[2].bypassed  # optimistic
        assert panel.zone_raw[2] & 0x80  # applied by the panel at log-out
        for _ in range(60):
            await asyncio.sleep(0.05)
            if panel.connections == 2 and panel.logged_in and client.connected:
                break
        assert panel.connections == 2  # planned, immediate reconnection
        assert False not in states  # never shown as unavailable
        await asyncio.sleep(0.5)
        assert client.zones[2].bypassed

        await client.set_zone_bypass(2, False)
        for _ in range(60):
            await asyncio.sleep(0.05)
            if panel.connections == 3 and client.connected and not client.zones[2].bypassed:
                break
        assert not client.zones[2].bypassed

        await client.arm(1, ArmMode.AWAY)
        await asyncio.sleep(0.3)
        assert client.partitions[1].armed
        await client.disarm(1)
        assert not client.partitions[1].armed
        assert not panel.errors
    finally:
        await client.stop()
        await panel.stop()


async def test_event_log_time_sync_and_partition_zones():
    import datetime as dt

    from itv2 import events as ev

    panel = FakePanel()
    panel.log_event(0x004D)  # arming OK
    client = await _started(panel, load_labels=True)
    try:
        assert client.partition_zones == {1: [1, 3, 5], 2: [2]}
        # our own login ("Riconosciuto Cod") is hidden
        assert [e.text() for e in client.last_events] == ["Inser. eseguito"]
        logged = []
        client.add_event_listener(lambda t, d: logged.append((t, d)))
        panel.log_event(0x1007, who=2)  # zone alarm, zone 3
        panel.log_event(0x3818, where=0x0A)  # restore: panel no battery
        await client.check_events()
        texts = [d["text"] for t, d in logged if t == "log"]
        assert texts == ["Allarme di zona", "Ripristino: Cent.NO batteria"]
        zone_event = next(d for t, d in logged if t == "log" and d["zone"])
        assert zone_event["zone"] == 3 and zone_event["zone_label"] == "Zona 03"
        assert client.last_events[0].restore

        now = dt.datetime(2026, 9, 25, 11, 30, 15)
        await client.sync_time(now)
        assert ev.decode_datetime(panel.panel_time) == now

        panel.zone_raw[3] = 0x01
        panel.zone_raw[2] = 0x01
        await client.refresh()
        assert client.open_zones(1) == [3]
        assert client.open_zones(0) == [2, 3]
        assert not panel.errors
    finally:
        await client.stop()
        await panel.stop()


async def test_bypass_event_not_hidden_by_own_relogin():
    panel = FakePanel()
    client = await _started(panel, load_labels=True)
    logged = []
    client.add_event_listener(lambda t, d: logged.append(d) if t == "log" else None)
    try:
        await client.set_zone_bypass(3, True)
        for _ in range(60):
            await asyncio.sleep(0.05)
            if client.connected and panel.connections == 2 and client.last_events:
                break
        await asyncio.sleep(0.3)
        await client.check_events()
        assert client.last_events[0].text() == "Esclusa zone"
        assert client.last_events[0].zone == 3
        assert [d["text"] for d in logged] == ["Esclusa zone"]  # login not notified
    finally:
        await client.stop()
        await panel.stop()
