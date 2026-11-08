# Bentel Absoluta for Home Assistant

[![Marketplace](https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
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
| Absoluta 42 + ABS-IP | 3.60.24 | ✅ Reported working by a user |
| Absoluta 42 + ABS-IP | 3.60.27 | ✅ Reported working by a user |
| Absoluta 42 + ABS-IP | 3.60.28 | ✅ Reported working by a user (all 42 zones) |
| Absoluta 42 + ABS-IP 2.00.08 | 3.60.37 | ✅ Reported working by a user (all 42 zones) |
| Absoluta 48 + ABS-IP | 4.30.25 | ✅ Reported working by a user |
| Absoluta Plus 48 + ABS-IP | 4.30.35 | ✅ Reported working by a user |
| Absoluta Plus 48 (B104) + ABS-IP 02.00.10.01 | 4.30.32 | ✅ Reported working by a user (poll interval 1 s) |

#### ABS-IP firmware

The ABS-IP firmware matters more than the panel firmware. The full version is shown in BOSS
(the integration diagnostics only show the first two numbers, e.g. `02 00`).

| ABS-IP firmware | Status |
|---|---|
| 2.00.08 | ✅ Works |
| 2.00.09, 2.00.10 | ❌ On some panels status requests are not answered: no zone/partition status, reconnection every ~30 s ([#8](https://github.com/valerix85/bentelalarm_for_ha/issues/8), [#9](https://github.com/valerix85/bentelalarm_for_ha/issues/9)) |
| 02.00.10.01 | ✅ Works from integration 0.3.17: about 0.4 % of the replies are lost and retried automatically ([#11](https://github.com/valerix85/bentelalarm_for_ha/issues/11)) |

Other models and firmware versions should work but have not been tested yet: feedback is
very welcome, please [open an issue](https://github.com/valerix85/bentelalarm_for_ha/issues/new/choose).

## Installation

### Marketplace (Home Assistant 2026.11 or later, recommended)

[![Open your Home Assistant instance and open this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=valerix85&repository=bentelalarm_for_ha&category=integration)

The button opens the repository in the Marketplace. Or manually: *Settings → Marketplace →
Add from link*, enter `valerix85/bentelalarm_for_ha` and select *Add* (choose *Integration*
if asked). Then install **Bentel Absoluta** and **restart Home Assistant**.

If you installed it with HACS before 2026.11, Home Assistant moves it to the Marketplace
automatically when you update: updates keep coming, nothing to do.

### HACS (Home Assistant before 2026.11)

Use the button above, or *HACS → ⋮ → Custom repositories* → add
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
| Status polling interval | 5 s | The ABS-IP does not push zone open/closed changes, so zones are read at this interval (1–60 s). Partition status is pushed by the panel on alarms and faults, so it is read after a notification or a command, once the zones stop changing (for "ready to arm"), and at least every 10 s. For zones driving lights (PIR) 1–2 s works well; lower values mean more traffic to the ABS-IP. |
| Arm modes | Away | Add *Home* (stay) and *Night* (instant stay) only if you use them on the panel. *Forced* arms even with open zones, which get bypassed; it appears in Home Assistant as "custom bypass". |
| Require code to disarm | Off | Home Assistant asks for the PIN to disarm. Zone bypass switches are not created. |
| Also require the code to arm | On | Only used with the option above. On: the PIN is asked to arm too and the arming mode buttons are not created. Off: arming needs no PIN, so automations and the *Arm mode A–D* buttons can arm, while disarming stays protected. |

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
| **Remote command**, **Arm mode A–D**, **Clear alarm memory**, **Clear alarms, faults and tampers**, **Sync panel clock** (button) | Each arm mode A–D also has a **(forced)** button, disabled by default: the panel arms even with open zones that can be bypassed, like the Bentel app after its confirmation (otherwise the panel refuses with error 0x01). Each remote command also has a **… OFF** button, disabled by default: it deactivates the command, which is useful when the command keeps an output on (latched action). ITv2 reports no state for remote commands. |

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

- The ABS-IP accepts **only one ITv2 connection** at a time: configure each panel **once**
  in Home Assistant. To switch to another user's PIN use *Reconfigure* on the existing entry;
  two entries for the same panel keep disconnecting each other.
- ITv2 has the **lowest priority**: when BOSS or the Bentel mobile app connects, the panel
  closes the Home Assistant session. The integration reconnects by itself: it waits 1 minute
  after the panel ends the session, and while BOSS or the app is still connected (the panel
  answers "system is locked out") it retries every 2 minutes. After a network loss it retries
  from 10 s up to every minute.
- **Zone bypass** is applied by the panel when the session ends, so the integration
  reconnects right after it: each bypass takes a few seconds.
- **Arming refused**: if a zone is open or something blocks arming, Home Assistant shows an
  error with the open zones and the state does not change. With *All partitions* the panel
  still arms the partitions that are ready: Home Assistant then tells which partitions were
  armed and which were not (with their open zones).

## Known limitations

- **Zones above the model limit**: the panel reports a maximum number of zones over ITv2
  (16 on an Absoluta 16). Zones configured above it (e.g. wireless zones 17–20) are not
  created because the ABS-IP does not return their status. Bentel / Johnson Controls
  engineering confirmed this is an intentional limit of the ITv2 implementation, not fixed
  by any ABS-IP firmware. Use slots within the limit for important sensors. Their alarm and tamper events still appear in the event log
  (*Last event* sensor and `bentel_absoluta_event`).
- **No more firmware updates**: Bentel / Johnson Controls has declared the Absoluta 16, 42
  and 104 panels obsolete (official support and firmware development have ended, October
  2026), so the ITv2 limits of these models will not change. The Absoluta Plus is the
  current, supported model.
- **Zones not assigned to the user**: only zones in the partitions the configured user is
  enabled on are created. If a zone is missing, enable the user on that zone's partition in
  BOSS and reload the integration (the panel does not report the real status of other zones).
- **Outputs**: only outputs reserved to the user's partitions with a programmed action are
  available over ITv2.
- ABS-IP **AES encryption** is not supported.

## Troubleshooting

1. Check the **Connection** sensor and that BOSS, the mobile app or other ITv2 clients (old
   bridges/add-ons, a second Home Assistant entry or instance for the same panel) are not connected.
2. Download the **diagnostics**: device page → ⋮ → *Download diagnostics* (the PIN is redacted).
3. For a detailed log: *Settings → Devices & services → Bentel Absoluta → ⋮ → Enable debug
   logging*, reproduce the problem, then disable it to download the log (every packet is
   logged in hex; the user code in the login frame is redacted).
4. **Connected, but no zone/partition status and a reconnection every ~30 s** (debug log shows
   login working but status requests answered `0x18` or not at all): the ABS-IP does not answer
   ITv2 status requests. Two users report this with **ABS-IP firmware 2.00.09 / 2.00.10**, while
   2.00.08 works on the same panel
   ([#8](https://github.com/valerix85/bentelalarm_for_ha/issues/8),
   [#9](https://github.com/valerix85/bentelalarm_for_ha/issues/9)). In #9 re-flashing the panel
   firmware with BOSS (settings are kept) left the ABS-IP on 2.00.08 and everything worked.
   Check the ABS-IP firmware in BOSS before buying a new module (see
   [ABS-IP firmware](#abs-ip-firmware)).
5. [Open an issue](https://github.com/valerix85/bentelalarm_for_ha/issues/new/choose)
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
