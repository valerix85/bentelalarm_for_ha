"""Home Assistant tests: config flow + setup against the simulated panel.

Requires pytest-homeassistant-custom-component (skipped otherwise).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "bentel_absoluta"))
sys.path.insert(0, str(Path(__file__).parent))

from fake_panel import FakePanel  # noqa: E402
from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.bentel_absoluta.const import CONF_PIN, DOMAIN  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def expected_lingering_tasks() -> bool:
    return True


@pytest.fixture
async def panel(socket_enabled):
    fake = FakePanel()
    await fake.start()
    yield fake
    await fake.stop()


async def test_config_flow(hass: HomeAssistant, panel: FakePanel) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "0000"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "12a"}
    )
    assert result["errors"] == {CONF_PIN: "invalid_pin"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bentel Absoluta 42"
    assert result["result"].unique_id == "00:03:4f:06:00:03"
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_setup_and_control(hass: HomeAssistant, panel: FakePanel) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:03:4f:06:00:03",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"},
        options={"poll_interval": 2},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all()}
    area = states["alarm_control_panel.bentel_absoluta_42_area_02"]
    assert area.state == "disarmed"
    assert states["binary_sensor.bentel_absoluta_42_zona_01"].state == "off"
    assert states["switch.bentel_absoluta_42_uscita_04"].state == "off"
    assert "button.bentel_absoluta_42_uscita_52" in states  # remote command 2 (label offset 50)
    assert states["binary_sensor.bentel_absoluta_42_connection"].state == "on"
    assert "button.bentel_absoluta_42_arm_mode_modo_01" in states

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": "alarm_control_panel.bentel_absoluta_42_area_02"},
        blocking=True,
    )
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert hass.states.get("alarm_control_panel.bentel_absoluta_42_area_02").state == "armed_away"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.bentel_absoluta_42_uscita_04"}, blocking=True
    )
    await asyncio.sleep(0.2)
    assert hass.states.get("switch.bentel_absoluta_42_uscita_04").state == "on"

    panel.zone_raw[1] = 0x01
    await asyncio.sleep(2.5)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bentel_absoluta_42_zona_01").state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not panel.errors


async def test_arm_modes_option(hass: HomeAssistant, panel: FakePanel) -> None:
    from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature as F

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:03:4f:06:00:03",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    eid = "alarm_control_panel.bentel_absoluta_42_area_02"
    # default: only "armed" (away) besides disarm
    assert hass.states.get(eid).attributes["supported_features"] == F.ARM_AWAY

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 5, "arm_modes": [], "require_code": False}
    )
    assert result["errors"] == {"arm_modes": "no_arm_mode"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"poll_interval": 5, "arm_modes": ["away", "home"], "require_code": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()
    assert hass.states.get(eid).attributes["supported_features"] == F.ARM_AWAY | F.ARM_HOME

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_global_panel(hass: HomeAssistant, panel: FakePanel) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:03:4f:06:00:03",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"},
        options={"poll_interval": 2},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    glob = "alarm_control_panel.bentel_absoluta_42_all_partitions"
    area2 = "alarm_control_panel.bentel_absoluta_42_area_02"
    assert hass.states.get(glob).state == "disarmed"

    # one command arms every partition (partition 0)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": glob}, blocking=True
    )
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()
    assert all(panel.part_raw[p][0] & 0x01 for p in panel.partitions)
    assert hass.states.get(glob).state == "armed_away"

    # disarm a single partition -> global shows partially armed
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": area2}, blocking=True
    )
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()
    state = hass.states.get(glob)
    assert state.state == "armed_custom_bypass"
    assert state.attributes["partially_armed"] is True
    assert state.attributes["disarmed_partitions"] == ["Area 02"]

    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": glob}, blocking=True
    )
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()
    assert hass.states.get(glob).state == "disarmed"
    assert not any(panel.part_raw[p][0] & 0x01 for p in panel.partitions)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_arm_refused_open_zone(hass: HomeAssistant, panel: FakePanel) -> None:
    from homeassistant.exceptions import HomeAssistantError

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:03:4f:06:00:03",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"},
        options={"poll_interval": 2},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    panel.zone_raw[3] = 0x01  # a window left open
    await asyncio.sleep(2.5)
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": "alarm_control_panel.bentel_absoluta_42_all_partitions"},
            blocking=True,
        )
    assert exc.value.translation_key == "arm_failed_open_zones"
    assert exc.value.translation_placeholders == {"zones": "Zona 03"}
    assert hass.states.get("alarm_control_panel.bentel_absoluta_42_area_02").state == "disarmed"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_new_features(hass: HomeAssistant, panel: FakePanel) -> None:
    from homeassistant.helpers import entity_registry as er

    await hass.config.async_update(language="it")
    panel.log_event(0x004D)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:03:4f:06:00:03",
        version=1,
        minor_version=1,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: panel.port, CONF_PIN: "1234"},
        options={"poll_interval": 2, "arm_modes": ["away", "forced"]},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # an old (<=0.2.6) per-partition sensor, created enabled
    old = registry.async_get_or_create(
        "binary_sensor", DOMAIN, "00:03:4f:06:00:03_partition_1_trouble", config_entry=entry
    )
    assert old.disabled_by is None
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert registry.async_get(old.entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    # last event sensor (Italian text)
    sensors = [s for s in hass.states.async_all("sensor")]
    assert len(sensors) == 1 and sensors[0].state == "Inser. eseguito"

    # log events are fired on the bus
    fired = []
    hass.bus.async_listen("bentel_absoluta_event", lambda e: fired.append(e.data))
    panel.log_event(0x1007, who=2)
    await entry.runtime_data.check_events()
    await hass.async_block_till_done()
    assert any(d["type"] == "log" and d["zone"] == 3 for d in fired)
    assert hass.states.get(sensors[0].entity_id).state.startswith("Allarme di zona")

    # undocumented codes (class 0 code 0x0D) do not replace the last event
    panel.log_event(0x000D)
    await entry.runtime_data.check_events()
    await hass.async_block_till_done()
    state = hass.states.get(sensors[0].entity_id)
    assert state.state.startswith("Allarme di zona")
    assert state.attributes["recent"][0] == "Generico 0x0D"

    # forced arming offered as custom bypass and works with an open zone
    panel.zone_raw[3] = 0x01
    glob = next(
        s.entity_id
        for s in hass.states.async_all("alarm_control_panel")
        if s.attributes.get("armed_partitions") is not None
    )
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_custom_bypass", {"entity_id": glob}, blocking=True
    )
    assert panel.log[-1][0] == 0x0900 and panel.log[-1][1][-1] == 0x82

    # clock sync button
    button = next(s.entity_id for s in hass.states.async_all("button") if "orologio" in s.entity_id)
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert panel.panel_time is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_extra_zones_option(hass: HomeAssistant, socket_enabled) -> None:
    fake = FakePanel(unassigned_zones=(7,))
    await fake.start()
    try:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="00:03:4f:06:00:03",
            data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_PIN: "1234"},
            options={"poll_interval": 2},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.bentel_absoluta_42_zona_07") is None

        # invalid list is rejected
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"poll_interval": 2, "arm_modes": ["away"], "extra_zones": "7, x"}
        )
        assert result["errors"] == {"extra_zones": "invalid_zone_list"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"poll_interval": 2, "arm_modes": ["away"], "extra_zones": "7"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        await asyncio.sleep(0.5)
        await hass.async_block_till_done()

        client = entry.runtime_data
        assert 7 in client.user_zones and 7 not in client.assigned_zones
        assert hass.states.get("binary_sensor.bentel_absoluta_42_zona_07").state == "off"
        # no bypass switch for zones not assigned to the user
        switches = [s.entity_id for s in hass.states.async_all("switch")]
        assert not any("zona_07" in s for s in switches)
        assert any("zona_01" in s for s in switches)

        fake.zone_raw[7] = 0x01
        await asyncio.sleep(2.5)
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.bentel_absoluta_42_zona_07").state == "on"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not fake.errors
    finally:
        await fake.stop()
