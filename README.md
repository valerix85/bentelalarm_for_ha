# Bentel Absoluta per Home Assistant

Integrazione personalizzata per Home Assistant che si collega **localmente** alla centrale
**Bentel Absoluta** tramite il modulo **ABS-IP**, usando il protocollo **ITv2** su TCP
(nessun cloud, nessun bridge MQTT).

> Richiede che sull'ABS-IP sia abilitato il protocollo ITv2 (porta TCP predefinita **3064**,
> cifratura disabilitata) e il PIN di un utente Master, Normale o Limitato.

## Funzionalità

| Piattaforma | Cosa espone |
|---|---|
| `alarm_control_panel` | Un'entità per ogni **area** assegnata all'utente: di default solo **inserimento totale** ("Fuori casa") e disinserimento; opzionalmente anche Parziale ("In casa" = *stay*) e Notte (= *stay istantaneo*). Stati `arming` (tempo di uscita), `pending` (tempo di ingresso), `triggered`. |
| `binary_sensor` | Una per ogni **zona** (aperta/chiusa, con attributi allarme, memoria, sabotaggio, guasto, batteria bassa, esclusa); per ogni area *guasti* e *pronta*; stato della **connessione**. |
| `switch` | Le **uscite programmabili** abilitate per l'utente e l'**esclusione** di ogni zona ("Esclusione Divano"…). L'esclusione viene applicata dalla centrale al logout, quindi l'integrazione fa logout e nuovo login in automatico (qualche secondo). Non creati se è attiva l'opzione *Richiedi il codice*. |
| `button` | I **comandi remoti**, le **modalità di inserimento A-D** (globali), *cancella memoria allarmi*, *cancella allarmi/guasti/sabotaggi*. |
| Eventi | `bentel_absoluta_event` con `type`: `arming`, `blocking_condition` (es. mancanza rete che impedisce l'inserimento), `trouble`, `arming_pre_alert`. |
| Diagnostica | Download dalla pagina del dispositivo (PIN oscurato). |

I nomi di aree, zone, uscite e modalità di inserimento vengono letti dalla centrale.

## Installazione

**HACS** (consigliato): *HACS → Integrazioni → ⋮ → Repository personalizzati* →
`https://github.com/valerix85/bentelalarm_for_ha`, categoria *Integrazione*, poi installa
*Bentel Absoluta* e riavvia Home Assistant.

**Manuale**: copia `custom_components/bentel_absoluta/` nella cartella
`<config>/custom_components/` e riavvia.

Poi *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Bentel Absoluta* e inserisci
IP dell'ABS-IP, porta e PIN utente.

### Opzioni

- **Intervallo di lettura dello stato** (default 5 s): l'ABS-IP *non* notifica spontaneamente
  l'apertura/chiusura delle zone, quindi vengono lette periodicamente. Lo stesso polling fa da
  keep-alive raccomandato dalla guida Bentel.
- **Modalità di inserimento proposte** (default: solo *Fuori casa* = inserimento totale): aggiungi
  *In casa* (parziale) e *Notte* (parziale istantaneo) solo se le usi sulla centrale.
  I nomi "Fuori casa / In casa / Notte" sono quelli standard di Home Assistant.
- **Richiedi il codice**: se attivo, le entità allarme chiedono il PIN per inserire/disinserire
  e i pulsanti delle modalità A-D non vengono creati.

## Cose da sapere

- L'ABS-IP accetta **una sola connessione ITv2** alla volta.
- La sessione ITv2 ha la **priorità più bassa**: quando si collega BOSS o l'app mobile la
  centrale la chiude. L'integrazione si ricollega da sola (back-off da 10 s a 5 min).
- Vengono esposte solo le aree/zone/uscite assegnate all'utente del PIN configurato.
- La cifratura AES dell'ABS-IP non è supportata: lasciala disabilitata per il client ITv2.

## Limitazioni note

- **Stato zone oltre il limite del modello**: la centrale dichiara via ITv2 un numero massimo di
  zone (es. 16 su Absoluta 16). Anche se da BOSS sono configurate più zone (es. radio 17-20),
  l'ABS-IP restituisce lo stato solo delle prime N: le altre non vengono create (il motivo è
  visibile nella diagnostica, voce `invalid_zone_reasons`). Soluzione: usare per i sensori
  importanti gli slot entro il limite.
- **Uscite**: sono esposte solo le uscite *riservate* all'area con un'azione programmata
  (è la centrale a decidere quali rendere disponibili a ITv2).
- **Esclusione zone**: la centrale la applica al logout e poi chiude la sessione; l'integrazione
  si ricollega da sola, per cui ogni esclusione richiede qualche secondo.
- **Una sola connessione ITv2** e priorità più bassa di BOSS/app (vedi sopra).

## Debug

```yaml
logger:
  default: warning
  logs:
    custom_components.bentel_absoluta: debug
```

In debug vengono registrati tutti i pacchetti trasmessi/ricevuti (`TX`/`RX`) in esadecimale:
allegali alle issue insieme al file di diagnostica.

## Sviluppo

```
custom_components/bentel_absoluta/
├── itv2/            # libreria protocollo, senza dipendenze da Home Assistant
│   ├── framing.py   # 0x7E/0x7F, escape 7D 00/01/02, lunghezza, CRC-16/CCITT-FALSE
│   ├── messages.py  # codifica/decodifica dei comandi usati da Absoluta
│   └── client.py    # sessione asyncio: sequenze/ACK, handshake, login, polling, comandi
├── alarm_control_panel.py, binary_sensor.py, switch.py, button.py
└── config_flow.py   # setup, reauth, riconfigurazione, opzioni
tests/
├── fake_panel.py    # simulatore di centrale Absoluta (server TCP ITv2)
├── test_itv2.py     # test del protocollo
└── test_integration.py  # test in Home Assistant reale
```

```bash
pip install pytest-homeassistant-custom-component
pytest
```

Riferimenti: *Interactive Protocol V2.00 R2.03* e *ITv2 Usage Guide for Absoluta Rev 1.05*
(Tyco / Bentel Security). Formati e sequenza di sessione sono stati verificati anche
confrontandoli con il bridge Java open source
[mostorer/bentel-absoluta-local](https://github.com/mostorer/bentel-absoluta-local).

### Claude Code

Nelle issue e nelle pull request si può scrivere `@claude` per far intervenire
[Claude Code](https://github.com/anthropics/claude-code-action) (workflow
`.github/workflows/claude.yml`).

<details>
<summary>Setup del workflow Claude con GitHub App personalizzata</summary>

1. Crea una GitHub App (*Settings → Developer settings → GitHub Apps*) con permessi di
   repository **Contents**, **Issues**, **Pull requests** in *Read & write*.
2. Genera una *private key* (`.pem`) e installa la App su questo repository.
3. In *Settings → Secrets and variables → Actions* aggiungi: `APP_ID`, `APP_PRIVATE_KEY`
   (contenuto del `.pem`) e `ANTHROPIC_API_KEY`.

Guida completa: <https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md>
</details>

## Contributi

Issue e pull request sono benvenute: <https://github.com/valerix85/bentelalarm_for_ha>
