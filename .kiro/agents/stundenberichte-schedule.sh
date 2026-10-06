#!/bin/zsh
# Stundenberichte – Wöchentlicher Lauf (Freitag 17:00 Uhr)
# Gestartet von: ~/Library/LaunchAgents/de.alma.stundenberichte.plist

set -e

PROJECT="/Users/halimlawal/Developer/alma-zeiterfassung"
SCRIPT="$PROJECT/.kiro/skills/subunternehmer-stunden-kompilierung/scripts/whatsapp_integration.py"
LOG="$PROJECT/.kiro/agents/stundenberichte.log"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') – Automatischer Freitags-Lauf gestartet" >> "$LOG"

# Bridge-Check
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8080 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "000" ]]; then
  echo "❌ WhatsApp-Bridge nicht erreichbar – Abbruch" >> "$LOG"
  exit 1
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
