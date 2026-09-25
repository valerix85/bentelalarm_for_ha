"""Absoluta event log (Event Buffer Read 0101/4101) decoding.

Event descriptions come from "ITv2 Usage Guide for Absoluta" Appendix B
(Italian keypad text, English text). Event record layout (13 bytes)::

    timestamp(4, ITv2 Date Time) | flags(1) | event id(2) | event index(2) | partition mask(4)

Event id:    bits 15-12 class, bit 11 restore, bits 10-0 event code.
Event index: high byte "where/why", low byte "who" (Appendix C).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .messages import bitmask_to_list, decode_datetime

EVENT_RECORD_SIZE = 13

CLASSES = {
    0: ("Generico", "Generic"),
    1: ("Allarme", "Alarm"),
    2: ("Sabotaggio", "Tamper"),
    3: ("Guasto", "Fault"),
    4: ("Esclusione", "Bypass"),
    5: ("Test", "Test"),
}

RESTORE = ("Ripristino", "Restore")

# (class, code) -> (italiano, english)
EVENT_TEXT: dict[tuple[int, int], tuple[str, str]] = {
    (0, 0x00): ("Avvio", "Power on"),
    (0, 0x01): ("In servizio", "Service entered"),
    (0, 0x02): ("Fuori servizio", "Exit service"),
    (0, 0x05): ("Rich. Ins. Parz.", "Arm Stay Request"),
    (0, 0x06): ("Rich. Ins. Tot.", "Arm Away Request"),
    (0, 0x07): ("Rich. Ins. Inst.", "Arm Inst.Request"),
    (0, 0x08): ("Rich. Auto Parz.", "Auto Stay Requ."),
    (0, 0x09): ("Rich. Auto Tot.", "Auto Away Requ."),
    (0, 0x0A): ("Rich. Auto Inst.", "Auto Inst.Requ."),
    (0, 0x0B): ("Rich. Disinser.", "Disarm Request"),
    (0, 0x0C): ("Reset Allarmi", "Alarm reset"),
    (0, 0x0E): ("Chiave falsa", "False key"),
    (0, 0x0F): ("Rimossa Ch.falsa", "False key remove"),
    (0, 0x10): ("Chiave valida", "Valid Key"),
    (0, 0x11): ("Rimossa Ch.Valid", "Valid key remove"),
    (0, 0x12): ("Super tasto", "Super-key"),
    (0, 0x13): ("Codice NON valid", "Invalid code"),
    (0, 0x14): ("Negligenza", "Neglicence"),
    (0, 0x15): ("Riconosciuto Cod", "User entry"),
    (0, 0x16): ("Teleassist. abil", "Teleserv. Ena."),
    (0, 0x17): ("Teleassist. disa", "Teleserv. Dis."),
    (0, 0x18): ("Richiesta Teleas", "Teleserv. Requ."),
    (0, 0x19): ("Teleassist.start", "Teleserv. Start"),
    (0, 0x1A): ("Teleassist. stop", "Teleserv. End"),
    (0, 0x1B): ("Coda tel. 70%", "Tel. queue 70%"),
    (0, 0x1C): ("Coda tel. PIENA", "FULL Tel. queue"),
    (0, 0x1D): ("Uscita attivata", "Output set"),
    (0, 0x1E): ("Uscita disattiv.", "Output reset"),
    (0, 0x1F): ("Chiam. tel.fatta", "Phone call done"),
    (0, 0x20): ("Chiam. tel.iniz.", "Phone call start"),
    (0, 0x21): ("Risp. abilitato", "Answ. mach. ena."),
    (0, 0x22): ("Risp. disabil.", "Answ. mach. dis."),
    (0, 0x23): ("Cambio data/ora", "date/time change"),
    (0, 0x24): ("data/ora persa", "lost date/time"),
    (0, 0x25): ("Rich. Straord.", "Extratime requ."),
    (0, 0x26): ("Straord. inser.", "Extratime done"),
    (0, 0x27): ("Auto Ins. abilit", "Scheduler ena."),
    (0, 0x28): ("Auto Ins. disab.", "Scheduler dis."),
    (0, 0x29): ("riavvio BPI", "BPI reset"),
    (0, 0x2A): ("Avvio test zone", "Test zone start"),
    (0, 0x2B): ("Fine test zone", "Test zone end"),
    (0, 0x2C): ("Rich. cambio PIN", "PIN change requ."),
    (0, 0x2D): ("Rich. abil. PIN", "PIN enable requ."),
    (0, 0x2E): ("Rich. disab. PIN", "PIN disab. requ."),
    (0, 0x2F): ("PIN cambiato", "PIN changed"),
    (0, 0x30): ("PIN abilitato", "PIN enabled"),
    (0, 0x31): ("PIN disabilitato", "PIN disabled"),
    (0, 0x32): ("Delinquenza", "Delinquency"),
    (0, 0x33): ("Inserim. veloce", "Quick arming"),
    (0, 0x38): ("Rich.abil.chiave", "Key ena. requ."),
    (0, 0x39): ("Rich.disa.chiave", "Key dis. requ."),
    (0, 0x3A): ("Chiave abilit.", "Key enabled"),
    (0, 0x3B): ("Chiave disabilit", "Key disabled"),
    (0, 0x3C): ("Chiam. Teleass.", "Teleservice call"),
    (0, 0x3D): ("Cambio inst. PIN", "Inst.PIN changed"),
    (0, 0x3E): ("Canc. mem.eventi", "Event mem. clear"),
    (0, 0x3F): ("Rich. Ins. A", "A arming requ."),
    (0, 0x40): ("Rich. Ins. B", "B arming requ."),
    (0, 0x41): ("Rich. Ins. C", "C arming requ."),
    (0, 0x42): ("Rich. Ins. D", "D arming requ."),
    (0, 0x43): ("Rich. Ins. AUTO", "AUTO arming requ"),
    (0, 0x44): ("Inser. Rifiutato", "Arming refused"),
    (0, 0x45): ("Coda tel. canc.", "Clear tel. queue"),
    (0, 0x46): ("Evento accodato", "Queued event"),
    (0, 0x47): ("Tel. fatta", "Call executed"),
    (0, 0x48): ("Tel. fallita", "Call failed"),
    (0, 0x49): ("Straord.rifutato", "Extratime refuse"),
    (0, 0x4A): ("Forzato Inser.", "Arming forced"),
    (0, 0x4B): ("Evento custom", "Custom event"),
    (0, 0x4C): ("Ora legale/solar", "summer time"),
    (0, 0x4D): ("Inser. eseguito", "Arming OK"),
    (0, 0x4E): ("Rich. canc. coda", "Clear queue requ"),
    (0, 0x4F): ("Guasti cancel.", "Faults cleared"),
    (0, 0x50): ("Sabotaggi cancel", "Tampers cleared"),
    (0, 0x51): ("Batt. discon.", "Batt. disconnect"),
    (0, 0x52): ("Dati di fabbrica", "Factory default"),
    (0, 0x53): ("Prog.di fabbrica", "Prg.data default"),
    (0, 0x54): ("PIN di fabbrica", "PIN to default"),
    (0, 0x55): ("Rich. agg. FW", "FW upgrade req."),
    (0, 0x56): ("Agg. FW fatto", "FW upgrade done"),
    (0, 0x57): ("Rich.mod.PINinst", "Inst PIN chg.req"),
    (0, 0x58): ("PIN inst. modif.", "Inst PIN changed"),
    (0, 0x59): ("Rich. Att.Uscita", "OUTPUT ON requ."),
    (0, 0x5A): ("Rich. Dis.Uscita", "OUTPUT OFF requ."),
    (0, 0x5B): ("Rich. mod.PIN L4", "L4 PIN mod.requ."),
    (0, 0x5C): ("PIN L4 modif.", "L4 PIN modified"),
    (0, 0x5D): ("Inst. abilitato", "Inst. enabled"),
    (0, 0x5E): ("Inst. disabilit.", "Inst. disabled"),
    (0, 0x5F): ("Stop Allarmi", "Stop alarms"),
    (0, 0x60): ("Tel. Dig. Fatta", "Dig. Call exec."),
    (0, 0x61): ("Tel.Dig.Fallita", "Dig. Call failed"),
    (0, 0x62): ("Tel. No Tono", "Tel. No Tone"),
    (0, 0x63): ("Timeout Zona AND", "AND zone timeout"),
    (0, 0x64): ("Timer ON", "Timer ON"),
    (0, 0x65): ("Timer OFF", "Timer OFF"),
    (0, 0x66): ("Disins. eseguito", "Disarming exec."),
    (0, 0x67): ("Disins. rifiut.", "Disarming refus."),
    (0, 0x68): ("Evento periodico", "Periodic event"),
    (0, 0x69): ("Rich.Ins/Disins.", "Arm/Disarm requ."),
    (0, 0x6A): ("Proc.Ins.Fallita", "Arm.Proc. Failed"),
    (0, 0x6B): ("Autoins. rifiut.", "Autoarm refused"),
    (0, 0x6C): ("Sensore Forzato", "Detector forced"),
    (0, 0x6D): ("Rich.abi.chi.WLS", "WLSKey ena.requ."),
    (0, 0x6E): ("Rich.dis.chi.WLS", "WLSKey dis.requ."),
    (0, 0x6F): ("Chiave WLS abil.", "WLS Key enabled"),
    (0, 0x70): ("Chiave WLS disab", "WLS Key disabled"),
    (0, 0x71): ("N.Tel. fallito", "PhoneNum. Failed"),
    (0, 0x72): ("GSM disabilitato", "GSM disabled"),
    (0, 0x73): ("GSM abilitato", "GSM enabled"),
    (0, 0x74): ("Ev.Ric.CambioInt", "Receiv.Ev.Switch"),
    (0, 0x75): ("Rich. Scenario", "Scenario Request"),
    (0, 0x76): ("Scenario", "Scenario"),
    (0, 0x77): ("Ev. da chiamante", "Event by caller"),
    (0, 0x78): ("SMS inviato", "SMS sent"),
    (0, 0x79): ("Invio SMS fallit", "SMS sent failed"),
    (0, 0x7A): ("Ev.Ricev.", "OK                      Receiv.Ev. OK"),
    (0, 0x7B): ("Ev.Ricev. Fall.", "Receiv.Ev.Failed"),
    (0, 0x7C): ("IP disabilitato", "IP disabled"),
    (0, 0x7D): ("IP abilitato", "IP enabled"),
    (0, 0x7E): ("Evento Push OK", "Push Event OK"),
    (0, 0x7F): ("EventoPush Fall.", "PushEvent Failed"),
    (1, 0x00): ("Allarme di centr", "Panel alarm"),
    (1, 0x06): ("Allarme di area", "Partition alarm"),
    (1, 0x07): ("Allarme di zona", "Zone alarm"),
    (1, 0xF0): ("1 zona in allar.", "1 zone in alarm"),
    (2, 0x00): ("Centrale", "Panel"),
    (2, 0x01): ("Sabot. tastiera", "Keyboard tamper"),
    (2, 0x02): ("Sabot. Esp. In.", "Exp.In. tamper"),
    (2, 0x03): ("Sabot. Esp. Out.", "Exp.Out. tamper"),
    (2, 0x04): ("Sabot. Lettore", "Key reader tamp."),
    (2, 0x05): ("Sabot. Staz.Alim", "Power stat tamp."),
    (2, 0x06): ("R1", "R1"),
    (2, 0x07): ("Sabotaggio zona", "Zone tamper"),
    (2, 0x08): ("R2", "R2"),
    (2, 0x09): ("R3", "R3"),
    (2, 0x0A): ("R4", "R4"),
    (2, 0x0B): ("R5", "R5"),
    (2, 0x0C): ("R6", "R6"),
    (2, 0x0D): ("Sabot. uscita", "Output Tamper"),
    (2, 0x0E): ("Sabot. zona WLS", "WLS zone tamper"),
    (2, 0x0F): ("R7", "R7"),
    (2, 0x10): ("R8", "R8"),
    (2, 0x11): ("Sabot. ric. WLS", "WLS rec. tamper"),
    (2, 0x12): ("Linea AS", "AS line"),
    (2, 0x13): ("Centr. rimossa", "Panel removed"),
    (2, 0x14): ("Coperchio aperto", "Cover opened"),
    (2, 0x15): ("Perso Ric. WLS", "WLS rec. lost"),
    (2, 0x16): ("Persa tastiera", "Keyboard lost"),
    (2, 0x17): ("Perso Esp. In.", "Exp. In. lost"),
    (2, 0x18): ("Perso Esp. Out.", "Exp. Out. lost"),
    (2, 0x19): ("Perso lettore", "Key reader lost"),
    (2, 0x1A): ("Persa Staz. Alim", "Power stat. lost"),
    (2, 0x1B): ("Persa zona WLS", "WLS zone lost"),
    (2, 0x1C): ("KBD inval. attem", "KBD inval. attem"),
    (2, 0x1D): ("KR inval. attem", "KR inval. attem"),
    (2, 0x1E): ("Sab.sirena ester", "Ext.siren tamper"),
    (2, 0x1F): ("Sab.sirena inter", "Int.siren tamper"),
    (2, 0x20): ("Inattività", "Delinquency"),
    (3, 0x00): ("Guasto di centr.", "Panel fault"),
    (3, 0x01): ("Tastiera guasta", "keyboard fault"),
    (3, 0x02): ("Esp.In guasta", "Exp.In fault"),
    (3, 0x03): ("Esp.Out guasta", "Exp.Out fault"),
    (3, 0x04): ("Lettore guasto", "Key reader fault"),
    (3, 0x05): ("Staz.Alim guasta", "Power stat.fault"),
    (3, 0x06): ("Guasto di area", "Partition fault"),
    (3, 0x07): ("Guasto di zona", "Zone fault"),
    (3, 0x0A): ("Chiave guasta", "Key fault"),
    (3, 0x0B): ("Chi. WLS guasta", "WLS key fault"),
    (3, 0x0D): ("Uscita guasta", "Output fault"),
    (3, 0x0E): ("Zona WLS guasta", "WLS zone fault"),
    (3, 0x0F): ("Zona WLS bat.bas", "WLS zone bat.low"),
    (3, 0x10): ("Chi. WLS bat.bas", "WLS key bat.low"),
    (3, 0x11): ("Ric. WLS guasto", "WLS rec. fault"),
    (3, 0x12): ("Tel.telass. fal.", "Teles.call fail"),
    (3, 0x13): ("Linea tel.guasta", "Tel. line fault"),
    (3, 0x15): ("Chiam. tel. fall", "Phone call fail"),
    (3, 0x16): ("Cent. bat. bassa", "Panel bat. low"),
    (3, 0x17): ("Cent. bat. ineff", "Panel bat. fail"),
    (3, 0x18): ("Cent.NO batteria", "Panel NO batt."),
    (3, 0x19): ("Cent. caricabat.", "Panel bat.charg"),
    (3, 0x1A): ("Cent. NO 220v", "Panel NO 220v"),
    (3, 0x1B): ("Cent. Alim. guas", "Panel PSU fault"),
    (3, 0x1C): ("Cent. bassa tens", "Panel low Vout"),
    (3, 0x1D): ("Alim1 bat. bassa", "PS1 bat. low"),
    (3, 0x1E): ("Alim1 bat. ineff", "PS1 bat. fail"),
    (3, 0x1F): ("Alim1 NO batt.", "PS1 NO batt."),
    (3, 0x20): ("Alim1 caricabat.", "PS1 bat.charg"),
    (3, 0x21): ("Alim1 NO 220v", "PS1 NO 220v"),
    (3, 0x22): ("Alim1 Alim. guas", "PS1 PSU fault"),
    (3, 0x23): ("Alim1 bassa tens", "PS1 low Vout"),
    (3, 0x24): ("Alim1 bat. disc.", "PS1 bat. disc."),
    (3, 0x25): ("Alim1 SWT disc.", "PS1 SWT disc."),
    (3, 0x26): ("Alim1 Vout1 CC", "PS1 Vout1 short"),
    (3, 0x27): ("Alim1 Vout2 CC", "PS1 Vout2 short"),
    (3, 0x28): ("Alim1 Vout3 CC", "PS1 Vout3 short"),
    (3, 0x29): ("Alim2 bat. bassa", "PS2 bat. low"),
    (3, 0x2A): ("Alim2 bat. ineff", "PS2 bat. fail"),
    (3, 0x2B): ("Alim2 NO batt.", "PS2 NO batt."),
    (3, 0x2C): ("Alim2 caricabat.", "PS2 bat.charg"),
    (3, 0x2D): ("Alim2 NO 220v", "PS2 NO 220v"),
    (3, 0x2E): ("Alim2 Alim. guas", "PS2 PSU fault"),
    (3, 0x2F): ("Alim2 bassa tens", "PS2 low Vout"),
    (3, 0x30): ("Alim2 bat. disc.", "PS2 bat. disc."),
    (3, 0x31): ("Alim2 SWT disc.", "PS2 SWT disc."),
    (3, 0x32): ("Alim2 Vout1 CC", "PS2 Vout1 short"),
    (3, 0x33): ("Alim2 Vout2 CC", "PS2 Vout2 short"),
    (3, 0x34): ("Alim2 Vout3 CC", "PS2 Vout3 short"),
    (3, 0x35): ("Alim3 bat. bassa", "PS3 bat. low"),
    (3, 0x36): ("Alim3 bat. ineff", "PS3 bat. fail"),
    (3, 0x37): ("Alim3 NO batt.", "PS3 NO batt."),
    (3, 0x38): ("Alim3 caricabat.", "PS3 bat.charg"),
    (3, 0x39): ("Alim3 NO 220v", "PS3 NO 220v"),
    (3, 0x3A): ("Alim3 Alim. guas", "PS3 PSU fault"),
    (3, 0x3B): ("Alim3 bassa tens", "PS3 low Vout"),
    (3, 0x3C): ("Alim3 bat. disc.", "PS3 bat. disc."),
    (3, 0x3D): ("Alim3 SWT disc.", "PS3 SWT disc."),
    (3, 0x3E): ("Alim3 Vout1 CC", "PS3 Vout1 short"),
    (3, 0x3F): ("Alim3 Vout2 CC", "PS3 Vout2 short"),
    (3, 0x40): ("Alim3 Vout3 CC", "PS3 Vout3 short"),
    (3, 0x41): ("Alim4 bat. bassa", "PS4 bat. low"),
    (3, 0x42): ("Alim4 bat. ineff", "PS4 bat. fail"),
    (3, 0x43): ("Alim4 NO batt.", "PS4 NO batt."),
    (3, 0x44): ("Alim4 caricabat.", "PS4 bat.charg"),
    (3, 0x45): ("Alim4 NO 220v", "PS4 NO 220v"),
    (3, 0x46): ("Alim4 Alim. guas", "PS4 PSU fault"),
    (3, 0x47): ("Alim4 bassa tens", "PS4 low Vout"),
    (3, 0x48): ("Alim4 bat. disc.", "PS4 bat. disc."),
    (3, 0x49): ("Alim4 SWT disc.", "PS4 SWT disc."),
    (3, 0x4A): ("Alim4 Vout1 CC", "PS4 Vout1 short"),
    (3, 0x4B): ("Alim4 Vout2 CC", "PS4 Vout2 short"),
    (3, 0x4C): ("Alim4 Vout3 CC", "PS4 Vout3 short"),
    (3, 0x4D): ("Cambio ora leg.", "summer time"),
    (3, 0x4E): ("Fus. B aperto", "Fuse B fail"),
    (3, 0x4F): ("Fus. Zone aperto", "Fuse zones fail"),
    (3, 0x50): ("Fus. BPI aperto", "Fuse BPI fail"),
    (3, 0x51): ("Fus. Kbus aperto", "Fuse Kbus fail"),
    (3, 0x53): ("Manuten. Instal.", "Inst. Maintenan."),
    (3, 0x54): ("Manuten. Vigil.", "Surv.Maintenan."),
    (3, 0x55): ("Perdita Datario", "Date/time lost"),
    (3, 0x56): ("Dati Prog. modif", "Prog.data change"),
    (3, 0x57): ("Inattività", "Delinquency"),
    (3, 0x58): ("PIN duplicato", "Duplicated PIN"),
    (3, 0x59): ("Gua Linea Telef.", "Tel. Line fault"),
    (3, 0x5A): ("Com. Tel. fallit", "Tel. comm. FTC"),
    (3, 0x5B): ("Conn. Sirena Gua", "Siren Conn. fail"),
    (3, 0x5C): ("Ric. WLS Guasto", "WLS rec. fail"),
    (3, 0x5D): ("Com. IP guasta", "IP Com. fail"),
    (3, 0x5E): ("Rete IP guasta", "IP Net. fail"),
    (3, 0x5F): ("Com. fallita IP", "IP Remote Server"),
    (3, 0x60): ("Com. GSM guasto", "GSM Com. faulty"),
    (3, 0x61): ("Rete GSM guasta", "GSM Net fail"),
    (3, 0x62): ("FW incompat.", "FW mismatch"),
    (3, 0x64): ("Gua. Sirena Est.", "Ext. Siren fault"),
    (3, 0x65): ("Gua. Sirena Int.", "Int. Siren fault"),
    (3, 0x66): ("RiavvioProgramma", "Program Restart"),
    (3, 0x67): ("PIN di fabbrica", "PIN to default"),
    (3, 0x68): ("Problemi su BPI", "BPI bus trouble"),
    (3, 0x69): ("Aggiorn. Fallito", "Upgrade Failed"),
    (3, 0x6C): ("Rete Dati Persa", "Lost DataNetwork"),
    (3, 0x6D): ("Ricev.Prim.Perso", "Main Receiv.Lost"),
    (3, 0x6E): ("Ricev.Sec. Perso", "2nd Receiv. Lost"),
    (4, 0x00): ("Esclusa zone", "Zone bypassed"),
    (4, 0x01): ("Inclusa zona", "Zone un-bypassed"),
    (4, 0x02): ("Inibita zona", "Zone Inhibit"),
    (4, 0x03): ("Isolata zona", "Zone Isolated"),
    (4, 0x04): ("Inibita tastiera", "KBD inhibited"),
    (4, 0x05): ("Inibito lettore", "Key reader inhib"),
    (4, 0x06): ("Rich. inib. zona", "Zone inhib req."),
    (4, 0x07): ("Rich. isol. zona", "Zone isol. req."),
    (5, 0x00): ("Centr. in prova", "Panel in test"),
    (5, 0x01): ("prova all. zona", "zone test alarm"),
    (5, 0x02): ("prova circ.apert", "zone open test"),
    (5, 0x03): ("prova corto circ", "zone short test"),
    (5, 0x04): ("Prova zona persa", "zone lost test"),
    (5, 0x05): ("Prova bat. zona", "zone bat.low tst"),
}

# (class, code) whose "who" is a zone number when "where" is 0 (Appendix C, table 9)
ZONE_WHO = {
    (1, 0x07),
    (1, 0x20),
    (1, 0xF0),
    (2, 0x07),
    (2, 0x0E),
    (2, 0x1B),
    (2, 0x20),
    (3, 0x07),
    (3, 0x0E),
    (3, 0x20),
    (4, 0x00),
    (4, 0x01),
    (4, 0x02),
    (4, 0x03),
    (5, 0x01),
    (5, 0x02),
    (5, 0x03),
    (5, 0x04),
    (5, 0x05),
    (0, 0x6C),
}
PARTITION_WHO = {(1, 0x06), (2, 0x06), (3, 0x06)}


@dataclass(slots=True, frozen=True)
class PanelEvent:
    timestamp: dt.datetime | None
    event_id: int
    where: int
    who: int
    partitions: tuple[int, ...]
    raw: bytes

    @property
    def cls(self) -> int:
        return self.event_id >> 12

    @property
    def restore(self) -> bool:
        return bool(self.event_id & 0x0800)

    @property
    def code(self) -> int:
        return self.event_id & 0x07FF

    @property
    def zone(self) -> int | None:
        """Zone number the event refers to (None when not a zone event).

        Assumes WHO is the 1-based zone number, as in the WLS zone mapping of
        Appendix C (Wireless Zone Label [WHO - 0F]).
        """
        if self.where == 0 and (self.cls, self.code) in ZONE_WHO and self.who not in (0, 0xFF):
            return self.who
        return None

    @property
    def partition(self) -> int | None:
        if self.where == 0 and (self.cls, self.code) in PARTITION_WHO and self.who not in (0, 0xFF):
            return self.who
        return None

    def text(self, italian: bool = True) -> str:
        idx = 0 if italian else 1
        base = EVENT_TEXT.get((self.cls, self.code))
        if base is None:
            cls_name = CLASSES.get(self.cls, ("Evento", "Event"))[idx]
            base_text = f"{cls_name} 0x{self.code:02X}"
        else:
            base_text = base[idx]
        if self.restore:
            base_text = f"{RESTORE[idx]}: {base_text}"
        return base_text

    @property
    def key(self) -> bytes:
        """Identity of the record (used to detect new events)."""
        return self.raw


def parse_event(rec: bytes) -> PanelEvent:
    if len(rec) < EVENT_RECORD_SIZE:
        raise ValueError("event record too short")
    mask = rec[9:13]
    # fixed length partition mask, only the last 2 bytes are significant:
    # byte 3 = partitions 1..8, byte 2 = partitions 9..16
    parts = tuple(bitmask_to_list(bytes([mask[3], mask[2]])))
    return PanelEvent(
        timestamp=decode_datetime(rec[0:4]),
        event_id=(rec[5] << 8) | rec[6],
        where=rec[7],
        who=rec[8],
        partitions=parts,
        raw=bytes(rec[:EVENT_RECORD_SIZE]),
    )


def parse_event_buffer_response(p: bytes) -> tuple[int, list[PanelEvent]]:
    """4101: buffer id(1), event number(2), number of events(2), records."""
    if len(p) < 5:
        raise ValueError("event buffer response too short")
    first = (p[1] << 8) | p[2]
    count = (p[3] << 8) | p[4]
    events = []
    off = 5
    for _ in range(count):
        rec = p[off : off + EVENT_RECORD_SIZE]
        if len(rec) < EVENT_RECORD_SIZE:
            break
        events.append(parse_event(rec))
        off += EVENT_RECORD_SIZE
    return first, events
