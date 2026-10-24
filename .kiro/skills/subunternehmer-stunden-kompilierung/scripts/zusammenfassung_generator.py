"""
Generiert projektübergreifende Zusammenfassungen per Auftrag pro KW.
Scannt alle Subunternehmer-Berichte und konsolidiert sie in:
  berichte/YYYY/Zusammenfassungen/KW-XX/Projektname.txt
"""

import os
import re
import glob
from datetime import datetime
from typing import Dict, List, Tuple


def _auftrag_normalisieren(auftrag: str) -> str:
    """Normalisiere Auftragsname für den Dateinamen."""
    # Umlaute beibehalten, Sonderzeichen entfernen
    s = re.sub(r'[^\w\s\-äöüÄÖÜß,.]', '', auftrag).strip()
    # Konsekutive Leerzeichen
    s = re.sub(r'\s+', ' ', s)
    return s.strip(' -.,')


def _dateiname_aus_auftrag(auftrag: str) -> str:
    """Erzeuge sicheren Dateinamen aus Auftragsname."""
    s = _auftrag_normalisieren(auftrag)
    # Leerzeichen und Kommas → Bindestriche
    s = re.sub(r'[\s,]+', '-', s)
    s = s.strip('-')
    return s + '.txt'


def _kw_datum_aus_verzeichnis(kw_verzeichnis: str) -> Tuple[str, str, str]:
    """
    Extrahiere KW-Label, Start- und End-Datum aus dem KW-Verzeichnisnamen.
    z.B. 'KW-41' → ('KW-41', '10.10', '16.10')
    """
    # Datum aus einer Bericht-Datei im Verzeichnis lesen
    dateien = glob.glob(os.path.join(kw_verzeichnis, '*.txt'))
    if dateien:
        basename = os.path.basename(dateien[0])
        m = re.match(r'(\d{2}-\d{2})-bis-(\d{2}-\d{2})', basename)
        if m:
            start = m.group(1).replace('-', '.')
            ende = m.group(2).replace('-', '.')
            return os.path.basename(kw_verzeichnis), start, ende
    return os.path.basename(kw_verzeichnis), '', ''


def _gesamtstunden_aus_datei(inhalt: str) -> float:
    """Extrahiere die KW-Gesamtstunden aus dem letzten ══ Block."""
    muster = re.findall(r'Gesamt KW-\d+[^:]*:\s*([\d,]+)h(?:\s+(\d+)min)?', inhalt)
    if muster:
        letzter = muster[-1]
        stunden = float(letzter[0].replace(',', '.'))
        if letzter[1]:
            stunden += int(letzter[1]) / 60.0
        return round(stunden, 2)
    return 0.0


def _format_stunden(stunden: float) -> str:
    """Formatiere Stunden: 5.5 → '5,5h', 9.0 → '9h', 5.5833 → '5h 35min'."""
    ganz = int(stunden)
    minuten = round((stunden - ganz) * 60)
    if minuten == 0:
        return f"{ganz}h"
    return f"{ganz}h {minuten}min"


def zusammenfassungen_erstellen(ausgabe_verzeichnis: str, jahr: int = None) -> List[str]:
    """
    Scannt alle Subunternehmer-Berichte und erstellt Zusammenfassungen
    pro Auftrag und KW unter ausgabe_verzeichnis/YYYY/Zusammenfassungen/KW-XX/
    
    Rückgabe: Liste erstellter Zusammenfassungs-Dateien
    """
    if jahr is None:
        jahr = datetime.now().year

    basis = os.path.join(ausgabe_verzeichnis, str(jahr))
    zusammen_basis = os.path.join(basis, 'Zusammenfassungen')

    # Alle Berichte sammeln (nicht aus Zusammenfassungen)
    # Struktur: {(kw_label, auftrag_norm): [(subunternehmer, datei, auftrag, inhalt)]}
    gruppen: Dict[Tuple[str, str], List[tuple]] = {}

    for datei in sorted(glob.glob(os.path.join(basis, '*', 'KW-*', '*.txt'))):
        # Subunternehmer aus Pfad extrahieren
        rel = os.path.relpath(datei, basis)
        teile = rel.split(os.sep)
        if len(teile) < 3:
            continue
        if teile[0] == 'Zusammenfassungen':
            continue

        subunternehmer = teile[0]
        kw_label = teile[1]  # z.B. "KW-41"

        try:
            with open(datei, 'r', encoding='utf-8') as f:
                inhalt = f.read()
        except Exception:
            continue

        # Auftrag aus Datei-Header lesen
        auftrag_match = re.search(r'^Auftrag:\s*(.+)$', inhalt, re.MULTILINE)
        if not auftrag_match:
            continue
        auftrag = auftrag_match.group(1).strip()

        # Unbekannte Projekte oder leere Namen überspringen
        if not auftrag or auftrag.lower().startswith('unbekannt'):
            continue

        auftrag_norm = auftrag.lower().strip()
        schluessel = (kw_label, auftrag_norm)

        if schluessel not in gruppen:
            gruppen[schluessel] = []
        gruppen[schluessel].append((subunternehmer, datei, auftrag, inhalt))

    # Zusammenfassungen schreiben
    erstellt = []

    for (kw_label, _), berichte in sorted(gruppen.items()):
        kw_dir = os.path.join(zusammen_basis, kw_label)
        os.makedirs(kw_dir, exist_ok=True)

        # Auftragsname: vollständigsten nehmen
        auftrag_display = max([b[2] for b in berichte], key=len)
        dateiname = _dateiname_aus_auftrag(auftrag_display)
        zusammen_pfad = os.path.join(kw_dir, dateiname)

        # Datum aus einem Bericht-Header lesen
        start_str, ende_str = '', ''
        for _, _, _, inhalt in berichte:
            m = re.search(r'Übersicht der Woche\s+(\d+\.\d+)\s*-\s*(\d+\.\d+)', inhalt)
            if m:
                start_str, ende_str = m.group(1), m.group(2)
                break

        # Zusammenfassung aufbauen
        zeilen = []
        zeilen.append('=' * 40)
        zeilen.append(f'Auftrag: {auftrag_display}')
        if start_str:
            zeilen.append(f'Zeitraum: {kw_label}  ({start_str}–{ende_str})')
        zeilen.append('=' * 40)

        gesamt_alle = 0.0

        for subunternehmer, _, _, inhalt in berichte:
            zeilen.append('')
            zeilen.append(f'── {subunternehmer} {"─" * max(1, 30 - len(subunternehmer))}')
            zeilen.append('')

            # Inhalts-Block ohne Header (ab der ersten Leerzeile nach dem Header)
            header_ende = inhalt.find('-' * 10 + '\n\n')
            if header_ende != -1:
                bericht_inhalt = inhalt[header_ende + 12:].strip()
            else:
                bericht_inhalt = inhalt.strip()

            # KW-Gesamtzeile entfernen (wird unten neu berechnet)
            bericht_ohne_gesamt = re.sub(
                r'\n*[═]{10,}\n.*?Gesamt KW[^\n]*\n?', '', bericht_inhalt
            ).rstrip()

            zeilen.append(bericht_ohne_gesamt)

            # KW-Stunden für diesen Subunternehmer
            sub_stunden = _gesamtstunden_aus_datei(inhalt)
            if sub_stunden > 0:
                zeilen.append('')
                zeilen.append('─' * 30)
                zeilen.append(f'{subunternehmer}: {_format_stunden(sub_stunden)} Arbeitsstunden')
                gesamt_alle += sub_stunden

        # Gesamtsumme über alle Subunternehmer
        zeilen.append('')
        zeilen.append('═' * 40)
        if len(berichte) > 1:
            zeilen.append(f'Gesamt {kw_label} ({start_str}–{ende_str}) – alle Subunternehmer:')
            zeilen.append(f'{_format_stunden(gesamt_alle)} Arbeitsstunden')
        else:
            zeilen.append(f'Gesamt {kw_label} ({start_str}–{ende_str}): {_format_stunden(gesamt_alle)} Arbeitsstunden')
        zeilen.append('')

        try:
            with open(zusammen_pfad, 'w', encoding='utf-8') as f:
                f.write('\n'.join(zeilen))
            erstellt.append(zusammen_pfad)
        except Exception as e:
            print(f'  ⚠ Zusammenfassung konnte nicht erstellt werden: {e}')

    return erstellt


if __name__ == '__main__':
    """CLI-Aufruf: python3 zusammenfassung_generator.py [ausgabe_verzeichnis] [jahr]"""
    import sys
    script_dir = os.path.dirname(os.path.abspath(__file__))
    projekt_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..', '..'))
    ausgabe_verz = sys.argv[1] if len(sys.argv) > 1 else os.path.join(projekt_root, 'berichte')
    jahr = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f'Erstelle Zusammenfassungen in {ausgabe_verz} ...')
    erstellt = zusammenfassungen_erstellen(ausgabe_verz, jahr)
    print(f'✅ {len(erstellt)} Zusammenfassungen erstellt:')
    for p in erstellt:
        print(f'  {p}')
