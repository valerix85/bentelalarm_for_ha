# Bentel Absoluta per Home Assistant

Integrazione personalizzata per Home Assistant che consente di interfacciarsi con la centrale di allarme **Bentel Absoluta** tramite il protocollo **ITv2** su TCP.

> ⚠️ Richiede che la centrale sia configurata per **connessione TCP/IP (porta 3064)** con **protocollo interattivo ITv2** abilitato.

---

## 🔧 Funzionalità supportate

- 🔐 **Arm/Disarm** delle partizioni tramite `alarm_control_panel`
- 🚨 **Zone attive** come `binary_sensor`
- 🔌 **Controllo uscite** via `switch`
- 📟 **Lettura firmware** via `sensor`
- 🔑 **Crittografia AES-128 ECB** (opzionale, con chiave nulla)
- 📶 Comunicazione diretta con protocollo ITv2 conforme alla guida ufficiale Bentel

---

## 📦 Installazione

1. Copia la cartella `bentel_absoluta/` in: <config>/custom_components/

2. Riavvia Home Assistant.

3. Vai in **Impostazioni → Dispositivi e servizi → Aggiungi Integrazione**, cerca `Bentel Absoluta`.

---

## 🧠 Requisiti della centrale

- Porta **TCP 3064** abilitata
- **Protocollo PC-Link/ITv2** attivo
- Nessuna crittografia (oppure chiave AES nulla)
- Centrale con firmware compatibile con il protocollo ITv2 (≥ versione 1.0)

---

## ⚙️ Configurazione

Durante la configurazione tramite UI ti verranno richiesti:

- **Indirizzo IP** della centrale
- **Porta TCP** (default: 3064)

L'integrazione stabilisce automaticamente la sessione con `Open Session (0x060A)` e `Request Access (0x060E)`.

---

## 🧪 Debug & sviluppo

Per attivare il logging dettagliato, aggiungi in `configuration.yaml`:

```yaml
logger:
default: warning
logs:
 custom_components.bentel_absoluta: debug
```

---

## 📚 Documentazione tecnica
Questo custom component implementa fedelmente:

Il protocollo ITv2 Usage Guide for Absoluta Rev 1.05

Comandi come 0x060A, 0x060E, 0x060D, 0x0812, 0x0900, 0x0901, 0x0902, ecc.

Framing 0x7E / 0x7F, escaping 0x7D, CRC-CCITT, gestione sequenza

---

## 🤝 Collaborazioni e pull request
Questo progetto è attivamente sviluppato per uso professionale. Contributi e miglioramenti sono benvenuti su:

📎 https://github.com/valerix85/bentelalarm_for_ha

---
