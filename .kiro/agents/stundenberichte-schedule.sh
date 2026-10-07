#!/bin/zsh
# Stundenberichte – Wöchentlicher Lauf (Freitag 17:00 Uhr)
# Gestartet von: ~/Library/LaunchAgents/de.alma.stundenberichte.plist

set -e

# Projektpfad aus Script-Position ableiten (.kiro/agents/stundenberichte-schedule.sh)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCRIPT="$PROJECT/.kiro/skills/subunternehmer-stunden-kompilierung/scripts/whatsapp_integration.py"
CONFIG="$PROJECT/.kiro/skills/subunternehmer-stunden-kompilierung/config.json"
LOG="$PROJECT/.kiro/agents/stundenberichte.log"
BRIDGE_LOG="$PROJECT/.kiro/agents/bridge.log"
BRIDGE_PID=""
BRIDGE_GESTARTET=false

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') – Automatischer Freitags-Lauf gestartet" >> "$LOG"

# Schritt 1: Bridge-Check via lsof (identisch zum Hook)
if lsof -ti:8080 > /dev/null 2>&1; then
  echo "✅ Bridge läuft bereits – wird am Ende nicht gestoppt" >> "$LOG"
else
  echo "⚠️  Bridge nicht erreichbar – versuche zu starten…" >> "$LOG"

  # bridge_pfad aus config.json lesen
  BRIDGE_DIR=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('bridge_pfad',''))" 2>/dev/null)

  if [[ -z "$BRIDGE_DIR" ]]; then
    echo "❌ bridge_pfad nicht in config.json – Abbruch" >> "$LOG"
    exit 1
  fi

  if [[ ! -d "$BRIDGE_DIR" ]]; then
    echo "❌ Verzeichnis nicht gefunden: $BRIDGE_DIR – Abbruch" >> "$LOG"
    exit 1
  fi

  # Schritt 2b: Bridge starten (identisch zum Hook-Befehl)
  cd "$BRIDGE_DIR"
  set -a
  source .env 2>/dev/null || true
  set +a
  go run main.go >> "$BRIDGE_LOG" 2>&1 &
  BRIDGE_PID=$!
  BRIDGE_GESTARTET=true
  echo "Bridge gestartet (PID $BRIDGE_PID)" >> "$LOG"

  # Schritt 2c: Bis zu 3× auf 'Connected to WhatsApp' oder 'REST server is running' prüfen
  VERBUNDEN=false
  for VERSUCH in 1 2 3; do
    sleep 5
    if grep -q "Connected to WhatsApp\|REST server is running" "$BRIDGE_LOG" 2>/dev/null; then
      echo "✅ Bridge verbunden (Versuch $VERSUCH)" >> "$LOG"
      VERBUNDEN=true
      break
    fi
    echo "⟳ Versuch $VERSUCH/3 – warte auf Bridge…" >> "$LOG"
  done

  # Schritt 2d: Nach 3 Versuchen abbrechen
  if [[ "$VERBUNDEN" == false ]]; then
    echo "❌ Bridge nicht verbunden nach 3 Versuchen – Abbruch" >> "$LOG"
    [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null
    exit 1
  fi
fi

# Schritt 3: Berichte generieren
cd "$PROJECT"
python3 "$SCRIPT" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Lauf erfolgreich abgeschlossen" >> "$LOG"
else
  echo "⚠️  Lauf mit Fehler beendet (Exit $EXIT_CODE)" >> "$LOG"
fi

# Schritt 5: Bridge stoppen – nur wenn wir sie in diesem Lauf gestartet haben
if [[ "$BRIDGE_GESTARTET" == true && -n "$BRIDGE_PID" ]]; then
  kill "$BRIDGE_PID" 2>/dev/null
  echo "✅ Bridge gestoppt (PID $BRIDGE_PID)" >> "$LOG"
fi

exit $EXIT_CODE
