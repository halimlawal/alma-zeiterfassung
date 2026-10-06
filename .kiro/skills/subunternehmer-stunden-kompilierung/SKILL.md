---
name: subunternehmer-stunden-kompilierung
description: Kompiliert Subunternehmer-Arbeitsstunden aus WhatsApp-Gruppennachrichten in strukturierte deutsche Wochenberichte für die Kundenabrechnung. Verwenden für wöchentliche Zeiterfassung, Verarbeitung von Auftragnehmerstunden oder Erstellung von Abrechnungsdokumenten.
---

## Subunternehmer-Stunden-Kompilierungssystem

### Zweck
Liest WhatsApp-Nachrichten aus konfigurierten Subunternehmer-Gruppen, parst Arbeitszeitangaben automatisch und erzeugt strukturierte `.txt`-Berichte pro Auftrag im deutschen Rechnungsformat. Anomalien (Fehler in Stundenangaben, fehlende Daten, Rechenfehler) werden direkt im Bericht markiert und per WhatsApp gemeldet.

---

### Einstiegspunkt

```bash
cd .kiro/skills/subunternehmer-stunden-kompilierung/scripts

# Alle aktiven Gruppen verarbeiten (nutzt Checkpoint aus config.json)
python3 whatsapp_integration.py

# Nur eine bestimmte Gruppe
python3 whatsapp_integration.py --gruppe "Adam Sub & Alma"

# Ab einem bestimmten Datum (überschreibt Checkpoint)
python3 whatsapp_integration.py --seit 2026-09-20

# Parsen ohne Speichern (zum Testen)
python3 whatsapp_integration.py --dry-run
```

---

### Dateistruktur

```
.kiro/skills/subunternehmer-stunden-kompilierung/
├── SKILL.md                        ← diese Datei
├── config.json                     ← Gruppen, Kontakte, Checkpoints, JIDs
├── test_cases.txt                  ← 7 Testfälle für Parser-Validierung
└── scripts/
    ├── message_parser.py           ← Deutschen WhatsApp-Text → Arbeitseintrag
    ├── report_generator.py         ← Arbeitseintrag → .txt-Bericht
    └── whatsapp_integration.py     ← Hauptprogramm: Bridge → Parser → Berichte → Notify

berichte/                           ← generierte Berichte (in .gitignore)
└── 2026/
    └── Subunternehmer/
        ├── KW-38/
        │   └── 19-09-bis-25-09-Bad-Tölz.txt
        └── KW-39/
            ├── 26-09-bis-02-10-Bad-Tölz.txt
            └── 26-09-bis-02-10-Simbach.txt
```

---

### config.json – Struktur

```json
{
  "version": "1.3",
  "benachrichtigungs_nummer": "49XXXXXXXXXX",
  "whatsapp_gruppen": [
    {
      "gruppenname": "Subunternehmer",
      "aktiv": true,
      "chat_jid": "120363...@g.us",
      "kontakte": ["Max", "Subunternehmer", "49XXXXXXXXXX"],
      "letzter_bericht_datum": "2026-10-02",
      "letzter_kw_bericht": "berichte/2026/Subunternehmer/KW-39"
    }
  ],
  "einstellungen": {
    "ausgabe_verzeichnis": "berichte",
    "wochen_beginn": "samstag",
    "max_nachrichten_pro_abruf": 3000,
    "verbindungs_versuche": 5
  }
}
```

**Wichtige Felder:**
- `kontakte` — Pflicht-Whitelist. Leere Liste = keine Nachrichten werden verarbeitet (Sicherheit).
- `chat_jid` — Chat-JID der WhatsApp-Gruppe. Wird beim ersten Lauf automatisch ermittelt und gespeichert. Ermöglicht serverseitige Filterung — nur Nachrichten dieser Gruppe verlassen den Bridge-Prozess.
- `letzter_bericht_datum` — Checkpoint. Nächster Lauf verarbeitet nur Nachrichten nach diesem Datum.
- `letzter_kw_bericht` — Relativer Pfad zum zuletzt generierten KW-Ordner.
- `benachrichtigungs_nummer` — Deine WhatsApp-Nummer (z.B. `4915218682585`). Nach jedem Lauf wird pro Auftrag eine Nachricht + eine Zusammenfassung gesendet.
- Nicht gespeicherte Kontakte erscheinen in der Bridge als Telefonnummer (z.B. `49XXXXXXXXXX`), nicht als `~Name`.

---

### Unterstützte Nachrichtenformate

**Einfach (1 Person):**
```
📍 Bad Tölz  28.09.26
Arbeitsbeginn: 07:00–17:00 Uhr
Pause: 12:00–12:30
Insgesamt: 9,5 Std.
```

**Mehrere Pausen:**
```
📍 Bad Tölz  24.09.26
Arbeitsbeginn: 07:00–17:00 Uhr
Pause: 09:00–09:30
Pause: 12:00–12:30
Insgesamt: 9 Std.
```

**Mehrere Personen mit unterschiedlichen Pausen:**
```
📍 Bad Tölz  24.09.26
Arbeitsbeginn: 07:00–17:00 Uhr

3 Personen
Pause: 10:00–10:30
Pause: 12:00–12:30
3×9=27

1 Person
Pause: 10:00–10:30
1×9,5=9,5

Insgesamt: 36,5 Std.
```

**Mehrere Projekte am gleichen Tag → als separate Nachrichten schicken:**
```
📍 Bad Tölz  28.09.26
Arbeitsbeginn: 07:00–17:00 Uhr
Pause: 11:00–12:00
Insgesamt: 9 Std.
```
```
📍 Simbach  28.09.26
Arbeitsbeginn: 08:00–16:40 Uhr
Pause: keine
Insgesamt: 8:40
```

**Parser-Robustheit:**
- Datum: `28.9.26`, `28.09.2026`, `28/09/26` — alle erkannt
- Zeit: `07:00`, `07.00`, `7-17` — alle erkannt
- Tippfehler: `Ingesamt`, `ingesamt` — erkannt
- Berechnungen: `3*9=27`, `3×9,5=28,5` — erkannt

---

### Anomalie-Erkennung

Folgende Probleme werden 🔴/🟡/🔵 im Bericht markiert und in der WhatsApp-Zusammenfassung gemeldet:

| Schweregrad | Typ | Beispiel |
|-------------|-----|---------|
| 🔴 KRITISCH | Fehlendes Datum | Nachricht ohne Datumsangabe |
| 🔴 KRITISCH | Ungültiges Zeitformat | `25:00`, `8:70` |
| 🔴 KRITISCH | Ungültiges Datum | `32.13.2026`, `30.02.2026` |
| 🔴 KRITISCH | Pause vor Start-/Endzeit | Pause 06:00 wenn Arbeit ab 07:00 |
| 🔴 KRITISCH | Duplikateintrag | Gleiche Datum + Projekt + Zeiten |
| 🟡 WARNUNG | Stundenabweichung | Angegebene 9h ≠ berechnete 9,5h (berechneter Wert wird verwendet) |
| 🟡 WARNUNG | Überlange Schicht | Netto > 12 Stunden (nur bei Einzelgruppe) |
| 🟡 WARNUNG | Pausen überlappen | `11:00–12:00` und `11:30–12:30` in derselben Gruppe |
| 🟡 WARNUNG | Pausendauer > Schicht | Pausen länger als Arbeitszeit |
| 🟡 WARNUNG | Rechenfehler | `3×8=25` statt `24` |
| 🟡 WARNUNG | Zu viele Mitarbeiter | Mehr als 15 Personen |
| 🔵 FEHLER | Fehlender Projektname | Auftrag nicht erkennbar |
| 🔵 FEHLER | Fehlende Startzeit | Nur Endzeit vorhanden |

**Berechnungskorrektur:** Wenn der Subunternehmer `Insgesamt 9` angibt, die Berechnung aus Start–Ende–Pausen jedoch `9,5h` ergibt, wird automatisch der **berechnete Wert** verwendet und eine Warnung angezeigt.

---

### Berichtsformat

Berichte entsprechen exakt der `template.txt`-Vorlage:

```
-------------------------------------------------
Arbeitsstunden Übersicht der Woche  22.09 - 28.09
Auftrag: Bad Tölz
-------------------------------------------------

Dienstag, 22.09.2026

Arbeitszeit: 08:00–18:00 Uhr
Leistung: Holz sowie Plastik von Wänden entfernen
Pausen: 09:00–09:30 Uhr und 12:00–12:30 Uhr

Einsatz: 3 Mitarbeiter
Arbeitszeit nach Abzug der Pausen:
3 Mitarbeiter × 9 Stunden = 27 Arbeitsstunden

Gesamt 22.09.2026: 27 Arbeitsstunden
```

- Stunden in Industriezeit (Dezimalformat): `9,5h` = 9 Stunden 30 Minuten
- Wochen: Samstag–Freitag
- Ein Bericht pro Auftrag (gleiche Projektnamen werden automatisch zusammengeführt, auch bei Adressvarianten wie „Manhartstraße 5 Bad Tölz" → „Bad Tölz")
- Mehrere Tageseinträge für denselben Auftrag werden in einer Datei zusammengeführt

---

### WhatsApp-Benachrichtigung

Nach jedem Lauf werden Nachrichten an `benachrichtigungs_nummer` gesendet:

1. **Pro Auftrag**: Vollständiger Berichtsinhalt mit Header `📋 Gruppenname / KW-XX – Projektname`
2. **Gesamtzusammenfassung**: Auftragsanzahl, Gesamtstunden, Anomalien mit Datum (oder `✅ Keine Anomalien`)

---

### Sicherheitsmodell

```
WhatsApp ──► whatsapp-bridge (lokal, sieht alles)
                │
                │ ?chat=<JID>  ← nur diese Gruppe
                ▼
         whatsapp_integration.py
                │
                │ Kontakt-Whitelist (config.json)
                ▼
         Parser + Berichtsgenerator
```

- `chat_jid` in config.json → serverseitige Filterung, persönliche Chats verlassen den Bridge-Prozess nie
- `kontakte` → Kontakt-Whitelist pro Gruppe, leere Liste blockiert alle Nachrichten
- Deine eigenen Nachrichten (`Me`) werden immer ausgeschlossen
- `WHATSAPP_API_KEY` nur als Umgebungsvariable, nie im Code oder Config
- `berichte/` und `.env` in `.gitignore`

---

### Bridge-Voraussetzungen

Der `whatsapp-bridge` Prozess muss laufen:

```bash
cd ~/Developer/tools/whatsapp-mcp-go/whatsapp-bridge
source .env && go run main.go
# Bridge läuft auf localhost:8080
```

- Retry-Logik: 5 Versuche mit exponentiellem Backoff (1s, 2s, 4s, 8s)
- JWT-Token wird automatisch erneuert (gültig 40 Minuten)
- Bei `chat_jid = null`: JID wird automatisch aus Media-Nachrichten der Gruppe extrahiert und in config.json gespeichert
