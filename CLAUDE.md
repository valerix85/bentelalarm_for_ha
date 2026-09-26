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
  over ITv2 (labels are). This is not a client bug.
- Event log 0101/4101: 13-byte records = timestamp(4) flags(1) event id(2: class<<12 |
  restore<<11 | code) index(2: where, who) partition mask(4, only the last 2 bytes matter).
  Verified against the guide's examples. In zone events WHO is the 0-based zone index
  (verified on Absoluta 16 fw 3.60: bypassing zone 6 -> WHO 5). A bypass done via ITv2 (074A)
  is logged as "Isolata zona" / "Zone Isolated" (class 4, code 0x03); removing it logs the restore
  of that event plus class 0 code 0x0D, which the guide leaves blank: the "Last event" sensor
  skips undocumented codes.
- Absoluta Plus 48 fw 4.30.35 (user report): all 48 zones answer 0811 normally, but a chime
  zone and a "real time" zone were missing from the user's 0770 mask (probably no partition)
  while their status is readable: exposed via the "extra_zones" option (no bypass switch).
- Zones per partition: 0800 -> 0770 with partition != 0 (fw >= 3.50.80). If unanswered the
  global list is used.
- Panel clock: 0741 with ITv2 date/time in local time.
- Every integration login (including the reconnect after a bypass) is logged by the panel as
  "Riconosciuto Cod" (class 0, code 0x15): the client recognises it (one per login, the most
  recent) and neither shows nor fires it, otherwise it would hide the interesting event.
