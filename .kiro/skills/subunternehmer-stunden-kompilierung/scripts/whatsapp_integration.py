#!/usr/bin/env python3
"""
WhatsApp-Integration für das Subunternehmer-Stunden-Kompilierungssystem.

Ruft Nachrichten NUR aus den in config.json whitelisteten Gruppen ab,
parst sie und speichert Berichte im Year/KW Format.

Verwendung:
  python3 whatsapp_integration.py                    # Alle aktiven Gruppen verarbeiten
  python3 whatsapp_integration.py --gruppe "Garten…" # Nur eine Gruppe
  python3 whatsapp_integration.py --seit 2026-09-22  # Ab bestimmtem Datum
  python3 whatsapp_integration.py --dry-run           # Nur parsen, nicht speichern
"""

import os
import sys
import json
import re
import argparse
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

# Pfade relativ zu diesem Script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# scripts/ → subunternehmer-stunden-kompilierung/ → skills/ → .kiro/ → project root
PROJEKT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', '..'))
CONFIG_PFAD = os.path.join(SCRIPT_DIR, '..', 'config.json')

sys.path.insert(0, SCRIPT_DIR)
from message_parser import DeutscherNachrichtenParser, Arbeitseintrag
from report_generator import DeutscherBerichtsgenerator


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

def config_laden(pfad: str) -> Dict:
    """Lade config.json."""
    pfad = os.path.abspath(pfad)
    if not os.path.exists(pfad):
        print(f"✗ Config nicht gefunden: {pfad}")
        sys.exit(1)
    with open(pfad, 'r', encoding='utf-8') as f:
        return json.load(f)


# ─────────────────────────────────────────────
# WhatsApp Bridge API
# ─────────────────────────────────────────────

class WhatsAppBridge:
    """Thin wrapper um die WhatsApp-Bridge HTTP API."""

    BASE_URL = "http://localhost:8080"

    def __init__(self, api_key: str, max_versuche: int = 5):
        self.api_key = api_key
        self.max_versuche = max_versuche
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    def _mit_retry(self, aktion, beschreibung: str = ""):
        """Führe eine Aktion mit bis zu max_versuche Wiederholungen aus (exponential backoff)."""
        import time
        letzter_fehler = None
        for versuch in range(1, self.max_versuche + 1):
            try:
                return aktion()
            except Exception as e:
                letzter_fehler = e
                if versuch < self.max_versuche:
                    wartezeit = 2 ** (versuch - 1)  # 1s, 2s, 4s, 8s
                    print(f"  ⟳ Versuch {versuch}/{self.max_versuche}"
                          f"{f' ({beschreibung})' if beschreibung else ''}: {e}"
                          f" – warte {wartezeit}s")
                    time.sleep(wartezeit)
        raise letzter_fehler

    def _jwt_holen(self) -> str:
        """Holt oder erneuert den JWT."""
        if self._token and self._token_expiry and datetime.now() < self._token_expiry:
            return self._token

        def login():
            resp = requests.post(
                f"{self.BASE_URL}/auth/login",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()["token"]

        self._token = self._mit_retry(login, "JWT-Login")
        self._token_expiry = datetime.now() + timedelta(minutes=40)
        return self._token

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self._jwt_holen()}"}

    def verbindung_pruefen(self) -> bool:
        """Prüfe ob Bridge verbunden ist (mit Retry)."""
        try:
            self._mit_retry(self._jwt_holen, "Verbindungscheck")
            return True
        except Exception as e:
            print(f"✗ Bridge nicht erreichbar nach {self.max_versuche} Versuchen: {e}")
            return False

    def gruppe_jid_nachschlagen(self, gruppenname: str,
                                rohtext: Optional[str] = None) -> Optional[str]:
        """Extrahiere die Chat-JID einer Gruppe aus Media-Nachrichten."""
        if not rohtext:
            def abfrage():
                resp = requests.get(
                    f"{self.BASE_URL}/api/messages",
                    params={"limit": 500},
                    headers=self._headers(),
                    timeout=20
                )
                resp.raise_for_status()
                return resp.json().get("result", "")
            try:
                rohtext = self._mit_retry(abfrage, "JID-Scan")
            except Exception as e:
                print(f"  ⚠ JID-Scan fehlgeschlagen: {e}")
                return None

        jid_muster = re.compile(r'\[.*?Chat JID:\s*([^\]]+)\]')
        gruppenname_kurz = gruppenname.lower().strip("…").strip()[:15]

        for zeile in rohtext.split('\n'):
            if gruppenname_kurz not in zeile.lower():
                continue
            m = jid_muster.search(zeile)
            if m:
                jid = m.group(1).strip()
                if jid and jid != "status@broadcast":
                    return jid

        return None

    def nachrichten_holen(self, nach_datum: Optional[datetime] = None,
                          max_nachrichten: int = 5000,
                          chat_jid: Optional[str] = None) -> List[Dict]:
        """Holt Nachrichten von der Bridge (serverseitig gefiltert wenn JID bekannt)."""
        def abfrage():
            params: Dict = {"limit": max_nachrichten}
            if chat_jid:
                params["chat"] = chat_jid
            if nach_datum:
                params["after"] = nach_datum.strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = requests.get(
                f"{self.BASE_URL}/api/messages",
                params=params,
                headers=self._headers(),
                timeout=30
            )
            resp.raise_for_status()
            return resp.json().get("result", "")

        try:
            rohtext = self._mit_retry(abfrage, "Nachrichten abrufen")
            nachrichten = self._nachrichten_parsen(rohtext)
            quelle = f"JID {chat_jid[:25]}…" if chat_jid else "alle Chats"
            print(f"✓ {len(nachrichten)} Textnachrichten empfangen (Quelle: {quelle})")
            return nachrichten
        except Exception as e:
            print(f"✗ Fehler beim Abrufen der Nachrichten nach {self.max_versuche} Versuchen: {e}")
            return []

    def nachricht_senden(self, empfaenger: str, nachricht: str) -> bool:
        """Sende eine WhatsApp-Nachricht an eine Nummer oder Gruppen-JID."""
        if not empfaenger:
            return False

        def senden():
            resp = requests.post(
                f"{self.BASE_URL}/api/send",
                json={"recipient": empfaenger, "message": nachricht},
                headers=self._headers(),
                timeout=15
            )
            resp.raise_for_status()
            return resp.json()

        try:
            ergebnis = self._mit_retry(senden, "Nachricht senden")
            return ergebnis.get("success", False)
        except Exception as e:
            print(f"  ⚠ Benachrichtigung fehlgeschlagen: {e}")
            return False

    def _nachrichten_parsen(self, rohtext: str) -> List[Dict]:
        """
        Parst das Rohformat der Bridge:
        [2026-10-05 21:55:58] Chat: Gruppenname From: Absender: Nachrichtentext

        Multi-Zeilen-Nachrichten werden korrekt zusammengeführt.
        """
        nachrichten = []
        muster = re.compile(
            r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+Chat:\s+(.+?)\s+From:\s+(.+?):\s+(.*)'
        )
        aktuell: Optional[Dict] = None

        for zeile in rohtext.split('\n'):
            m = muster.match(zeile)
            if m:
                if aktuell is not None:
                    nachrichten.append(aktuell)
                zeitstempel_str, gruppe, absender, text = m.groups()
                if text.startswith(('[image', '[video', '[audio', '[document', '[sticker')):
                    aktuell = None
                    continue
                try:
                    zeitstempel = datetime.strptime(zeitstempel_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    aktuell = None
                    continue
                aktuell = {
                    "zeitstempel": zeitstempel,
                    "gruppe": gruppe.strip(),
                    "absender": absender.strip(),
                    "text": text.strip()
                }
            else:
                if aktuell is not None:
                    fortsetzung = zeile.strip()
                    if fortsetzung:
                        aktuell["text"] += "\n" + fortsetzung
                    else:
                        aktuell["text"] += "\n"

        if aktuell is not None:
            nachrichten.append(aktuell)

        return nachrichten


# ─────────────────────────────────────────────
# Benachrichtigung
# ─────────────────────────────────────────────

def _benachrichtigung_senden(bridge: 'WhatsAppBridge', empfaenger: str,
                              dateipfade: List[str]) -> None:
    """
    Sendet eine WhatsApp-Nachricht pro Auftrag (report file),
    gefolgt von einer kompakten Gesamtzusammenfassung.
    """
    import os
    from datetime import datetime as _dt

    if not dateipfade:
        return

    print(f"\n📱 Sende WhatsApp-Benachrichtigung an {empfaenger}…")

    def kw_aus_pfad(pfad: str) -> str:
        for teil in pfad.replace('\\', '/').split('/'):
            if teil.startswith('KW-'):
                return teil
        return 'KW-?'

    def gruppe_aus_pfad(pfad: str) -> str:
        teile = pfad.replace('\\', '/').split('/')
        for i, teil in enumerate(teile):
            if teil.startswith('KW-') and i > 0:
                return teile[i - 1]
        return ''

    gesamt_stunden = 0.0
    anomalien: List[str] = []

    gesamt_muster = re.compile(r'Gesamt\s+\d{2}\.\d{2}\.\d{4}:\s+([\d,]+)\s+Arbeitsstunden')
    anomalie_muster = re.compile(r'(🔴|🟡|🔵).+(KRITISCH|WARNUNG|FEHLER).+')
    tag_muster = re.compile(
        r'^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s+\d{2}\.\d{2}\.\d{4}'
    )

    gesendet = 0

    # Eine Nachricht pro Auftrag
    for pfad in sorted(dateipfade):
        kw = kw_aus_pfad(pfad)
        gruppe = gruppe_aus_pfad(pfad)
        projektname = os.path.splitext(os.path.basename(pfad))[0]

        try:
            with open(pfad, 'r', encoding='utf-8') as f:
                inhalt = f.read().strip()
        except Exception:
            continue

        header = f"📋 {gruppe} / {kw} – {projektname}"
        nachricht = f"{header}\n\n{inhalt}"

        # Stunden und Anomalien sammeln
        aktueller_tag = ""
        in_anomalie = False
        for zeile in inhalt.splitlines():
            z = zeile.strip()
            if tag_muster.match(z):
                aktueller_tag = z
                in_anomalie = False
            m = gesamt_muster.search(z)
            if m:
                try:
                    gesamt_stunden += float(m.group(1).replace(',', '.'))
                except ValueError:
                    pass
            if '⚠️ ANOMALIEN ERKANNT' in z:
                in_anomalie = True
            if in_anomalie and anomalie_muster.search(z):
                datum = aktueller_tag.split(', ')[-1] if aktueller_tag else projektname
                anomalien.append(f"• {datum}: {z}")
            if z.startswith('⸻'):
                in_anomalie = False

        bridge.nachricht_senden(empfaenger, nachricht)
        gesendet += 1

    # Gesamtzusammenfassung als letzte Nachricht
    std_ganz = int(gesamt_stunden)
    minuten = int(round((gesamt_stunden - std_ganz) * 60))
    std_str = f"{std_ganz}h{f' {minuten}min' if minuten else ''}"

    zusammenfassung = [
        f"📊 *Zusammenfassung* – {_dt.now().strftime('%d.%m.%Y %H:%M')}",
        f"Aufträge: {gesendet}",
        f"Gesamtstunden: {std_str}",
    ]

    if anomalien:
        zusammenfassung.append(f"⚠️ {len(anomalien)} Anomalie(n):")
        gesehen: set = set()
        count = 0
        for a in anomalien:
            if a not in gesehen:
                gesehen.add(a)
                zusammenfassung.append(a)
                count += 1
            if count >= 5:
                rest = len(anomalien) - count
                if rest > 0:
                    zusammenfassung.append(f"  … +{rest} weitere")
                break
    else:
        zusammenfassung.append("✅ Keine Anomalien")

    erfolg = bridge.nachricht_senden(empfaenger, "\n".join(zusammenfassung))
    print(f"✓ {gesendet + 1} Nachrichten gesendet ({gesendet} Aufträge + Zusammenfassung)"
          if erfolg else "⚠ Zusammenfassung fehlgeschlagen")


# ─────────────────────────────────────────────
# Nachrichtenverarbeitung
# ─────────────────────────────────────────────

def nachrichten_nach_gruppe_filtern(
    alle_nachrichten: List[Dict],
    erlaubte_gruppen: List[str],
    gruppen_kontakte: Dict[str, List[str]],
    seit_datum: Optional[datetime] = None
) -> Dict[str, List[Dict]]:
    """
    Filtert Nachrichten nach whitelisteten Gruppen, Kontakt-Whitelist und Startdatum.

    SECURITY: Nur Gruppen explizit in der Whitelist werden verarbeitet.
    Leere Kontaktliste = keine Nachrichten verarbeiten.
    'Me' wird immer ausgeschlossen.
    """
    ergebnis: Dict[str, List[Dict]] = {g: [] for g in erlaubte_gruppen}

    for nachricht in alle_nachrichten:
        gruppe = nachricht["gruppe"]
        absender = nachricht["absender"]

        if gruppe not in erlaubte_gruppen:
            continue
        if absender.lower() in ("me", "ich"):
            continue

        erlaubte_kontakte = gruppen_kontakte.get(gruppe, [])
        if not erlaubte_kontakte:
            continue

        if not _kontakt_erlaubt(absender, erlaubte_kontakte):
            continue

        if seit_datum and nachricht["zeitstempel"] <= seit_datum:
            continue

        ergebnis[gruppe].append(nachricht)

    return ergebnis


def _kontakt_erlaubt(absender: str, erlaubte_kontakte: List[str]) -> bool:
    """Prüft ob ein Absender in der Kontaktliste steht (case-insensitiv, ignoriert ~«»)."""
    def normalisieren(name: str) -> str:
        return re.sub(r'^[~«»\s]+', '', name).strip().lower()

    absender_norm = normalisieren(absender)
    for kontakt in erlaubte_kontakte:
        kontakt_norm = normalisieren(kontakt)
        if absender_norm == kontakt_norm or absender_norm.startswith(kontakt_norm):
            return True
    return False


def _ist_stundenbericht(text: str) -> bool:
    """
    Prüft ob eine Nachricht ein Stundenbericht ist.
    Mindestens eine der folgenden Bedingungen muss zutreffen:
    - 'Arbeitsbeginn' vorhanden
    - Zeitbereich + Datum
    - Zeitbereich + Gesamtstunden
    - Multiplikationsformel (3×9=27)
    """
    text_lower = text.lower()

    hat_zeitbereich = bool(re.search(
        r'\d{1,2}[.:]\d{2}\s*[-–]\s*\d{1,2}[.:]\d{2}', text_lower
    ))
    hat_arbeitsbeginn = bool(re.search(r'arbeitsbeginn|arbeitszeit\s+baustelle', text_lower))
    hat_gesamtstunden = bool(re.search(
        r'insgesamt\s*[\d:,.]|ingesamt\s*[\d:,.]|'
        r'\d+\s*[*×]\s*\d+\s*=\s*\d+|'
        r'\d+(?:[,.]\d+)?\s*(?:h|st)\b',
        text_lower
    ))
    hat_datum = bool(re.search(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}', text_lower))

    if hat_arbeitsbeginn:
        return True
    if hat_zeitbereich and hat_datum:
        return True
    if hat_zeitbereich and hat_gesamtstunden:
        return True
    if bool(re.search(r'\d+\s*[*×]\s*\d+\s*=\s*\d+', text_lower)):
        return True

    return False


def nachrichten_nach_absender_gruppieren(nachrichten: List[Dict]) -> Dict[str, List[str]]:
    """Gruppiert Nachrichten pro Absender. Zusammenhängende Nachrichten (< 30 Min.) werden zusammengefasst."""
    sortiert = sorted(nachrichten, key=lambda n: n["zeitstempel"])
    bloecke: Dict[str, List[str]] = {}
    letzter_absender = None
    letzter_zeitstempel = None
    aktueller_block_key = None

    for nachricht in sortiert:
        absender = nachricht["absender"]
        zeitstempel = nachricht["zeitstempel"]
        text = nachricht["text"]

        neuer_block = (
            absender != letzter_absender or
            letzter_zeitstempel is None or
            (zeitstempel - letzter_zeitstempel).total_seconds() > 1800
        )

        if neuer_block:
            aktueller_block_key = f"{absender}__{zeitstempel.strftime('%Y%m%d_%H%M%S')}"
            bloecke[aktueller_block_key] = []

        bloecke[aktueller_block_key].append(text)
        letzter_absender = absender
        letzter_zeitstempel = zeitstempel

    absender_texte: Dict[str, List[str]] = {}
    for block_key, texte in bloecke.items():
        absender = block_key.split('__')[0]
        kombiniert = "\n".join(texte)
        if absender not in absender_texte:
            absender_texte[absender] = []
        absender_texte[absender].append(kombiniert)

    return absender_texte


def gruppe_verarbeiten(
    gruppenname: str,
    nachrichten: List[Dict],
    ausgabe_verzeichnis: str,
    config_pfad: str,
    dry_run: bool = False
) -> Tuple[int, int, List[str]]:
    """
    Verarbeitet alle Nachrichten einer Gruppe.
    Gibt (anzahl_eintraege, anzahl_dateien, gespeicherte_dateipfade) zurück.
    """
    if not nachrichten:
        print(f"  Keine neuen Nachrichten in '{gruppenname}'")
        return 0, 0, []

    print(f"\n{'─'*50}")
    print(f"Verarbeite Gruppe: {gruppenname}")
    print(f"Nachrichten: {len(nachrichten)}")

    absender_texte = nachrichten_nach_absender_gruppieren(nachrichten)
    parser = DeutscherNachrichtenParser()
    alle_eintraege: List[Arbeitseintrag] = []

    for absender, texte in absender_texte.items():
        for text in texte:
            if not text.strip():
                continue
            if not _ist_stundenbericht(text):
                print(f"  ⚪ {absender}: Übersprungen (kein Stundenbericht)")
                continue
            eintraege = parser.nachricht_parsen(text)
            if eintraege:
                alle_eintraege.extend(eintraege)
                print(f"  ✓ {absender}: {len(eintraege)} Eintrag/Einträge geparst")
            else:
                print(f"  ⚠ {absender}: Kein Arbeitseintrag erkannt")

    if not alle_eintraege:
        print(f"  Keine Arbeitseinträge in '{gruppenname}' gefunden.")
        return 0, 0, []

    print(f"\n  Gesamt: {len(alle_eintraege)} Arbeitseinträge")

    if dry_run:
        print("  [DRY-RUN] Kein Speichern.")
        generator = DeutscherBerichtsgenerator()
        berichte = generator.gesamtbericht_generieren(alle_eintraege)
        for key, inhalt in berichte.items():
            print(f"\n{'='*60}")
            print(f"[DRY-RUN] Bericht: {key}")
            print('='*60)
            print(inhalt)
        return len(alle_eintraege), 0, []

    generator = DeutscherBerichtsgenerator()
    gespeichert = generator.berichte_speichern(
        alle_eintraege,
        ausgabe_verzeichnis=ausgabe_verzeichnis,
        config_pfad=os.path.abspath(config_pfad),
        gruppenname=gruppenname
    )

    return len(alle_eintraege), len(gespeichert), list(gespeichert.values())


# ─────────────────────────────────────────────
# Hauptprogramm
# ─────────────────────────────────────────────

def main():
    parser_args = argparse.ArgumentParser(
        description="WhatsApp Subunternehmer-Stunden-Integration",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser_args.add_argument('--gruppe', help='Nur diese Gruppe verarbeiten', default=None)
    parser_args.add_argument('--seit', help='Nachrichten ab diesem Datum (YYYY-MM-DD)', default=None)
    parser_args.add_argument('--dry-run', action='store_true', help='Nur parsen, nicht speichern')
    parser_args.add_argument('--config', help='Pfad zur config.json', default=CONFIG_PFAD)
    args = parser_args.parse_args()

    config = config_laden(args.config)
    einstellungen = config.get("einstellungen", {})
    ausgabe_verzeichnis = os.path.join(PROJEKT_ROOT, einstellungen.get("ausgabe_verzeichnis", "berichte"))
    max_nachrichten = einstellungen.get("max_nachrichten_pro_abruf", 3000)

    api_key = os.environ.get("WHATSAPP_API_KEY")
    if not api_key:
        print("✗ WHATSAPP_API_KEY Umgebungsvariable nicht gesetzt.")
        print("  Setze sie mit: export WHATSAPP_API_KEY='dein-api-key'")
        print("  Oder füge sie in .kiro/skills/subunternehmer-stunden-kompilierung/../../../.env ein.")
        sys.exit(1)
    max_versuche = einstellungen.get("verbindungs_versuche", 5)
    benachrichtigungs_nummer = config.get("benachrichtigungs_nummer", "")

    bridge = WhatsAppBridge(api_key, max_versuche=max_versuche)
    if not bridge.verbindung_pruefen():
        print("✗ WhatsApp Bridge nicht erreichbar. Läuft der whatsapp-bridge Prozess?")
        sys.exit(1)
    print("✓ WhatsApp Bridge verbunden")

    alle_gruppen = config.get("whatsapp_gruppen", [])
    aktive_gruppen = [g for g in alle_gruppen if g.get("aktiv", True)]

    if args.gruppe:
        aktive_gruppen = [g for g in aktive_gruppen if g["gruppenname"] == args.gruppe]
        if not aktive_gruppen:
            print(f"✗ Gruppe '{args.gruppe}' nicht in config.json oder nicht aktiv.")
            sys.exit(1)

    if not aktive_gruppen:
        print("✗ Keine aktiven Gruppen in config.json konfiguriert.")
        sys.exit(1)

    print(f"\nAktive Gruppen: {[g['gruppenname'] for g in aktive_gruppen]}")

    # JIDs nachschlagen und in Config cachen (nur wenn fehlend)
    import json as _json
    config_geaendert = False
    gruppen_ohne_jid = [g for g in aktive_gruppen if not g.get("chat_jid")]
    scan_rohtext: Optional[str] = None

    if gruppen_ohne_jid:
        print(f"\n🔍 Scanne Nachrichten nach Gruppen-JIDs ({len(gruppen_ohne_jid)} fehlend)…")
        try:
            def scan_abfrage():
                resp = requests.get(
                    f"{bridge.BASE_URL}/api/messages",
                    params={"limit": 1000},
                    headers=bridge._headers(),
                    timeout=20
                )
                resp.raise_for_status()
                return resp.json().get("result", "")
            scan_rohtext = bridge._mit_retry(scan_abfrage, "JID-Scan")
        except Exception as e:
            print(f"  ⚠ Konnte Scan-Batch nicht laden: {e}")

        for gruppe_config in gruppen_ohne_jid:
            jid = bridge.gruppe_jid_nachschlagen(gruppe_config["gruppenname"], scan_rohtext)
            if jid:
                gruppe_config["chat_jid"] = jid
                print(f"  ✓ {gruppe_config['gruppenname']}: JID = {jid}")
                config_geaendert = True
            else:
                print(f"  ⚠ {gruppe_config['gruppenname']}: JID nicht gefunden – Name-Filter bleibt aktiv")

    if config_geaendert:
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config_raw = _json.load(f)
            for orig in config_raw.get("whatsapp_gruppen", []):
                for upd in aktive_gruppen:
                    if orig["gruppenname"] == upd["gruppenname"] and upd.get("chat_jid"):
                        orig["chat_jid"] = upd["chat_jid"]
            with open(args.config, 'w', encoding='utf-8') as f:
                _json.dump(config_raw, f, ensure_ascii=False, indent=2)
            print("✓ JIDs in Config gespeichert")
        except Exception as e:
            print(f"⚠ JID-Speicherung fehlgeschlagen: {e}")

    # Pro Gruppe separate Abfrage mit JID-Filter
    gesamt_eintraege = 0
    gesamt_dateien = 0
    alle_gespeicherte_pfade: List[str] = []

    for gruppe_config in aktive_gruppen:
        gruppenname = gruppe_config["gruppenname"]
        chat_jid = gruppe_config.get("chat_jid")

        if args.seit:
            try:
                seit_datum = datetime.strptime(args.seit, "%Y-%m-%d")
            except ValueError:
                print(f"✗ Ungültiges Datum '{args.seit}'. Format: YYYY-MM-DD")
                sys.exit(1)
        elif gruppe_config.get("letzter_bericht_datum"):
            seit_datum = datetime.strptime(gruppe_config["letzter_bericht_datum"], "%Y-%m-%d")
        else:
            seit_datum = None

        if seit_datum:
            print(f"\n  [{gruppenname}] Checkpoint: ab {seit_datum.strftime('%d.%m.%Y')}")
        else:
            print(f"\n  [{gruppenname}] Kein Checkpoint – alle Nachrichten")

        nachrichten_gruppe = bridge.nachrichten_holen(
            nach_datum=seit_datum,
            max_nachrichten=max_nachrichten,
            chat_jid=chat_jid
        )

        gruppen_kontakte = {gruppenname: gruppe_config.get("kontakte", [])}
        gefiltert = nachrichten_nach_gruppe_filtern(
            nachrichten_gruppe,
            erlaubte_gruppen=[gruppenname],
            gruppen_kontakte=gruppen_kontakte,
            seit_datum=seit_datum
        )

        eintraege, dateien, pfade = gruppe_verarbeiten(
            gruppenname=gruppenname,
            nachrichten=gefiltert.get(gruppenname, []),
            ausgabe_verzeichnis=ausgabe_verzeichnis,
            config_pfad=args.config,
            dry_run=args.dry_run
        )
        gesamt_eintraege += eintraege
        gesamt_dateien += dateien
        alle_gespeicherte_pfade.extend(pfade)

    print(f"\n{'='*50}")
    print(f"Fertig! {gesamt_eintraege} Einträge verarbeitet, {gesamt_dateien} Berichte gespeichert.")
    if args.dry_run:
        print("(DRY-RUN: keine Dateien wurden geschrieben)")

    if benachrichtigungs_nummer and gesamt_dateien > 0 and not args.dry_run:
        _benachrichtigung_senden(bridge, benachrichtigungs_nummer, alle_gespeicherte_pfade)


if __name__ == '__main__':
    main()
