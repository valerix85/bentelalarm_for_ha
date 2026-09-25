# Bentel Absoluta for Home Assistant

Custom Home Assistant integration that connects **locally** to a **Bentel Absoluta** alarm panel
through the **ABS-IP** module, using the **ITv2** protocol over TCP
(no cloud, no MQTT bridge).

> Requires the ITv2 protocol to be enabled on the ABS-IP (default TCP port **3064**,
> encryption disabled) and the PIN of a Master, Normal or Limited user.

## Features

| Platform | What it provides |
|---|---|
| `alarm_control_panel` | **All partitions**: arms/disarms every partition of the user with a single command (combined state; when only some partitions are armed the state is "armed custom bypass" with `armed_partitions`/`disarmed_partitions` attributes). Plus one entity per **partition** assigned to the user: by default only **away** arming and disarm; optionally also Home (*stay*) and Night (*instant stay*). States `arming` (exit delay), `pending` (entry delay), `triggered`. |
| `binary_sensor` | One per **zone** (open/closed, with alarm, memory, tamper, fault, low battery and bypassed attributes); panel-wide **troubles**; per-partition *troubles* and *ready* (disabled by default); **connection** status. |
| `sensor` | **Last event** from the panel event log (e.g. "Arming OK", "Zone alarm – Kitchen window"), with timestamp and the last 5 events as attributes. Each new event is also fired as `bentel_absoluta_event` with `type: log`. |
| `switch` | The **programmable outputs** enabled for the user and **bypass** of each zone. The panel applies a bypass at log-out, so the integration logs out and back in automatically (a few seconds). |
| `button` | **Remote commands**, **arming modes A-D** (global), *clear alarm memory*, *clear alarms/troubles/tampers*, *sync clock* (sets Home Assistant's time on the panel). |
| Events | `bentel_absoluta_event` with `type`: `arming`, `blocking_condition` (e.g. mains failure preventing arming), `trouble`, `arming_pre_alert`, `log`. |
| Diagnostics | Download from the device page (PIN redacted). |

Partition, zone, output and arming mode names are read from the panel.
The UI is translated into English and Italian; event texts follow Home Assistant's language.

## Installation

**HACS** (recommended): *HACS → ⋮ → Custom repositories* →
`https://github.com/valerix85/bentelalarm_for_ha`, category *Integration*, then install
*Bentel Absoluta* and restart Home Assistant.

**Manual**: copy `custom_components/bentel_absoluta/` into `<config>/custom_components/`
and restart.

Then *Settings → Devices & services → Add integration → Bentel Absoluta* and enter the
ABS-IP address, port and user PIN.

### Options

- **Status polling interval** (default 5 s): the ABS-IP does *not* notify zone open/close
  changes, so zones are polled. The same polling acts as the keep-alive recommended by the
  Bentel guide.
- **Arming modes offered** (default: *Away* only): add *Home* (stay) and *Night* (instant stay)
  only if you use them on the panel, and *Forced* (away arming even with open zones, which are
  bypassed; shown in Home Assistant as "custom bypass") only if you really need it.
- **Require code**: when enabled, the alarm entities ask for the PIN to arm/disarm, and the
  arming mode A-D buttons and zone bypass switches are not created.

## Good to know

- The ABS-IP accepts **a single ITv2 connection** at a time.
- The ITv2 session has the **lowest priority**: when BOSS or the mobile app connects, the panel
  closes it. The integration reconnects by itself (back-off from 10 s to 5 min).
- Only the partitions/zones/outputs assigned to the configured user are exposed.
- ABS-IP AES encryption is not supported: keep it disabled for the ITv2 client.

## Known limitations

- **Zone status beyond the model limit**: over ITv2 the panel reports a maximum number of zones
  (e.g. 16 on an Absoluta 16). Even if more zones are configured in BOSS (e.g. wireless 17-20),
  the ABS-IP only returns the status of the first N: the others are not created (the reason is
  shown in the diagnostics, `invalid_zone_reasons`). Workaround: use slots within the limit for
  important sensors.
- **Outputs**: only outputs *reserved* to the partition with a programmed action are exposed
  (the panel decides which ones are available to ITv2).
- **Zone bypass**: the panel applies it at log-out and then closes the session; the integration
  reconnects automatically, so each bypass takes a few seconds.
- **Arming refused**: if a zone is open (or a blocking condition is present) the panel refuses
  to arm; Home Assistant shows the error with the list of open zones (of that partition, when
  the panel provides the zone-partition assignment) and the state is unchanged. With the
  *All partitions* entity some partitions may arm and others not: the state becomes partial
  and the attributes tell which.

## Debugging

```yaml
logger:
  default: warning
  logs:
    custom_components.bentel_absoluta: debug
```

With debug logging every transmitted/received packet (`TX`/`RX`) is logged in hex:
attach it to issues together with the diagnostics file.

## Development

```
custom_components/bentel_absoluta/
├── itv2/            # protocol library, no Home Assistant dependencies
│   ├── framing.py   # 0x7E/0x7F, 7D 00/01/02 escaping, length, CRC-16/CCITT-FALSE
│   ├── messages.py  # encoding/decoding of the commands used by Absoluta
│   ├── events.py    # event log decoding (Appendix B texts)
│   └── client.py    # asyncio session: sequences/ACKs, handshake, login, polling, commands
├── alarm_control_panel.py, binary_sensor.py, sensor.py, switch.py, button.py
└── config_flow.py   # setup, reauth, reconfigure, options
tests/
├── fake_panel.py    # Absoluta panel simulator (ITv2 TCP server)
├── test_itv2.py     # protocol tests
└── test_integration.py  # tests inside a real Home Assistant
scripts/diagnose.py  # standalone connection test against a real panel
```

```bash
pip install pytest-homeassistant-custom-component
pytest
```

References: *Interactive Protocol V2.00 R2.03* and *ITv2 Usage Guide for Absoluta Rev 1.05*
(Tyco / Bentel Security). Message formats and the session sequence were also cross-checked
against the open-source Java bridge
[mostorer/bentel-absoluta-local](https://github.com/mostorer/bentel-absoluta-local).

### Claude Code

In issues and pull requests you can write `@claude` to get help from
[Claude Code](https://github.com/anthropics/claude-code-action) (workflow
`.github/workflows/claude.yml`).

<details>
<summary>Setting up the Claude workflow with a custom GitHub App</summary>

1. Create a GitHub App (*Settings → Developer settings → GitHub Apps*) with repository
   permissions **Contents**, **Issues**, **Pull requests** set to *Read & write*.
2. Generate a *private key* (`.pem`) and install the App on this repository.
3. Create an API key at <https://console.anthropic.com> (prepaid credit required).
4. In *Settings → Secrets and variables → Actions* add `APP_ID`, `APP_PRIVATE_KEY`
   (contents of the `.pem`) and `ANTHROPIC_API_KEY` (the key from step 3).
   Instead of an API key you can use a Claude Pro/Max subscription token
   (`claude setup-token` → secret `CLAUDE_CODE_OAUTH_TOKEN` and, in the workflow,
   `claude_code_oauth_token:` instead of `anthropic_api_key:`).

Full guide: <https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md>
</details>

## Contributing

Issues and pull requests are welcome: <https://github.com/valerix85/bentelalarm_for_ha>
