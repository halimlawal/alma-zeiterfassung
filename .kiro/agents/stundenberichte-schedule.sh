#!/bin/zsh
# Stundenberichte – Wöchentlicher Lauf (Freitag 17:00 Uhr)
# Gestartet von: ~/Library/LaunchAgents/de.alma.stundenberichte.plist

set -e

# Derive project root from this script's location (.kiro/agents/stundenberichte-schedule.sh)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCRIPT="$PROJECT/.kiro/skills/subunternehmer-stunden-kompilierung/scripts/whatsapp_integration.py"
CONFIG="$PROJECT/.kiro/skills/subunternehmer-stunden-kompilierung/config.json"
LOG="$PROJECT/.kiro/agents/stundenberichte.log"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') – Automatischer Freitags-Lauf gestartet" >> "$LOG"

# Bridge-Check – versuche zu starten falls nicht erreichbar
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8080 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "000" ]]; then
  echo "⚠️  Bridge nicht erreichbar – versuche zu starten…" >> "$LOG"

  # Lese bridge_pfad aus config.json
  BRIDGE_DIR=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('bridge_pfad',''))" 2>/dev/null)

  if [[ -z "$BRIDGE_DIR" ]]; then
    echo "❌ bridge_pfad nicht in config.json – Abbruch" >> "$LOG"
    exit 1
  fi

  if [[ ! -d "$BRIDGE_DIR" ]]; then
    echo "❌ Verzeichnis nicht gefunden: $BRIDGE_DIR – Abbruch" >> "$LOG"
    exit 1
  fi

  # Bridge im Hintergrund starten
  cd "$BRIDGE_DIR"
  source .env 2>/dev/null || true
  go run main.go >> "$LOG" 2>&1 &
  BRIDGE_PID=$!
  echo "Bridge gestartet (PID $BRIDGE_PID) – warte 10s…" >> "$LOG"
  sleep 10

  # Nochmal prüfen
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8080 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "000" ]]; then
    echo "❌ Bridge konnte nicht gestartet werden – Abbruch" >> "$LOG"
    exit 1
  fi
  echo "✅ Bridge erfolgreich gestartet" >> "$LOG"
fi

# Berichte generieren
cd "$PROJECT"
python3 "$SCRIPT" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Lauf erfolgreich abgeschlossen" >> "$LOG"
else
  echo "⚠️  Lauf mit Fehler beendet (Exit $EXIT_CODE)" >> "$LOG"
fi

exit $EXIT_CODE
