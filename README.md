# Alma Zeiterfassung

Automated pipeline for compiling subcontractor working hours from WhatsApp group messages into structured weekly billing reports — in German, matching the exact invoice format used by Alma.

---

## What it does

1. Reads messages from whitelisted WhatsApp contractor groups via a local bridge
2. Parses German free-text work hour reports (times, pauses, worker counts, totals)
3. Generates structured `.txt` reports per project per calendar week
4. Detects anomalies (wrong calculations, missing dates, impossible hours) and flags them inline
5. Sends a WhatsApp notification per report + a summary after each run
6. Runs automatically every Friday at 17:00 via macOS launchd

---

## Tech stack

- **Python 3** — parser, report generator, WhatsApp integration
- **[whatsapp-mcp-go](https://github.com/iamatulsingh/whatsapp-mcp-go)** — local Go bridge connecting to WhatsApp Web (stores messages in SQLite)
- **macOS launchd** — scheduled execution
- **Kiro** — AI-assisted development + custom agent for manual triggering

---

## Prerequisites

1. macOS (launchd scheduling) or any Unix system for the scripts
2. Python 3.10+
3. `requests` library: `pip3 install requests`
4. [whatsapp-mcp-go](https://github.com/iamatulsingh/whatsapp-mcp-go) bridge built and running

---

## Setup

### 1. Clone and configure

```bash
git clone <your-repo>
cd alma-zeiterfassung
```

Copy the example config and fill in your values:

```bash
cp .kiro/skills/subunternehmer-stunden-kompilierung/config.example.json \
   .kiro/skills/subunternehmer-stunden-kompilierung/config.json
```

Edit `config.json`:
- `benachrichtigungs_nummer` — your WhatsApp number in international format without `+` (e.g. `4915218682585`)
- `whatsapp_gruppen[].gruppenname` — exact WhatsApp group name as it appears in the app
- `whatsapp_gruppen[].kontakte` — whitelist of contractor names/numbers to parse (empty = nothing processed)

### 2. Set your API key

```bash
export WHATSAPP_API_KEY="your-key-from-whatsapp-bridge-env"
```

Add it to your shell profile or a local `.env` file (never commit this).

### 3. Start the WhatsApp bridge

```bash
cd ~/path/to/whatsapp-mcp-go/whatsapp-bridge
source .env && go run main.go
# Scan the QR code on first run
```

### 4. Run

```bash
cd alma-zeiterfassung
python3 .kiro/skills/subunternehmer-stunden-kompilierung/scripts/whatsapp_integration.py
```

---

## Usage

```bash
# All active groups (from last checkpoint)
python3 whatsapp_integration.py

# Specific group only
python3 whatsapp_integration.py --gruppe "Adam Sub & Alma"

# Override checkpoint date
python3 whatsapp_integration.py --seit 2026-09-20

# Parse only, don't save
python3 whatsapp_integration.py --dry-run
```

---

## Output structure

```
berichte/                        ← gitignored (billing data)
└── 2026/
    └── Adam Sub & Alma/
        ├── KW-38/
        │   └── 19-09-bis-25-09-Bad-Tölz.txt
        └── KW-39/
            ├── 26-09-bis-02-10-Bad-Tölz.txt
            └── 26-09-bis-02-10-Simbach.txt
```

One `.txt` file per project per calendar week. Multiple days for the same project are merged into one file.

---

## Contractor message format

Contractors should send messages in this format:

```
📍 Bad Tölz  28.09.26
Arbeitsbeginn: 07:00–17:00 Uhr
Pause: 12:00–12:30
Insgesamt: 9,5 Std.
```

For multiple workers with different breaks, send separate messages. See [`SKILL.md`](.kiro/skills/subunternehmer-stunden-kompilierung/SKILL.md) for all supported formats.

---

## Anomaly detection

The parser flags issues directly in the report and in the WhatsApp summary:

| Level | Examples |
|-------|---------|
| 🔴 KRITISCH | Missing date, invalid time format (25:00), duplicate entry |
| 🟡 WARNUNG | Stated hours ≠ calculated hours (auto-corrected), shift > 12h, pause overlaps |
| 🔵 FEHLER | Missing project name, missing start time |

When the contractor's stated total differs from the calculated value (start − end − pauses), the **calculated value is used** and a warning is shown.

---

## Scheduled execution (macOS)

The launchd job `de.alma.stundenberichte` fires every **Friday at 17:00**:

```bash
# Check status
launchctl list | grep stundenberichte

# View logs
cat .kiro/agents/stundenberichte.log

# Disable
launchctl unload ~/Library/LaunchAgents/de.alma.stundenberichte.plist

# Re-enable
launchctl load ~/Library/LaunchAgents/de.alma.stundenberichte.plist
```

---

## Security

- The local WhatsApp bridge has access to all your messages. This app uses `?chat=<JID>` to filter at the API level — only whitelisted group messages are fetched into Python memory.
- `kontakte` whitelist ensures only authorised contractors are parsed.
- Your own messages (`Me`) are always excluded.
- `WHATSAPP_API_KEY` must be set as an environment variable — never hardcoded.
- `berichte/`, `config.json`, and `.env` are gitignored.

---

## Project structure

```
alma-zeiterfassung/
├── .gitignore
├── README.md
├── template.txt                          ← Reference report format
└── .kiro/
    ├── agents/
    │   ├── stundenberichte.md            ← Kiro agent definition
    │   └── stundenberichte-schedule.sh   ← Shell wrapper for launchd
    ├── hooks/
    │   └── stundenberichte-manuell.json  ← Kiro manual trigger hook
    ├── steering/
    │   └── alma-zeiterfassung-handover.md
    └── skills/subunternehmer-stunden-kompilierung/
        ├── SKILL.md
        ├── config.example.json           ← Template (commit this)
        ├── config.json                   ← Your config (gitignored)
        ├── test_cases.txt
        └── scripts/
            ├── message_parser.py
            ├── report_generator.py
            └── whatsapp_integration.py
```

---

## License

Private — Alma internal tooling.
