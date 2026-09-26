# Bentel Absoluta for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/valerix85/bentelalarm_for_ha)](https://github.com/valerix85/bentelalarm_for_ha/releases)
[![Validate](https://github.com/valerix85/bentelalarm_for_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/valerix85/bentelalarm_for_ha/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/valerix85/bentelalarm_for_ha)](LICENSE)

Control your **Bentel Absoluta** alarm panel from Home Assistant. The integration talks
directly to the panel's **ABS-IP** module on your network, using Bentel's **ITv2** protocol:
fully local, no cloud account, no MQTT bridge, no extra hardware.

## Features

- **Arm and disarm** each partition, or all of them at once with the *All partitions* panel
- **Zone sensors**: open/closed, with alarm, tamper, fault, low battery and bypass details
- **Zone bypass** switches
- **Programmable outputs**, **remote commands** and **arming modes A–D**
- **Troubles** sensor and **Last event** sensor from the panel event log
- Buttons to **sync the panel clock** and **clear alarm memory** or alarms/faults/tampers
- **Events** for automations (arming, troubles, event log…)
- Partition, zone, output and arming mode **names are read from the panel**
- English and Italian UI, diagnostics download (PIN redacted)

## Requirements

- An Absoluta panel with the **ABS-IP** module on your network
- The **ITv2** protocol on the ABS-IP, with **encryption disabled**, on TCP port **3064**
  (default). On the panels tested so far this works out of the box, with no change in BOSS;
  port and encryption are installer settings (see the Absoluta installer manual or ask your
  installer) if yours were changed
- The **PIN** of a Master, Normal or Limited user: the integration sees only the partitions,
  zones and outputs assigned to that user

### Tested hardware

| Panel | Firmware | Status |
|---|---|---|
| Absoluta 16 + ABS-IP | 3.60.37 | ✅ Tested by the author |
| Absoluta Plus 48 + ABS-IP | 4.30.35 | ✅ Reported working by a user |

Other models and firmware versions should work but have not been tested yet: feedback is
very welcome, please [open an issue](https://github.com/valerix85/bentelalarm_for_ha/issues/new/choose).

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=valerix85&repository=bentelalarm_for_ha&category=integration)

Or manually: *HACS → ⋮ → Custom repositories* → add
`https://github.com/valerix85/bentelalarm_for_ha` with category *Integration*.
Then download **Bentel Absoluta** and **restart Home Assistant**.

### Manual

Copy `custom_components/bentel_absoluta/` into the `custom_components/` folder of your
Home Assistant configuration and restart Home Assistant.

> After every update, **restart** Home Assistant: reloading the integration is not enough.

## Configuration

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=bentel_absoluta)

Or go to *Settings → Devices & services → Add integration → Bentel Absoluta* and enter the
ABS-IP address, the port and the user PIN.

### Options

Available from the integration's **Configure** button:

| Option | Default | Description |
|---|---|---|
| Status polling interval | 5 s | The ABS-IP does not push zone open/closed changes, so zones are read at this interval. |
| Arm modes | Away | Add *Home* (stay) and *Night* (instant stay) only if you use them on the panel. *Forced* arms even with open zones, which get bypassed; it appears in Home Assistant as "custom bypass". |
| Require code | Off | Home Assistant asks for the PIN to arm/disarm. Arming mode buttons and zone bypass switches are not created. |
| Additional zones | – | Zones to show even if the panel does not assign them to the user, e.g. chime or real-time zones that belong to no partition (`15, 16` or `20-22`). No bypass switch is created for them. |

## Entities

| Entity | Notes |
|---|---|
| **All partitions** (alarm panel) | Arms/disarms every partition at once. When only some partitions are armed the state is *armed custom bypass* and the `armed_partitions` / `disarmed_partitions` attributes tell which. |
| **Partition** (alarm panel) | One per partition. States include *arming* (exit delay), *pending* (entry delay) and *triggered*. |
| **Zone** (binary sensor) | One per zone, on = open. Attributes: alarm, alarm memory, tamper, fault, low battery, bypassed. |
| **Troubles** (binary sensor) | On when the panel reports a trouble (mains, battery, faults…). |
| **Connection** (binary sensor) | State of the ITv2 session. |
| **Last event** (sensor) | Latest entry of the panel event log, e.g. *Zone alarm – Kitchen window*; the last events are in the `recent` attribute. |
| **Output** / **Zone bypass** (switch) | Programmable outputs enabled for the user; bypass of each zone (takes a few seconds, see below). |
| **Remote command**, **Arm mode A–D**, **Clear alarm memory**, **Clear alarms, faults and tampers**, **Sync panel clock** (button) | |

Per-partition *troubles* and *ready* sensors are also available, disabled by default.

### Events

The integration fires `bentel_absoluta_event` with a `type` field: `log` (every new entry of
the panel event log), `arming`, `blocking_condition` (e.g. mains failure preventing arming),
`trouble` and `arming_pre_alert`. Example: get notified of any zone alarm.

```yaml
automation:
  - alias: "Alarm: zone alarm notification"
    triggers:
      - trigger: event
        event_type: bentel_absoluta_event
        event_data:
          type: log
          class: 1        # alarm events
          restore: false
    actions:
      - action: notify.notify
        data:
          message: "{{ trigger.event.data.text_en }} {{ trigger.event.data.zone_label or '' }}"
```

`log` events carry `text` (Italian), `text_en`, `event_id`, `class`
(0 generic, 1 alarm, 2 tamper, 3 fault, 4 bypass, 5 test), `restore`, `zone`, `zone_label`,
`partitions` and `timestamp`.

## Good to know

- The ABS-IP accepts **only one ITv2 connection** at a time.
- ITv2 has the **lowest priority**: when BOSS or the Bentel mobile app connects, the panel
  closes the Home Assistant session. The integration reconnects by itself (retrying from 10 s
  up to every 5 min).
- **Zone bypass** is applied by the panel when the session ends, so the integration
  reconnects right after it: each bypass takes a few seconds.
- **Arming refused**: if a zone is open or something blocks arming, Home Assistant shows an
  error with the open zones and the state does not change. With *All partitions*, some
  partitions may arm and others not.

## Known limitations

- **Zones above the model limit**: the panel reports a maximum number of zones over ITv2
  (16 on an Absoluta 16). Zones configured above it (e.g. wireless zones 17–20) are not
  created because the ABS-IP does not return their status. Use slots within the limit for
  important sensors.
- **Zones not assigned to the user**: the integration creates the zones the panel assigns
  to the configured user. Zones in partitions the user cannot access, or special zones that
  belong to no partition (e.g. chime, real-time), are missing: enable the user on that
  partition in BOSS, or list them in the *Additional zones* option.
- **Outputs**: only outputs reserved to the user's partitions with a programmed action are
  available over ITv2.
- ABS-IP **AES encryption** is not supported.

## Troubleshooting

1. Check the **Connection** sensor and that BOSS or the mobile app are not connected.
2. Download the **diagnostics**: device page → ⋮ → *Download diagnostics* (the PIN is redacted).
3. For a detailed log: *Settings → Devices & services → Bentel Absoluta → ⋮ → Enable debug
   logging*, reproduce the problem, then disable it to download the log (every packet is
   logged in hex).
4. [Open an issue](https://github.com/valerix85/bentelalarm_for_ha/issues/new/choose)
   attaching both files.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the code
structure, tests and protocol notes.

## Credits

Built on Bentel's *ITv2 Usage Guide for Absoluta* and *Interactive Protocol V2.00*
documentation; the session sequence was cross-checked against the open-source Java bridge
[mostorer/bentel-absoluta-local](https://github.com/mostorer/bentel-absoluta-local).
Developed with the help of [Claude Code](https://claude.com/claude-code) and tested on a
real panel.

## Disclaimer and license

This is an independent project, not affiliated with or endorsed by Bentel Security or
Tyco / Johnson Controls. "Bentel" and "Absoluta" are trademarks of their respective owners.
Use it at your own risk: it is not a certified security product.

Released under the [MIT License](LICENSE).
