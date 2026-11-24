# Notes for Claude Code

Home Assistant integration for Bentel Absoluta panels via ABS-IP, ITv2 protocol over TCP.
The repository is English-only (code, comments, docs); Italian is used only in
`translations/it.json` and in the panel's Italian event texts (`itv2/events.py`).

## Layout
- `custom_components/bentel_absoluta/itv2/`: pure protocol library (no HA imports).
- HA platforms: `alarm_control_panel`, `binary_sensor`, `sensor`, `switch`, `button`; `config_flow.py`.
- `tests/fake_panel.py` simulates the panel: every new command must be added there too and
  covered by a test. Run `pytest` (requires `pytest-homeassistant-custom-component`, Python 3.13).

## Verified protocol facts (do not "fix" them)
- Frame: `7E | escape(LEN SEQ RSEQ CMD[2] [APPSEQ] DATA CRC_HI CRC_LO) | 7F`.
  Escaping: 7D→7D 00, 7E→7D 01, 7F→7D 02 (NOT xor 0x20).
- LEN counts SEQ, RSEQ, data and the 2 CRC bytes (simple ACK = LEN 4). CRC-16/CCITT-FALSE
  (poly 0x1021, init 0xFFFF) computed over LEN + content.
- Sequences: the first packet has SEQ 0, then 1..255 wrapping to 1. Every non-empty packet
  must be acknowledged (simple ACK with unchanged SEQ and RSEQ = received seq).
- Handshake: 060A ↔ 060A, 060E ↔ 060E (with 0502 for every command carrying an app-seq),
  060D ↔ 060D, then login 0400 with the PIN in BCD padded with 0xA ("1234" → AA 12 34).
  No encryption.
- Partition status 0812, byte 1: **bit0 = armed**; when armed bit1 stay, bit2 away, bit3 night,
  bit4 no entry delay, bit5 exit delay, bit6 entry delay; when disarmed bit1 ready.
  The PDF table is laid out right-to-left: do not use bit7 as "armed".
- Zone status 0811: bit0 open, 1 tamper, 2 fault, 3 low battery, 4 delinquency, 5 alarm,
  6 memory, 7 bypassed. Zones are NOT notified: they must be polled.
- Some panels do not answer multi-zone reads: the client falls back to single reads.
- Outputs 1..50, remote commands = output 56 + n. Labels via 0800/0771 in Windows-1252.
- 0771 (verified on Absoluta 16 fw 3.60.37): the "data length" field is the TOTAL length of the
  requested block (8 labels -> 0x80), not of a single label. The parser handles both.
- Do NOT filter zones with the 0613 "max zones": an Absoluta 16 (fw 3.60.37) has wireless zones
  17, 18, 20 configured. The 0770 mask reflects enabled zones (disabled 19 is absent).
  Zones the panel refuses or does not report are dropped after reading them singly;
  if a multi-zone answer is truncated, the missing zones are read one by one at every poll.
- The system label (0771 option 3, offset 1) is the keypad screensaver text:
  do not use it as the device name.
- Zone bypass 074A: Absoluta applies it only at log-out (0401), and after log-out the ABS-IP
  CLOSES the TCP connection (verified fw 3.60.37): the client does an immediate "planned"
  reconnect without marking entities unavailable.
  Bypasses are serialised and wait for the session to be fully up (0.3.28, issue #17): a second
  074A + 0401 sent during the discovery of the planned reconnection made the ABS-IP drop the
  session ("connection closed during discovery", entities unavailable ~25 s, second change lost).
- Labels: the panel may refuse a block (e.g. zones >16 on Absoluta 16); each block is
  independent and on refusal it is retried item by item.
- Zone status beyond max_zones (0613): on Absoluta 16 fw 3.60.37 a 0811 request for zone 17
  (or 18, 20) is answered with zones 1..16 anyway. Status of zones >16 is NOT available
  over ITv2 (labels are). This is not a client bug. Bentel/JCI support (Oct 2026): Absoluta
  16/42/104 are obsolete, no more support or firmware, so this will not be fixed upstream.
  JCI engineering (13 Oct 2026) confirmed it is an intentional limit of the ITv2
  implementation and no ABS-IP firmware (including 2.00.10) changes it.
- Event log 0101/4101: 13-byte records = timestamp(4) flags(1) event id(2: class<<12 |
  restore<<11 | code) index(2: where, who) partition mask(4, only the last 2 bytes matter).
  Verified against the guide's examples. In zone events WHO is the 0-based zone index
  (verified on Absoluta 16 fw 3.60: bypassing zone 6 -> WHO 5). A bypass done via ITv2 (074A)
  is logged as "Isolata zona" / "Zone Isolated" (class 4, code 0x03); removing it logs the restore
  of that event plus class 0 code 0x0D, which the guide leaves blank: the "Last event" sensor
  skips undocumented codes.
- Zones outside the user's partitions (verified Absoluta Plus 48 fw 4.30.35): they are not in
  the user's 0770 mask and 0811 answers for them are always 00 (closed) even when open. Do NOT
  expose them (an extra zones option was tried in 0.3.6 and removed in 0.3.7): the fix is
  enabling the ITv2 user on that partition in BOSS.
- Zones per partition: 0800 -> 0770 with partition != 0 (fw >= 3.50.80). If unanswered the
  global list is used.
- Arm all partitions (0900 with partition 0) when some are not ready (verified Absoluta 16
  fw 3.60.37): the answer is only 0502 0x01 (no zone detail), but the panel still arms the
  ready partitions (0230 exit delay + 0812) 0.5 to ~4 s after the 0502. The client waits
  for those notifications (up to 6 s), re-reads 0812 and raises PartiallyArmed with the
  armed / not armed partitions.
- Panel clock: 0741 with ITv2 date/time in local time.
- Every integration login (including the reconnect after a bypass) is logged by the panel as
  "Riconosciuto Cod" (class 0, code 0x15): the client recognises it (one per login, the most
  recent) and neither shows nor fires it, otherwise it would hide the interesting event.
- Partition Status request (0800 -> 0812): send a 2-byte partition mask, as the Usage Guide says
  (Absoluta has 16 partitions, mask length always 0x02); Absoluta 16 fw 3.60.37 answers both.
- ABS-IP firmware 2.00.09 / 2.00.10 (issues #8, #9): handshake, login, login notifications,
  0721, 0912 keep-alive and the 0220 time broadcast work, but 0800 Command Requests get 0x18 or
  no answer at all (0811 never; 0812 only right after a cold power-up) and no zone notifications
  are sent over ITv2, while the Bentel app/cloud still gets them. Same panel and config with
  ABS-IP 2.00.08 works (#8: Absoluta 42 fw 3.60.37, boards swapped; #9: after re-flashing the
  panel the ABS-IP reported 2.00.08 and 0811 answered all 42 zones). Not a client issue.
- Lost replies (issue #11, Absoluta Plus 48 B104 fw 4.30.32, ABS-IP 02.00.10.01): most 0811/0812
  requests are answered, but now and then one is only transport-ACKed and its reply never comes.
  The poll loop drops the session after MAX_UNANSWERED (3) unanswered requests with no reply in
  between (any answered request resets the count, 0.3.21) or 3 timeouts in a row of the same
  status command (a panel answering zones but never partitions still reconnects), and a multi-zone read is retried once before switching to single-zone polling.
- Absoluta Plus 48 (issue #11) answers every 0811 request with all 48 zones from zone 1
  ("01 01 01 30"), whatever range was asked: zone runs already covered by an earlier reply in the
  same poll are skipped, so a gap in the user zones does not cost an extra request.
- Poll order (0.3.19): zones (0811) first, then partitions (0812) only when due: start-up,
  request_refresh() (notifications, commands), zones settled after a change (0.3.21: the poll
  after the last zone change, so 0812 reads, and a lost 0812 waiting its timeout, do not delay
  zone reads during movement; the "ready" flag follows the zones) or every max(poll_interval, PARTITION_POLL_INTERVAL = 10 s). The ABS-IP
  notifies 0812 on alarms/tampers/faults/bypass (Usage Guide); 0210 Life Style zone notifications
  are not supported, zones can only be polled. Status requests use an adaptive timeout:
  2 x slowest of the last 50 replies, min 3 s, max APP_TIMEOUT; the retry is adaptive too, and
  after two timeouts in a row the full APP_TIMEOUT is used (a slow panel gets new samples).
- Single-zone fallback (0.3.20) only if no multi-zone request was ever answered: once one was,
  two lost replies in a row are a TimeoutError counted by the poll loop (issue #11 at 1 s
  polling: ~1 double loss every 13 h). When the ABS-IP loses a reply its own seq does not
  advance: it ACKs the request but never generates the reply (not a network loss).
  Issue #11 timings (Plus 48, ABS-IP 02.00.10.01): 0811 median 0.62 s / max 1.8 s, 0812 median
  0.98 s / max 2.5 s; lost replies never arrive late.
- One config entry per ABS-IP host: the config flow aborts on an already configured host before
  connecting (the ABS-IP accepts a single ITv2 session).
- Event log (0.3.23, issue #11): an Absoluta Plus 48 (ABS-IP 02.00.10.01) now and then answers
  0101 with 0502 0x19 "command timed out" (~2.3 s later) after hundreds of good reads. A refusal
  disables the log only if it was never read in this client's lifetime (and not for 0x19); after
  a successful read every error is transient: 3 in a row only space the reads to every 300 s.
- BOSS / mobile app taking over (0.3.24, issue #13, Absoluta 42 fw 3.60.37): the panel sends 060B,
  then refuses Open Session with command error 0x09 "system is locked out" while the other
  session is open. A user saw panel restarts ("Riavvio Programma" / BPI reset) ~30-40 s after
  such take-overs, while the client was retrying; cause not proven. The client now waits
  SESSION_ENDED_DELAY (60 s) after a 060B and SESSION_BUSY_DELAY (120 s) after each 0x09.
- Forced custom arm modes (0.3.25, issue #14, Absoluta 48 fw 4.30.25): a custom mode (0x0D..0x10)
  is refused with 0502 0x01 when open zones would need a bypass; the Bentel app asks for a
  confirmation and then arms. The Usage Guide lists "Forcing customized Arming Mode A..D" =
  0x8D..0x90: exposed as "Arm mode X (forced)" buttons, disabled by default.
- Code options (0.3.26, issue #15): `require_code` = PIN to disarm (zone bypass switches hidden);
  `require_code_arm` = PIN to arm too (arm mode buttons hidden), only used with `require_code`.
  Entries without `require_code_arm` (before 0.3.26) behave as before (code for both).
- Event log details (0.3.27, issue #11, Absoluta Plus 48): a zone alarm is logged with WHERE 0x3F
  (expander-in 2) and WHO 0x0A for zone 11: per Appendix C, with WHERE 3E..5D (expander-in),
  5E..65 (on-board zones) or 7B (zone fault) WHO is the 0-based zone, like WHERE 0 for the
  ZONE_WHO codes. When all EVENTS_READ records of a read are new, older records are read too
  (up to EVENTS_CATCHUP_MAX) until a known one, so bursts are not skipped. The integration's
  own login ("Riconosciuto Cod", e.g. WHERE 0x0B WHO 0x09 on that panel) is recognised once per
  login; older user entries with the same WHERE/WHO (previous sessions, e.g. before an HA
  restart) are hidden from last_events too.
- Partition attributes (0.3.28 / 0.3.29, issue #17): `arming_mode` / `arming_forced` (and `arming_modes` on
  the all-partitions entity) are kept while the partition is armed or arming, cleared on disarm. Sources:
  the mode of the 0900 command this client sent; for an arming started elsewhere (keypad, app) the 0232
  arming notification, which carries the type but NO partition (always 0 per the Usage Guide) and arrives
  ~0.3 s before the 0230 exit delay (verified in a log: `02 32 00 0f 01 00` then `02 30 01 04 80 00`):
  the type is assigned to the partitions whose exit delay starts within ARM_ANNOUNCE_WINDOW (3 s);
  `arming_forced` is unknown then. Otherwise only away / stay / night from the 0812 flags.
  `bypassed_zone_names` / `bypassed_zones()` = zones with the 0811 bypass bit plus zones inhibited /
  isolated per the event log (class 4 codes 0x02 / 0x03, restore removes them): the only way to see the
  zones above 16 (no 0811 status) that a forced arming excluded. Verified: forced custom C logs one
  "Zone Inhibit" per excluded zone and the matching restore on disarm. Limit: unknown after an HA
  restart while already armed (history is not replayed). `bypassed_zones` attribute is the 0812 byte-2 bit 2 flag.
- Arm mode mapping (0.3.30, issue #18): options `arm_away_as` / `arm_home_as` / `arm_night_as` choose what the
  Home Assistant Away / Home / Night arming sends: default, default forced (`mode | 0x80`), custom A-D or
  forced custom A-D (0x8D..0x90). Applies to the partition and all-partitions entities, so a forced arming is
  possible with the PIN required to arm (the forced buttons are hidden then). Not verified on a real panel
  beyond what issue #14 / #17 logs show for forced custom modes.
- Custom modes arm several partitions (0.3.31, issue #17, Absoluta 16 log 13 Nov): `0232 00 0e 01 00`
  (custom B) at 20:10:39.455, `0230` exit delay for ONE partition only (4) 0.3 s later, and the next 0812
  (1.7 s after the 0232) shows partition 8 (GAS) armed away with no exit delay. The announced mode is
  therefore applied to every partition that starts an exit delay or is first seen armed within
  ARM_ANNOUNCE_WINDOW (8 s) of the 0232. Heuristic: another partition armed by someone else in the
  same seconds would get the same mode.
- Hidden old logins (0.3.32, issue #20, Absoluta Plus 48): after an HA restart the previous session's
  "Riconosciuto Cod" is hidden from last_events but was not in `_own_login_keys`, so from the second read
  it counted as new and was fired as an event every 30 s until it left the last 5 records (~5800 events in
  15 h). The keys of every hidden login are now remembered. "Arming refused" (class 0, code 0x44) is logged
  once per open zone with WHERE 0x7C and WHO = the 0-based zone (16 records, one user): `zone` is set for it.
- Arming source (0.3.33, issue #17): `armed_from` attribute on the partitions (and per partition on the
  all-partitions entity): `home_assistant` when the 0900 was sent by this client, `panel` when the mode
  came from a 0232 (keypad, Bentel app and cloud cannot be told apart: the 0232 always has user 0 and
  method "access code"), empty when unknown (already armed when HA started) or while disarmed.
- armed_from fix (0.3.34, issue #17): for partial modes an early 0812 cleared `arming_modes` of the partitions
  we had just armed, so the following 0232/0230 marked them `panel`. The 0232 received within
  ARM_ANNOUNCE_WINDOW after our own 0900 (`_last_ha_arm`) is ours. The all-partitions entity now has a single
  `armed_from` (home_assistant / panel / mixed / None) plus `armed_from_partitions` (per partition).
- Arming partitions (0.3.35, issue #17): the all-partitions entity has `arming_partitions` (names of the
  partitions in the ARMING state: exit delay, or our 0900 accepted and not yet armed). With an HA arming of
  all partitions (partition 0) every target stays listed until the next 0812 shows which ones really armed.
- Arming flicker (0.3.36, issue #17): the entity went arming -> disarmed -> arming because an 0812 read before
  the panel starts the exit delay (0.5-4 s after the 0900) cleared `arming_requested`. It is now cleared only
  when the partition is seen armed / in exit delay, on disarm, or after ARMING_REQUEST_TTL (12 s: a partition
  that is not ready never arms). The mode in `arming_modes` is kept meanwhile.
- Disarm bouncing (0.3.37, issue #17): after an accepted disarm the client shows the partition disarmed at
  once, but an 0812 read still showing it armed (the panel is not done yet) put it back to armed with the
  old mode and origin, then the real status cleared them again (`armed_from` home_assistant -> empty ->
  home_assistant -> null). The disarm now clears mode/origin/arming request, and for DISARM_GRACE (5 s) an
  0812 that still shows that partition armed is ignored. Hypothesis from the code and the report, not yet
  confirmed with a debug log.
- Alarm records in "Last event" (0.3.38, issue #22, Absoluta 42): the event log is read every 30 s or on
  0232 / misc alarm / trouble notifications, not on a zone or partition alarm. Alarm + disarm within the same
  window were read together and the sensor, which shows the newest documented record, showed only the
  disarm (the alarm was only in `recent` and in the `log` bus event). A new partition alarm / siren / fire
  bit (0812) or a new zone alarm bit (0811) now sets `_events_due`.
- Delivery receipts (0.3.39, issue #22): two seconds after an alarm the panel logs "Push Event OK" (class 0,
  code 0x7E) and the "Last event" sensor switched to it. `INFORMATIONAL_EVENTS` (0x78 SMS sent, 0x7A event
  received OK, 0x7E push OK) are skipped by the sensor like undocumented codes; they stay in `recent` and in
  the `log` bus events. Failures (0x79, 0x7B, 0x7F) are still shown.
- Arming bus event (0.3.40, issue #17): the `arming` event carried the mode in a data key called `type`, which
  overwrote the event's own `type` ("arming") when merged in `__init__._panel_event`: automations saw
  `type: away` / `custom_b` instead of `type: arming`. The mode is now in `mode`
  (`away`, `stay`, `custom_a`..`custom_d`, `instant_stay`, `disarm`, `user`).
