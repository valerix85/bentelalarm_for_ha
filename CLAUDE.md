# Note per Claude Code

Integrazione Home Assistant per centrali Bentel Absoluta via ABS-IP, protocollo ITv2 su TCP.

## Struttura
- `custom_components/bentel_absoluta/itv2/`: libreria protocollo pura (nessun import di HA).
- Piattaforme HA: `alarm_control_panel`, `binary_sensor`, `switch`, `button`; `config_flow.py`.
- `tests/fake_panel.py` simula la centrale: ogni nuovo comando va aggiunto anche lì e coperto
  da un test. Eseguire `pytest` (richiede `pytest-homeassistant-custom-component`, Python 3.13).

## Fatti di protocollo verificati (non "correggerli")
- Frame: `7E | escape(LEN SEQ RSEQ CMD[2] [APPSEQ] DATI CRC_HI CRC_LO) | 7F`.
  Escape: 7D→7D 00, 7E→7D 01, 7F→7D 02 (NON xor 0x20).
- LEN conta SEQ, RSEQ, dati e i 2 byte di CRC (ACK semplice = LEN 4). CRC-16/CCITT-FALSE
  (poly 0x1021, init 0xFFFF) calcolato su LEN + contenuto.
- Sequenze: il primo pacchetto ha SEQ 0, poi 1..255 e si riparte da 1. Ogni pacchetto non vuoto
  va confermato (ACK semplice con SEQ invariato e RSEQ = seq ricevuto).
- Handshake: 060A ↔ 060A, 060E ↔ 060E (con 0502 a ogni comando con app-seq), 060D ↔ 060D,
  poi login 0400 con PIN BCD riempito a 0xA ("1234" → AA 12 34). Nessuna cifratura.
- Stato area 0812, byte 1: **bit0 = inserita**; se inserita bit1 stay, bit2 away, bit3 night,
  bit4 senza ritardo ingresso, bit5 tempo uscita, bit6 tempo ingresso; se disinserita bit1 pronta.
  La tabella del PDF è impaginata da destra: non usare bit7 come "inserita".
- Stato zona 0811: bit0 aperta, 1 sabotaggio, 2 guasto, 3 batteria, 4 inattività, 5 allarme,
  6 memoria, 7 esclusa. Le zone NON sono notificate: vanno lette in polling.
- Alcune centrali non rispondono a letture multi-zona: il client passa a letture singole.
- Uscite 1..50, comandi remoti = uscita 56 + n. Etichette via 0800/0771 in Windows-1252.
- 0771 (verificato su Absoluta 16 fw 3.60.37): il campo "data length" è la lunghezza TOTALE del
  blocco richiesto (8 etichette -> 0x80), non della singola etichetta. Il parser gestisce entrambi.
- NON filtrare le zone con "max zones" di 0613: una Absoluta 16 (fw 3.60.37) ha zone radio
  17, 18, 20 configurate. La maschera 0770 riflette le zone abilitate (la 19 disabilitata non c'è).
  Le zone che la centrale rifiuta o non riporta vengono scartate dopo averle lette singolarmente;
  se una risposta multi-zona è troncata, le zone mancanti vengono lette una per una a ogni poll.
- L'etichetta di sistema (0771 opzione 3, offset 1) è il testo salvaschermo della tastiera:
  non usarla come nome del dispositivo.
- Esclusione zona 074A: Absoluta la applica solo al logout (0401), e dopo il logout l'ABS-IP
  CHIUDE la connessione TCP (verificato fw 3.60.37): si fa una riconnessione immediata "pianificata"
  senza mostrare le entità come non disponibili.
- Etichette: la centrale può rifiutare un blocco (es. zone >16 su Absoluta 16); ogni blocco è
  indipendente e in caso di rifiuto si ritenta elemento per elemento.
- Stato zone oltre max_zones (0613): su Absoluta 16 fw 3.60.37 una richiesta 0811 per la zona 17
  (o 18, 20) riceve comunque la risposta con le zone 1..16. Lo stato delle zone >16 NON è
  disponibile via ITv2 (le etichette sì). Non è un bug del client.
- Registro eventi 0101/4101: record da 13 byte = data(4) flags(1) event id(2: classe<<12 |
  ripristino<<11 | codice) indice(2: where, who) maschera aree(4, contano gli ultimi 2 byte).
  Verificato sugli esempi della guida. DA VERIFICARE su centrale reale: WHO = numero zona 1-based
  per gli eventi di zona (ipotesi da Appendice C).
- Zone per area: 0800 -> 0770 con area != 0 (fw >= 3.50.80). Se non risponde si usa l'elenco globale.
- Ora centrale: 0741 con data/ora ITv2 in ora locale.
