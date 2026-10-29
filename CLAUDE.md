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
  The poll loop tolerates up to MAX_UNANSWERED (3) consecutive unanswered requests before dropping
  the session, and a multi-zone read is retried once before switching to single-zone polling.
- Absoluta Plus 48 (issue #11) answers every 0811 request with all 48 zones from zone 1
  ("01 01 01 30"), whatever range was asked: zone runs already covered by an earlier reply in the
  same poll are skipped, so a gap in the user zones does not cost an extra request.
- Poll order (0.3.19): zones (0811) first, then partitions (0812) only when due: start-up,
  request_refresh() (notifications, commands), a zone change in this poll (the "ready" flag
  follows the zones) or every max(poll_interval, PARTITION_POLL_INTERVAL = 10 s). The ABS-IP
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
