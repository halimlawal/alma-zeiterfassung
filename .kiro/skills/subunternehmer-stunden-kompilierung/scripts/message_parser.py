#!/usr/bin/env python3
"""
Deutscher WhatsApp-Nachrichten-Parser für Auftragnehmerstunden
Extrahiert strukturierte Zeitdaten aus deutschen Auftragnehmernachrichten.
"""

import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict

@dataclass
class Pausenzeit:
    beginn: str
    ende: str
    dauer_minuten: int

@dataclass
class Arbeitergruppe:
    """Repräsentiert eine Gruppe von Arbeitern mit gleichen Pausen."""
    anzahl: int
    pausen: List[Pausenzeit]
    netto_stunden: float
    gesamt_stunden: float
    berechnung: str  # z.B. "3*9,5=28,5"

@dataclass 
class Arbeitseintrag:
    datum: str
    projekt: str
    arbeitsbeginn: str
    arbeitsende: str
    arbeitergruppen: List[Arbeitergruppe]  # Mehrere Gruppen möglich
    gesamt_mitarbeiter: int  # Gesamtzahl aller Mitarbeiter
    gesamtstunden: float     # Summe aller Gruppen (berechneter Wert)
    urspruengliche_berechnung: str
    notizen: str
    angegebene_gesamtstunden: float = 0.0  # Contractor's stated total (vor Korrektur)
    validierungsprobleme: List['Validierungsproblem'] = None
    
    @property
    def pausen(self) -> List[Pausenzeit]:
        """Rückwärtskompatibilität - alle Pausen aller Gruppen."""
        alle_pausen = []
        for gruppe in self.arbeitergruppen:
            alle_pausen.extend(gruppe.pausen)
        return alle_pausen
    
    @property 
    def mitarbeiteranzahl(self) -> int:
        """Rückwärtskompatibilität - Gesamtzahl der Mitarbeiter."""
        return self.gesamt_mitarbeiter

@dataclass
class Validierungsproblem:
    typ: str  # 'zeit_anomalie', 'fehlende_daten', 'berechnungsabweichung'
    schweregrad: str  # 'warnung', 'fehler', 'kritisch' 
    nachricht: str
    feld: str
    erwartet: Any
    tatsaechlich: Any

class DeutscherNachrichtenParser:
    def __init__(self):
        # Deutsche Datumsmuster: 24.9.26, 1.10.26, 28.09.2026
        self.datumsmuster = [
            r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})',
            r'(\d{1,2})/(\d{1,2})/(\d{2,4})'
        ]
        
        # Zeitbereichsmuster: 07:00-17:30, 8.00-18.00, 07.00-17:30
        self.zeitbereich_muster = [
            r'(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})',
            r'(\d{1,2})\.(\d{2})\s*[-–]\s*(\d{1,2})\.(\d{2})',  # Punkt als Trenner
            r'(\d{1,2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})',  # Einfache Start zu detaillierte End
            r'(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})',  # Detaillierte Start zu einfache End
            r'(\d{1,2})\s*[-–]\s*(\d{1,2})',  # Einfache Stundenbereiche
        ]
        
        # Pausenmuster: 11:00-12:00, 09:00-09:30 und 12:00-12:30, "kein" für keine Pausen
        self.pausen_muster = [
            r'(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})',
            r'[Pp]ause[:\s]*(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})',
            r'[Pp]ausen[:\s]*([^\n]+)',
            r'(\d{1,2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})',  # 12-12:45 Format
            r'(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})',   # 12:00-13 Format
        ]
        
        # Mitarbeiterzahlmuster: 3 Mitarbeiter, 4 Personen, Insgesamt 3man, 2 Mann, 2 Männer
        # [Mm]änner? matcht: Männer, männer | [Mm]ann? matcht: man/Man/mann/Mann
        self.mitarbeiter_muster = [
            r'(\d+)\s*(?:[Mm]itarbeiter|[Pp]erson(?:en)?|[Mm]änner?|[Mm]ann?)',
            r'[Ee]insatz[:\s]*(\d+)\s*[Mm]itarbeiter',
            r'[Ii]nsgesamt[:\s]*(\d+)\s*[Mm]ann?',
            r'[Ii]ngesamt[:\s]*(\d+)\s*[Mm]ann?',   # Tippfehler berücksichtigen
            r'[Zz]usammen[:\s]*(\d+)\s*[Mm]ann?',   # Alternative
            r'(\d+)\s*[Pp]ersonen?',                # Nur Personen ohne Artikel
        ]
        
        # Deutsche Zahlwörter → Ziffern (für "Zwei man", "Drei Mitarbeiter" etc.)
        self._zahlwoerter = {
            'ein': '1', 'eine': '1', 'einen': '1', 'einem': '1',
            'zwei': '2', 'drei': '3', 'vier': '4', 'fünf': '5',
            'sechs': '6', 'sieben': '7', 'acht': '8', 'neun': '9', 'zehn': '10'
        }
        
        # Gesamtstundenmuster: Insgesamt 9h, 27 Arbeitsstunden, 3*9=27, Zusammen
        self.gesamtstunden_muster = [
            r'[Ii]nsgesamt[:\s]*(\d+(?:[,:.]\d+)?)\s*(?:h|st|Stunden?)',  # Mit Einheit - sind Stunden
            r'[Ii]ngesamt[:\s]*(\d+(?:[,:.]\d+)?)\s*(?:h|st|Stunden?)',   # Tippfehler mit Einheit
            r'[Zz]usammen[:\s]*(\d+(?:[,:.]\d+)?)\s*(?:h|st|Stunden?)',   # Alternative word mit Einheit
            r'[Zz]usammen[:\s]*(\d{1,2}):(\d{2})',   # Zusammen mit Zeitformat wie "17:40"
            r'(\d+(?:[,:.]\d+)?)\s*[Aa]rbeitsstunden',
            r'(\d+)\s*[x*×]\s*(\d+(?:[,:.]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,:.]\d+)?)',
            r'[Gg]esamt[^:]*?(\d+(?:[,:.]\d+)?)\s*(?:h|st|Stunden?)',
            # Einfache Zahlen NUR wenn sie nicht mit "man", "Mitarbeiter" oder "×" enden
            r'[Ii]nsgesamt[:\s]*(\d+(?:[,:.]\d+)?)(?!\s*[x*×])(?!\s*man)(?!\s*[Mm]itarbeiter)',  # Negative lookahead
            r'[Ii]ngesamt[:\s]*(\d+(?:[,:.]\d+)?)(?!\s*[x*×])(?!\s*man)(?!\s*[Mm]itarbeiter)',   # Tippfehler
        ]

    def nachricht_parsen(self, nachricht: str) -> List[Arbeitseintrag]:
        """Parse eine WhatsApp-Nachricht und extrahiere Arbeitseinträge."""
        eintraege = []
        
        # Nachricht nach potentiellen Datumsmarkierungen aufteilen
        zeilen = nachricht.strip().split('\n')
        aktueller_eintrag = None
        alle_zeilen_buffer = []  # Sammle alle Zeilen für spätere Verarbeitung
        pausen_sammlung = ""  # Sammle mehrzeilige Pausen wieder ein
        insgesamt_gefunden = False  # Signal dass aktueller Eintrag abgeschlossen ist
        pending_projekt = ""  # Projektkandidat nach "Insgesamt" vor nächstem "Arbeitsbeginn"
        
        for i, zeile in enumerate(zeilen):
            zeile = zeile.strip()
            if not zeile:
                continue
            
            zeile_klein = zeile.lower()
                
            # Prüfe auf Datum
            datum_match = self._datum_finden(zeile)
            if datum_match:
                # Speichere vorherigen Eintrag falls vorhanden
                if aktueller_eintrag:
                    # Verarbeite finale Pausen
                    if pausen_sammlung:
                        pausen = self._pausen_extrahieren(pausen_sammlung)
                        # Füge zu erste Gruppe hinzu (Rückwärtskompatibilität)
                        if aktueller_eintrag.arbeitergruppen:
                            aktueller_eintrag.arbeitergruppen[0].pausen.extend(pausen)
                    
                    aktueller_eintrag = self._eintrag_mit_zeilen_finalisieren(aktueller_eintrag, alle_zeilen_buffer)
                    eintraege.append(aktueller_eintrag)
                    
                # Beginne neuen Eintrag
                aktueller_eintrag = self._neuen_eintrag_erstellen(datum_match)
                alle_zeilen_buffer = []
                pausen_sammlung = ""
                insgesamt_gefunden = False
                pending_projekt = ""
                
                # Extrahiere Projektname aus derselben Zeile
                projekt = self._projektname_extrahieren(zeile, datum_match)
                if projekt:
                    aktueller_eintrag.projekt = projekt
                # Falls kein Projekt in dieser Zeile, prüfe nächste NICHT-LEERE Zeile
                else:
                    for j in range(i + 1, min(i + 6, len(zeilen))):
                        naechste_zeile = zeilen[j].strip()
                        if not naechste_zeile:
                            continue  # Leere Zeilen überspringen
                        if not self._datum_finden(naechste_zeile) and 'arbeitsbeginn' not in naechste_zeile.lower():
                            aktueller_eintrag.projekt = self._projektname_aus_zeile_extrahieren(naechste_zeile)
                        break  # Nur erste nicht-leere Zeile prüfen
                    
            else:
                # Zweites "Arbeitsbeginn" nach "Insgesamt" → neuer Eintrag gleichen Datums
                if 'arbeitsbeginn' in zeile_klein and aktueller_eintrag and insgesamt_gefunden:
                    # Finalisiere aktuellen Eintrag
                    if pausen_sammlung:
                        pausen = self._pausen_extrahieren(pausen_sammlung)
                        if aktueller_eintrag.arbeitergruppen:
                            aktueller_eintrag.arbeitergruppen[0].pausen.extend(pausen)
                    aktueller_eintrag = self._eintrag_mit_zeilen_finalisieren(aktueller_eintrag, alle_zeilen_buffer)
                    eintraege.append(aktueller_eintrag)
                    
                    # Neuer Eintrag – erbt Datum, übernimmt pending_projekt als Projektname
                    vorheriges_datum = eintraege[-1].datum
                    aktueller_eintrag = self._neuen_eintrag_erstellen(None)
                    aktueller_eintrag.datum = vorheriges_datum
                    if pending_projekt:
                        aktueller_eintrag.projekt = self._projektname_aus_zeile_extrahieren(pending_projekt)
                    alle_zeilen_buffer = [zeile]
                    pausen_sammlung = ""
                    insgesamt_gefunden = False
                    pending_projekt = ""
                    self._zeile_in_eintrag_parsen(zeile, aktueller_eintrag)
                    continue

                # Erstelle Eintrag auch wenn kein Datum gefunden wurde
                if not aktueller_eintrag:
                    # Erstelle Eintrag auch ohne Datum - wird als verdächtig markiert
                    aktueller_eintrag = self._neuen_eintrag_erstellen(None)
                    alle_zeilen_buffer = []
                    pausen_sammlung = ""
                    insgesamt_gefunden = False
                    pending_projekt = ""
                    # Erste Zeile ohne Datum könnte Projektname sein
                    if i == 0 and not any(keyword in zeile_klein for keyword in ['arbeitsbeginn', 'pause']):
                        aktueller_eintrag.projekt = self._projektname_aus_zeile_extrahieren(zeile)
                        continue
                
                # Insgesamt-Signal tracken
                if re.search(r'\binsgesamt\b|\bingesamt\b', zeile_klein):
                    insgesamt_gefunden = True
                    pending_projekt = ""
                elif insgesamt_gefunden and not any(k in zeile_klein for k in [
                        'arbeitsbeginn', 'pause', 'leistung', 'aufwand', 'insgesamt', 'ingesamt']):
                    # Text zwischen Insgesamt und nächstem Arbeitsbeginn = Projekkandidat
                    if re.search(r'[a-zA-ZäöüÄÖÜß]{3,}', zeile) and not re.match(r'^\d+[,.:]?\d*\s*$', zeile):
                        pending_projekt = zeile.strip()
                
                # Sammle alle Zeilen für spätere Verarbeitung
                alle_zeilen_buffer.append(zeile)
                
                # Parse grundlegende Felder sofort UND Pausen
                self._zeile_in_eintrag_parsen(zeile, aktueller_eintrag)
                
                # Spezielle Pausen-Behandlung - wiederhergestellt
                if zeile.startswith('            ') or re.match(r'^\s*\d{1,2}[:.:]?\d{0,2}\s*[-–]\s*\d{1,2}[:.:]?\d{0,2}\s*$', zeile):
                    # Das ist eine Fortsetzung der Pausen
                    pausen_sammlung += " " + zeile.strip()
                elif 'pause' in zeile_klein and 'kein' not in zeile_klein:
                    # Neue Pause gefunden, verarbeite vorherige falls vorhanden
                    if pausen_sammlung:
                        pausen = self._pausen_extrahieren(pausen_sammlung)
                        # Erstelle temporäre Gruppe falls noch nicht vorhanden
                        if not aktueller_eintrag.arbeitergruppen:
                            temp_gruppe = Arbeitergruppe(anzahl=1, pausen=[], netto_stunden=0, gesamt_stunden=0, berechnung="")
                            aktueller_eintrag.arbeitergruppen.append(temp_gruppe)
                        aktueller_eintrag.arbeitergruppen[0].pausen.extend(pausen)
                    pausen_sammlung = zeile
                else:
                    # Normale Zeile, verarbeite gesammelte Pausen falls vorhanden
                    if pausen_sammlung:
                        pausen = self._pausen_extrahieren(pausen_sammlung)
                        # Erstelle temporäre Gruppe falls noch nicht vorhanden
                        if not aktueller_eintrag.arbeitergruppen:
                            temp_gruppe = Arbeitergruppe(anzahl=1, pausen=[], netto_stunden=0, gesamt_stunden=0, berechnung="")
                            aktueller_eintrag.arbeitergruppen.append(temp_gruppe)
                        aktueller_eintrag.arbeitergruppen[0].pausen.extend(pausen)
                        pausen_sammlung = ""
                
        # Vergiss den letzten Eintrag nicht
        if aktueller_eintrag:
            # Verarbeite finale Pausen
            if pausen_sammlung:
                pausen = self._pausen_extrahieren(pausen_sammlung)
                if not aktueller_eintrag.arbeitergruppen:
                    temp_gruppe = Arbeitergruppe(anzahl=1, pausen=[], netto_stunden=0, gesamt_stunden=0, berechnung="")
                    aktueller_eintrag.arbeitergruppen.append(temp_gruppe)
                aktueller_eintrag.arbeitergruppen[0].pausen.extend(pausen)
                
            aktueller_eintrag = self._eintrag_mit_zeilen_finalisieren(aktueller_eintrag, alle_zeilen_buffer)
            eintraege.append(aktueller_eintrag)
            
        # Prüfe auf Duplikate vor Rückgabe
        self._duplikate_pruefen(eintraege)
        
        return eintraege

    def _eintrag_mit_zeilen_finalisieren(self, eintrag: Arbeitseintrag, zeilen: List[str]) -> Arbeitseintrag:
        """Finalisiere Eintrag mit kompletter Zeilen-Analyse für Arbeitergruppen."""
        # Parse Arbeitergruppen aus allen gesammelten Zeilen
        arbeitergruppen = self._arbeitergruppen_parsen(zeilen, eintrag)
        
        if arbeitergruppen and self._ist_komplexer_fall(arbeitergruppen, zeilen):
            # Komplexer Multi-Group-Fall - nutze Gruppendaten
            eintrag.arbeitergruppen = arbeitergruppen
            eintrag.gesamt_mitarbeiter = sum(g.anzahl for g in arbeitergruppen)
            calculated_total = sum(g.gesamt_stunden for g in arbeitergruppen)
            
            # Bei komplexen Fällen nutze immer die Summe der Gruppen
            eintrag.gesamtstunden = calculated_total
                
            # Setze ursprüngliche Berechnung basierend auf Gruppen
            berechnungen = [g.berechnung for g in arbeitergruppen if g.berechnung]
            if berechnungen:
                eintrag.urspruengliche_berechnung = "; ".join(berechnungen)
        else:
            # Einfacher Fall - erstelle eine Gruppe mit gesammelten Daten
            
            # Sammle Mitarbeiteranzahl und Berechnungen aus den Zeilen
            mitarbeiteranzahl = eintrag.gesamt_mitarbeiter
            berechnung_total = 0
            berechnung_text = eintrag.urspruengliche_berechnung
            
            for zeile in zeilen:
                # Suche Mitarbeiteranzahl (aber nicht "Insgesamt X" ohne "man")
                ma = self._mitarbeiteranzahl_extrahieren(zeile)
                if ma and mitarbeiteranzahl == 0:
                    mitarbeiteranzahl = ma
                    
                # Suche Berechnungen (3*9=27, 2×1,00 Std.=2,00 Std.)
                if ('*' in zeile or '×' in zeile) and '=' in zeile:
                    berechnung_match = re.search(r'(\d+)\s*[*×]\s*(\d+(?:[,.:]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,.:]\d+)?)', zeile)
                    if berechnung_match and berechnung_total == 0:
                        try:
                            berechnung_total = float(berechnung_match.group(3).replace(',', '.'))
                            berechnung_text = zeile
                            # Mitarbeiteranzahl aus Multiplikator übernehmen falls noch nicht bekannt
                            # (z.B. "2 × 3,75 Std. = 7,50 Std." → 2 Mitarbeiter)
                            if mitarbeiteranzahl == 0:
                                mitarbeiteranzahl = int(berechnung_match.group(1))
                        except ValueError:
                            pass
                        
            if mitarbeiteranzahl == 0:
                mitarbeiteranzahl = 1
            
            # Nutze bereits gesammelte Pausen aus der ersten Gruppe falls vorhanden
            pausen = []
            if eintrag.arbeitergruppen and eintrag.arbeitergruppen[0].pausen:
                pausen = eintrag.arbeitergruppen[0].pausen
            
            netto_stunden = self._arbeitsdauer_berechnen_basis(eintrag.arbeitsbeginn, eintrag.arbeitsende, pausen)
            calculated_total = netto_stunden * mitarbeiteranzahl
            
            # Priorisiere Berechnungen über explizite "Insgesamt" Aussagen
            final_total = eintrag.gesamtstunden
            stated_total = eintrag.gesamtstunden  # Merke Contractor-Angabe
            if berechnung_total > 0:
                final_total = berechnung_total
                eintrag.urspruengliche_berechnung = berechnung_text
            elif final_total == 0:
                final_total = calculated_total
            else:
                # Wenn berechneter Wert und angegebener Wert abweichen:
                # Verwende berechneten Wert als Quelle der Wahrheit.
                # Abweichung wird später durch eintrag_validieren geflaggt.
                if (calculated_total > 0
                        and abs(final_total - calculated_total) >= 0.1):
                    final_total = calculated_total
            
            # Speichere Contractor-Angabe für spätere Validierung
            eintrag.angegebene_gesamtstunden = stated_total
            
            eintrag.gesamt_mitarbeiter = mitarbeiteranzahl
            eintrag.gesamtstunden = final_total
            
            # Erstelle einzelne Gruppe
            gruppe = Arbeitergruppe(
                anzahl=mitarbeiteranzahl,
                pausen=pausen,
                netto_stunden=final_total / mitarbeiteranzahl if mitarbeiteranzahl > 0 else 0,  # Rückwärtsberechnung
                gesamt_stunden=final_total,
                berechnung=berechnung_text
            )
            eintrag.arbeitergruppen = [gruppe]
        
        # Validiere Eintrag und füge Probleme hinzu
        validierungsprobleme = self.eintrag_validieren(eintrag)
        eintrag.validierungsprobleme = validierungsprobleme if validierungsprobleme else None
        
        return eintrag

    def _ist_komplexer_fall(self, gruppen: List[Arbeitergruppe], zeilen: List[str]) -> bool:
        """Prüfe ob dies ein komplexer Multi-Group-Fall ist."""
        # Komplexer Fall wenn:
        # 1. Mehrere Gruppen gefunden wurden
        # 2. Mehrere Berechnungen in den Zeilen gefunden werden
        if len(gruppen) > 1:
            return True
            
        berechnung_count = 0
        for zeile in zeilen:
            if '*' in zeile and '=' in zeile:
                berechnung_count += 1
        
        return berechnung_count > 1

    def _neuen_eintrag_erstellen(self, datum_match: Optional[str]) -> Arbeitseintrag:
        """Erstelle neuen Arbeitseintrag mit Datum oder Fallback."""
        if datum_match:
            datum = self._datum_normalisieren(datum_match)
        else:
            # Kein Datum gefunden - lasse leer und markiere als Problem
            datum = ""
            
        return Arbeitseintrag(
            datum=datum,
            projekt="",
            arbeitsbeginn="",
            arbeitsende="", 
            arbeitergruppen=[],
            gesamt_mitarbeiter=0,
            gesamtstunden=0.0,
            urspruengliche_berechnung="",
            notizen="",
            angegebene_gesamtstunden=0.0
        )
    
    def _eintrag_finalisieren(self, eintrag: Arbeitseintrag):
        """Finalisiere einen Eintrag durch Parsing der Arbeitergruppen."""
        # Parse die gesamte Nachricht erneut um Arbeitergruppen zu extrahieren
        zeilen = (eintrag.urspruengliche_berechnung + "\n" + eintrag.notizen).split('\n')
        arbeitergruppen = self._arbeitergruppen_parsen(zeilen, eintrag)
        
        if arbeitergruppen:
            eintrag.arbeitergruppen = arbeitergruppen
            eintrag.gesamt_mitarbeiter = sum(g.anzahl for g in arbeitergruppen)
            eintrag.gesamtstunden = sum(g.gesamt_stunden for g in arbeitergruppen)
        else:
            # Fallback für einfache Fälle
            if eintrag.gesamt_mitarbeiter == 0:
                eintrag.gesamt_mitarbeiter = 1
            
            netto_stunden = self._arbeitsdauer_berechnen_basis(eintrag.arbeitsbeginn, eintrag.arbeitsende, [])
            gruppe = Arbeitergruppe(
                anzahl=eintrag.gesamt_mitarbeiter,
                pausen=[],
                netto_stunden=netto_stunden,
                gesamt_stunden=netto_stunden * eintrag.gesamt_mitarbeiter,
                berechnung=""
            )
            eintrag.arbeitergruppen = [gruppe]
            if eintrag.gesamtstunden == 0:
                eintrag.gesamtstunden = gruppe.gesamt_stunden

    def _datum_finden(self, zeile: str) -> Optional[str]:
        """Finde und extrahiere Datum aus Zeile."""
        for muster in self.datumsmuster:
            match = re.search(muster, zeile)
            if match:
                return match.group(0)
        return None

    def _datum_normalisieren(self, datum_str: str) -> str:
        """Konvertiere deutsches Datumsformat zu ISO-Format."""
        try:
            # Verschiedene Trenner behandeln
            datum_str = datum_str.replace('/', '.')
            teile = datum_str.split('.')
            
            tag = int(teile[0])
            monat = int(teile[1]) 
            jahr = int(teile[2])
            
            # 2-stellige Jahre behandeln
            if jahr < 100:
                jahr += 2000
                
            return f"{jahr:04d}-{monat:02d}-{tag:02d}"
        except:
            return datum_str

    def _projektname_extrahieren(self, zeile: str, datum_match: str) -> str:
        """Extrahiere Projektname aus Zeile mit Datum - flexibler Ansatz für jedes Projekt."""
        # Datum aus Zeile entfernen
        bereinigte_zeile = zeile.replace(datum_match, '').strip()
        
        if not bereinigte_zeile:
            return ""
            
        # Häufige deutsche Arbeitsbegriffe entfernen, die nicht Teil von Projektnamen sind
        aufräum_wörter = ['arbeitsbeginn', 'pause', 'leistung', 'insgesamt', 'mitarbeiter', 'personen', 'uhr']
        
        # Alles vor häufigen Trennern oder Indikatoren nehmen
        trenner = ['\n', 'arbeitsbeginn', 'arbeitszeit', 'pause', 'leistung', 'einsatz']
        
        projektname = bereinigte_zeile
        for trenner_wort in trenner:
            if trenner_wort.lower() in projektname.lower():
                projektname = projektname.split(trenner_wort.lower())[0].strip()
                break
        
        # Zusätzliche Leerzeichen und häufige Satzzeichen bereinigen
        projektname = re.sub(r'\s+', ' ', projektname)
        projektname = projektname.strip(' -.,;:')
        
        # Wenn zu lang, ersten sinnvollen Teil nehmen
        if len(projektname) > 50:
            # Nach häufigen Trennzeichen aufteilen und ersten Teil nehmen
            for trenner in [',', ';', '–', '—', '  ']:
                if trenner in projektname:
                    projektname = projektname.split(trenner)[0].strip()
                    break
            
            # Falls immer noch zu lang, abschneiden
            if len(projektname) > 50:
                projektname = projektname[:47] + "..."
        
        return projektname if projektname else bereinigte_zeile[:50]

    def _projektname_aus_zeile_extrahieren(self, zeile: str) -> str:
        """Extrahiere Projektname aus beliebiger Zeile ohne Datum."""
        if not zeile:
            return ""
            
        # Häufige deutsche Arbeitsbegriffe entfernen
        aufräum_wörter = ['arbeitsbeginn', 'arbeitszeit', 'pause', 'leistung', 'insgesamt', 'mitarbeiter', 'personen', 'uhr', 'zusammen']
        
        projektname = zeile
        for wort in aufräum_wörter:
            if wort.lower() in projektname.lower():
                projektname = projektname.split(wort.lower())[0].strip()
                break
        
        # Zusätzliche Leerzeichen und häufige Satzzeichen bereinigen
        projektname = re.sub(r'\s+', ' ', projektname)
        projektname = projektname.strip(' -.,;:')
        
        # Wenn zu lang, ersten sinnvollen Teil nehmen
        if len(projektname) > 50:
            for trenner in [',', ';', '–', '—', '  ']:
                if trenner in projektname:
                    projektname = projektname.split(trenner)[0].strip()
                    break
            if len(projektname) > 50:
                projektname = projektname[:47] + "..."
        
                
        return projektname if projektname else zeile[:50]

    def _arbeitergruppen_parsen(self, alle_zeilen: List[str], eintrag: Arbeitseintrag) -> List[Arbeitergruppe]:
        """Parse komplexe Arbeitergruppen-Strukturen aus der gesamten Nachricht."""
        # Sammle alle relevanten Zeilen für die Analyse
        relevante_zeilen = []
        for zeile in alle_zeilen:
            zeile = zeile.strip()
            if not zeile:
                continue
            # Strukturzeilen: Gruppen, Pausen, Berechnungen
            if any(keyword in zeile.lower() for keyword in
                   ['person', 'mitarbeiter', 'pause', 'man', '*', '=']):
                relevante_zeilen.append(zeile)
            # Zeitbereichs-Fortsetzungen ohne Schlüsselwort (z.B. "12:00-12:30")
            elif re.match(r'^\d{1,2}[:.]\d{2}\s*[-–/]\s*\d{1,2}[:.]\d{2}', zeile):
                relevante_zeilen.append(zeile)
        
        if not relevante_zeilen:
            return []
        
        # Versuche komplexe Multi-Group-Struktur zu erkennen
        gruppen = self._komplexe_gruppen_struktur_erkennen(relevante_zeilen, eintrag)
        if gruppen:
            return gruppen
            
        # Fallback auf einfache Struktur
        return self._einfache_gruppe_erstellen(relevante_zeilen, eintrag)

    def _komplexe_gruppen_struktur_erkennen(self, zeilen: List[str], eintrag: Arbeitseintrag) -> List[Arbeitergruppe]:
        """Erkenne komplexe Multi-Group-Strukturen wie im Test-Case.
        
        Phase 1: Weise Pausen den Gruppen nach Position zu (Pausen vor dem nächsten
                 Gruppen-Header gehören zur aktuellen Gruppe).
        Phase 2: Ordne Berechnungen den Gruppen anhand ihrer Anzahl zu.
        """
        # Phase 1: Gruppen mit Pausen aufbauen
        gruppen_info: List[Dict] = []
        aktuelle_anzahl: Optional[int] = None
        pausen_buffer: List[Pausenzeit] = []

        for zeile in zeilen:
            zeile_klein = zeile.lower()
            ma = self._mitarbeiteranzahl_extrahieren(zeile)
            ist_summe = ('ingesamt' in zeile_klein
                         or 'zusammen' in zeile_klein)

            if ma and not ist_summe:
                # Schliesse vorherige Gruppe ab
                if aktuelle_anzahl is not None:
                    gruppen_info.append({'anzahl': aktuelle_anzahl, 'pausen': list(pausen_buffer)})
                aktuelle_anzahl = ma
                pausen_buffer = []

            elif 'pause' in zeile_klein and 'kein' not in zeile_klein:
                pausen_buffer.extend(self._pausen_extrahieren(zeile))

            elif re.match(r'^\d{1,2}[:.]\d{2}\s*[-–/]\s*\d{1,2}[:.]\d{2}', zeile):
                pausen_buffer.extend(self._pausen_extrahieren(zeile))

        # Letzte Gruppe speichern
        if aktuelle_anzahl is not None:
            gruppen_info.append({'anzahl': aktuelle_anzahl, 'pausen': list(pausen_buffer)})

        if not gruppen_info:
            return []

        # Phase 2: Berechnungen den Gruppen anhand der Anzahl zuordnen
        for zeile in zeilen:
            bm = re.search(r'(\d+)\s*[*×]\s*(\d+(?:[,.:]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,.:]\d+)?)', zeile)
            if bm:
                berechnung_anzahl = int(bm.group(1))
                for info in gruppen_info:
                    if info['anzahl'] == berechnung_anzahl and 'berechnung' not in info:
                        info['berechnung'] = zeile
                        break

        # Phase 3: Arbeitergruppe-Objekte erzeugen
        gruppen = []
        for info in gruppen_info:
            pausen = info.get('pausen', [])
            berechnung = info.get('berechnung', '')

            netto_stunden = self._arbeitsdauer_berechnen_basis(
                eintrag.arbeitsbeginn, eintrag.arbeitsende, pausen
            )
            gesamt_stunden = netto_stunden * info['anzahl']

            # Exakte Werte aus Berechnung übernehmen wenn vorhanden
            if berechnung:
                bm = re.search(r'(\d+)\s*[*×]\s*(\d+(?:[,.:]\d+)?)\s*=\s*(\d+(?:[,.:]\d+)?)', berechnung)
                if bm:
                    try:
                        netto_stunden = float(bm.group(2).replace(',', '.'))
                        gesamt_stunden = float(bm.group(3).replace(',', '.'))
                    except ValueError:
                        pass

            # Pausen deduplizieren (Parsing-Artefakte entfernen)
            gesehen: set = set()
            einzigartige_pausen = []
            for p in pausen:
                key = f"{p.beginn}-{p.ende}"
                if key not in gesehen:
                    gesehen.add(key)
                    einzigartige_pausen.append(p)

            gruppen.append(Arbeitergruppe(
                anzahl=info['anzahl'],
                pausen=einzigartige_pausen,
                netto_stunden=netto_stunden,
                gesamt_stunden=gesamt_stunden,
                berechnung=berechnung
            ))

        return gruppen

    def _berechnungen_in_gruppen_aufteilen(self, gruppen: List[Arbeitergruppe]) -> List[Arbeitergruppe]:
        """Teile Gruppen mit mehreren Berechnungen in separate Gruppen auf."""
        neue_gruppen = []
        
        for gruppe in gruppen:
            if not gruppe.berechnung:
                neue_gruppen.append(gruppe)
                continue
                
            # Suche nach mehreren Berechnungen in einer Zeile/Gruppe
            berechnungen = re.findall(r'(\d+)\s*[x*×]\s*(\d+(?:[,.:]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,.:]\d+)?)', gruppe.berechnung)
            
            if len(berechnungen) > 1:
                # Mehrere Berechnungen gefunden - erstelle separate Gruppen
                for berechnung in berechnungen:
                    try:
                        anzahl = int(berechnung[0])
                        stunden_einzeln = float(berechnung[1].replace(',', '.'))
                        gesamt_stunden = float(berechnung[2].replace(',', '.'))
                        
                        neue_gruppe = Arbeitergruppe(
                            anzahl=anzahl,
                            pausen=gruppe.pausen if len(berechnungen) == 2 else [],  # Pausen nur bei erster Gruppe
                            netto_stunden=stunden_einzeln,
                            gesamt_stunden=gesamt_stunden,
                            berechnung=f"{anzahl}*{stunden_einzeln}={gesamt_stunden}"
                        )
                        neue_gruppen.append(neue_gruppe)
                    except ValueError:
                        continue
            else:
                # Nur eine Berechnung - behalte ursprüngliche Gruppe
                neue_gruppen.append(gruppe)
        
        return neue_gruppen

    def _gruppe_erstellen_aus_info(self, gruppe_info: Dict, eintrag: Arbeitseintrag, pausen: List[Pausenzeit]) -> Optional[Arbeitergruppe]:
        """Erstelle Arbeitergruppe aus gesammelten Informationen."""
        try:
            anzahl = gruppe_info['anzahl']
            berechnung_zeilen = gruppe_info.get('berechnung_zeilen', [])
            
            # Kombiniere alle Berechnungszeilen
            berechnung_text = ' '.join(berechnung_zeilen)
            
            # Berechne Netto-Stunden basierend auf Pausen für diese Gruppe
            netto_stunden = self._arbeitsdauer_berechnen_basis(
                eintrag.arbeitsbeginn, 
                eintrag.arbeitsende, 
                pausen
            )
            
            gesamt_stunden = netto_stunden * anzahl
            
            # Versuche exakte Werte aus Berechnung zu extrahieren falls vorhanden
            if berechnung_text:
                # Suche erste passende Berechnung für diese Gruppe
                berechnung_match = re.search(r'(\d+)\s*[*×]\s*(\d+(?:[,.:]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,.:]\d+)?)', berechnung_text)
                if berechnung_match:
                    try:
                        calc_anzahl = int(berechnung_match.group(1))
                        calc_einzeln = float(berechnung_match.group(2).replace(',', '.'))
                        calc_gesamt = float(berechnung_match.group(3).replace(',', '.'))
                        
                        # Nutze berechnete Werte wenn sie zu dieser Gruppe passen
                        if calc_anzahl == anzahl:
                            netto_stunden = calc_einzeln
                            gesamt_stunden = calc_gesamt
                    except ValueError:
                        pass
            
            return Arbeitergruppe(
                anzahl=anzahl,
                pausen=pausen[:],  # Kopie der Pausen für diese Gruppe
                netto_stunden=netto_stunden,
                gesamt_stunden=gesamt_stunden,
                berechnung=berechnung_text
            )
        except:
            return None

    def _gruppe_aus_dict_erstellen(self, gruppe_dict: Dict, eintrag: Arbeitseintrag) -> Optional[Arbeitergruppe]:
        """Erstelle Arbeitergruppe aus Dictionary."""
        try:
            anzahl = gruppe_dict['anzahl']
            pausen = gruppe_dict.get('pausen', [])
            berechnung = gruppe_dict.get('berechnung', '')
            
            # Berechne Netto-Stunden
            netto_stunden = self._arbeitsdauer_berechnen_basis(
                eintrag.arbeitsbeginn, 
                eintrag.arbeitsende, 
                pausen
            )
            
            # Versuche Stunden aus Berechnung zu extrahieren (z.B. "3*9,5=28,5")
            gesamt_stunden = netto_stunden * anzahl
            if berechnung:
                berechnung_match = re.search(r'(\d+)\s*[*×]\s*(\d+(?:[,.:]\d+)?)\s*(?:Std\.?|h|st)?\s*=\s*(\d+(?:[,.:]\d+)?)', berechnung)
                if berechnung_match:
                    try:
                        calc_gesamt = float(berechnung_match.group(3).replace(',', '.'))
                        calc_einzeln = float(berechnung_match.group(2).replace(',', '.'))
                        gesamt_stunden = calc_gesamt
                        netto_stunden = calc_einzeln
                    except ValueError:
                        pass
            
            return Arbeitergruppe(
                anzahl=anzahl,
                pausen=pausen,
                netto_stunden=netto_stunden,
                gesamt_stunden=gesamt_stunden,
                berechnung=berechnung
            )
        except:
            return None

    def _einfache_gruppe_erstellen(self, zeilen: List[str], eintrag: Arbeitseintrag) -> List[Arbeitergruppe]:
        """Erstelle eine einfache Arbeitergruppe als Fallback."""
        # Suche nach Mitarbeiteranzahl
        mitarbeiteranzahl = 1
        berechnung = ""
        
        for zeile in zeilen:
            ma = self._mitarbeiteranzahl_extrahieren(zeile)
            if ma:
                mitarbeiteranzahl = ma
                
            if '*' in zeile and '=' in zeile:
                berechnung = zeile
                break
        
        netto_stunden = self._arbeitsdauer_berechnen_basis(eintrag.arbeitsbeginn, eintrag.arbeitsende, [])
        
        gruppe = Arbeitergruppe(
            anzahl=mitarbeiteranzahl,
            pausen=[],
            netto_stunden=netto_stunden,
            gesamt_stunden=netto_stunden * mitarbeiteranzahl,
            berechnung=berechnung
        )
        
        return [gruppe]

    def _arbeitsdauer_berechnen_basis(self, start: str, ende: str, pausen: List[Pausenzeit]) -> float:
        """Basis-Berechnung für Arbeitsdauer minus Pausen."""
        if not start or not ende:
            return 0.0
            
        try:
            start_teile = start.split(':')
            ende_teile = ende.split(':')
            
            start_minuten = int(start_teile[0]) * 60 + int(start_teile[1])
            ende_minuten = int(ende_teile[0]) * 60 + int(ende_teile[1])
            
            gesamt_minuten = ende_minuten - start_minuten
            
            # Pausen abziehen
            pausen_minuten = sum(p.dauer_minuten for p in pausen)
            arbeits_minuten = gesamt_minuten - pausen_minuten
            
            return round(arbeits_minuten / 60.0, 1)
        except:
            return 0.0

    def _zeile_in_eintrag_parsen(self, zeile: str, eintrag: Arbeitseintrag):
        """Parse verschiedene Felder aus einer Zeile in den Arbeitseintrag."""
        zeile_klein = zeile.lower()
        
        # Spezielle Behandlung für "keine Pause"
        if 'pause' in zeile_klein and 'kein' in zeile_klein:
            return
        
        # Arbeitszeit-Bereich
        if 'arbeitsbeginn' in zeile_klein:
            zeiten = self._zeitbereich_extrahieren(zeile)
            if zeiten:
                eintrag.arbeitsbeginn, eintrag.arbeitsende = zeiten
        # Andere Zeitbereiche nur wenn noch keine Arbeitszeit gefunden
        elif not eintrag.arbeitsbeginn and any(p in zeile_klein for p in ['uhr', ':', '-']) and not 'pause' in zeile_klein:
            zeiten = self._zeitbereich_extrahieren(zeile)
            if zeiten:
                eintrag.arbeitsbeginn, eintrag.arbeitsende = zeiten

        # Gesamtstunden extrahieren (wichtig für einfache Fälle!) - ÜBERSCHREIBE mit späteren Werten
        gesamtstunden = self._gesamtstunden_extrahieren(zeile)
        if gesamtstunden:  # Immer aktualisieren, spätere Werte überschreiben frühere
            eintrag.gesamtstunden = gesamtstunden
            eintrag.urspruengliche_berechnung = zeile
                
        # Notizen/Aufgaben (Leistung)
        if 'leistung' in zeile_klein or any(wort in zeile_klein for wort in ['entfernen', 'entsorgt', 'geschliffen', 'sauber', 'geholfen']):
            if eintrag.notizen:
                eintrag.notizen += "; " + zeile
            else:
                eintrag.notizen = zeile

    def _zeitbereich_extrahieren(self, zeile: str) -> Optional[Tuple[str, str]]:
        """Extrahiere Start- und Endzeit aus Zeile."""
        for muster in self.zeitbereich_muster:
            match = re.search(muster, zeile)
            if match:
                gruppen = match.groups()
                if len(gruppen) == 4:
                    # Format: HH:MM-HH:MM oder HH.MM-HH.MM
                    start = f"{gruppen[0].zfill(2)}:{gruppen[1]}"
                    ende = f"{gruppen[2].zfill(2)}:{gruppen[3]}"
                    return start, ende
                elif len(gruppen) == 3:
                    # Mixed formats: H:MM-H oder H-H:MM
                    if ':' in gruppen[1] or '.' in gruppen[1]:
                        # Start hat Minuten, Ende nicht: HH:MM-HH
                        start = f"{gruppen[0].zfill(2)}:{gruppen[1]}"
                        ende = f"{gruppen[2].zfill(2)}:00"
                    else:
                        # Start hat keine Minuten, Ende hat: HH-HH:MM  
                        start = f"{gruppen[0].zfill(2)}:00"
                        ende = f"{gruppen[1].zfill(2)}:{gruppen[2]}"
                    return start, ende
                elif len(gruppen) == 2:
                    # Einfache Stundenbereiche: H-H
                    start = f"{gruppen[0].zfill(2)}:00"
                    ende = f"{gruppen[1].zfill(2)}:00"
                    return start, ende
        return None

    def _pausen_extrahieren(self, zeile: str) -> List[Pausenzeit]:
        """Extrahiere Pausenzeiten aus Zeile."""
        pausen = []
        bereits_gefunden = set()  # Vermeide Duplikate
        
        # Bereinige die Eingabe
        zeile_bereinigt = re.sub(r'\s+', ' ', zeile.strip())
        
        # Spezifisches Muster für mehrzeilige Pausen
        # Beispiel: "Pause 10:00-10:30 12:00-12:30"
        alle_zeitbereiche = re.findall(r'(\d{1,2})[:.:]?(\d{2})?\s*[-–]\s*(\d{1,2})[:.:]?(\d{2})?', zeile_bereinigt)
        
        for match in alle_zeitbereiche:
            try:
                start_std = int(match[0])
                start_min = int(match[1]) if match[1] else 0
                ende_std = int(match[2])
                ende_min = int(match[3]) if match[3] else 0
                
                start = f"{start_std:02d}:{start_min:02d}"
                ende = f"{ende_std:02d}:{ende_min:02d}"
                
                # Prüfe auf Duplikate
                pause_key = f"{start}-{ende}"
                if pause_key in bereits_gefunden:
                    continue
                bereits_gefunden.add(pause_key)
                
                # Berechne Dauer
                start_minuten = start_std * 60 + start_min
                ende_minuten = ende_std * 60 + ende_min
                dauer = ende_minuten - start_minuten
                
                if dauer > 0 and dauer < 600:  # Sinnvolle Pausendauer (max 10h)
                    pausen.append(Pausenzeit(
                        beginn=start,
                        ende=ende,
                        dauer_minuten=dauer
                    ))
                    
            except (ValueError, IndexError):
                continue
                        
        return pausen

    def _mitarbeiteranzahl_extrahieren(self, zeile: str) -> Optional[int]:
        """Extrahiere Anzahl der Mitarbeiter aus Zeile."""
        # Deutsche Zahlwörter in Ziffern umwandeln (z.B. "Zwei man" → "2 man")
        zeile_norm = zeile
        zeile_klein = zeile.lower()
        for wort, ziffer in self._zahlwoerter.items():
            zeile_klein = re.sub(r'\b' + wort + r'\b', ziffer, zeile_klein)
        # Ziffern aus normalisierter Kleinbuchstaben-Version extrahieren
        for muster in self.mitarbeiter_muster:
            match = re.search(muster, zeile_klein)
            if not match:
                match = re.search(muster, zeile_norm)  # Fallback auf Original für Großschreibung
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    def _gesamtstunden_extrahieren(self, zeile: str) -> Optional[float]:
        """Extrahiere Gesamtstunden aus Zeile."""
        for muster in self.gesamtstunden_muster:
            match = re.search(muster, zeile, re.IGNORECASE)  # Case-insensitive matching
            if match:
                try:
                    # Behandle verschiedene Berechnungsformate
                    gruppen = match.groups()
                    
                    # Spezielle Behandlung für Zeitformat "Zusammen 17:40"
                    if len(gruppen) == 2 and ':' not in str(gruppen[0]):
                        # Das ist wahrscheinlich Stunden:Minuten Format
                        stunden = int(gruppen[0])
                        minuten = int(gruppen[1]) 
                        return stunden + minuten / 60.0
                        
                    if len(gruppen) == 3:
                        # Format: 3*9=27 oder 3*9,5=28,5
                        return float(gruppen[2].replace(',', '.').replace(':', '.'))
                    elif len(gruppen) == 4:
                        # Format: 1 man 1*10=10 (mehrzeiliges Format)
                        return float(gruppen[3].replace(',', '.').replace(':', '.'))
                    else:
                        # Einfaches Format: Insgesamt 9 oder 27 Arbeitsstunden
                        wert = gruppen[0].replace(',', '.').replace(':', '.')
                        
                        # Handle time format like "17:40" as hours  
                        if ':' in gruppen[0] and len(gruppen[0]) <= 5:
                            teile = gruppen[0].split(':')
                            if len(teile) == 2:
                                try:
                                    stunden = int(teile[0])
                                    minuten = int(teile[1])
                                    return stunden + minuten / 60.0
                                except ValueError:
                                    pass
                        
                        return float(wert)
                except (ValueError, IndexError):
                    continue
        return None

    def eintrag_validieren(self, eintrag: Arbeitseintrag) -> List[Validierungsproblem]:
        """Validiere einen Arbeitseintrag und gib gefundene Probleme zurück."""
        probleme = []
        
        # === TIME-RELATED ANOMALIES ===
        
        # 1. Missing start time - Only end time provided
        if not eintrag.arbeitsbeginn and eintrag.arbeitsende:
            probleme.append(Validierungsproblem(
                typ='fehlende_daten',
                schweregrad='kritisch',
                nachricht='Nur Endzeit gefunden, Startzeit fehlt',
                feld='arbeitsbeginn',
                erwartet='HH:MM Format',
                tatsaechlich='Leer'
            ))
            
        # 2. Missing end time - Only start time provided  
        if eintrag.arbeitsbeginn and not eintrag.arbeitsende:
            probleme.append(Validierungsproblem(
                typ='fehlende_daten',
                schweregrad='kritisch',
                nachricht='Nur Startzeit gefunden, Endzeit fehlt',
                feld='arbeitsende',
                erwartet='HH:MM Format',
                tatsaechlich='Leer'
            ))
            
        # 3. Invalid time format - Check if times are valid
        if eintrag.arbeitsbeginn:
            if not self._ist_gueltige_zeit(eintrag.arbeitsbeginn):
                probleme.append(Validierungsproblem(
                    typ='datenformat_fehler',
                    schweregrad='kritisch',
                    nachricht=f'Ungültiges Startzeit-Format: {eintrag.arbeitsbeginn}',
                    feld='arbeitsbeginn',
                    erwartet='HH:MM (00:00-23:59)',
                    tatsaechlich=eintrag.arbeitsbeginn
                ))
                
        if eintrag.arbeitsende:
            if not self._ist_gueltige_zeit(eintrag.arbeitsende):
                probleme.append(Validierungsproblem(
                    typ='datenformat_fehler',
                    schweregrad='kritisch',
                    nachricht=f'Ungültiges Endzeit-Format: {eintrag.arbeitsende}',
                    feld='arbeitsende',
                    erwartet='HH:MM (00:00-23:59)',
                    tatsaechlich=eintrag.arbeitsende
                ))

        # === PAUSE-RELATED ANOMALIES ===
        
        for gruppe in eintrag.arbeitergruppen:
            for pause in gruppe.pausen:
                # 4. Pause outside work hours
                if eintrag.arbeitsbeginn and eintrag.arbeitsende:
                    if not self._ist_pause_in_arbeitszeit(pause, eintrag.arbeitsbeginn, eintrag.arbeitsende):
                        probleme.append(Validierungsproblem(
                            typ='zeit_anomalie',
                            schweregrad='warnung',
                            nachricht=f'Pause {pause.beginn}–{pause.ende} liegt außerhalb Arbeitszeit {eintrag.arbeitsbeginn}–{eintrag.arbeitsende}',
                            feld='pausen',
                            erwartet='Pausen innerhalb Arbeitszeit',
                            tatsaechlich=f'{pause.beginn}–{pause.ende}'
                        ))
                
                # 5. Pause end before pause start
                if not self._ist_zeitbereich_logisch(pause.beginn, pause.ende):
                    probleme.append(Validierungsproblem(
                        typ='zeit_anomalie',
                        schweregrad='kritisch',
                        nachricht=f'Pause-Endzeit vor Startzeit: {pause.beginn}–{pause.ende}',
                        feld='pausen',
                        erwartet='Endzeit nach Startzeit',
                        tatsaechlich=f'{pause.beginn}–{pause.ende}'
                    ))
                    
                # 6. Invalid pause format validation
                if not self._ist_gueltige_zeit(pause.beginn) or not self._ist_gueltige_zeit(pause.ende):
                    probleme.append(Validierungsproblem(
                        typ='datenformat_fehler',
                        schweregrad='kritisch',
                        nachricht=f'Ungültiges Pausenzeit-Format: {pause.beginn}–{pause.ende}',
                        feld='pausen',
                        erwartet='HH:MM–HH:MM',
                        tatsaechlich=f'{pause.beginn}–{pause.ende}'
                    ))
            
            # 7. Pause longer than work shift
            if eintrag.arbeitsbeginn and eintrag.arbeitsende and gruppe.pausen:
                gesamt_pausen_dauer = sum(self._pause_dauer_berechnen(p) for p in gruppe.pausen)
                schicht_dauer = self._zeitdauer_berechnen(eintrag.arbeitsbeginn, eintrag.arbeitsende)
                
                if gesamt_pausen_dauer >= schicht_dauer:
                    probleme.append(Validierungsproblem(
                        typ='zeit_anomalie',
                        schweregrad='kritisch',
                        nachricht=f'Pausendauer ({gesamt_pausen_dauer:.1f}h) >= Schichtdauer ({schicht_dauer:.1f}h)',
                        feld='pausen',
                        erwartet='Pausen < Arbeitszeit',
                        tatsaechlich=f'{gesamt_pausen_dauer:.1f}h Pausen'
                    ))
            
        # 8. Overlapping pauses — only check within a single-worker-group entry.
        # Multiple groups sharing the same break time is normal and expected.
        if len(eintrag.arbeitergruppen) == 1:
            ueberlappende_pausen = self._finde_ueberlappende_pausen(eintrag.arbeitergruppen[0].pausen)
            if ueberlappende_pausen:
                probleme.append(Validierungsproblem(
                    typ='zeit_anomalie',
                    schweregrad='warnung',
                    nachricht=f'Überlappende Pausen: {", ".join(ueberlappende_pausen)}',
                    feld='pausen',
                    erwartet='Keine überlappenden Pausen',
                    tatsaechlich=', '.join(ueberlappende_pausen)
                ))

        # === DATE-RELATED ANOMALIES ===
        
        # 9. Missing date (already implemented)
        if not eintrag.datum:
            probleme.append(Validierungsproblem(
                typ='fehlende_daten',
                schweregrad='kritisch',
                nachricht='Datum fehlt oder konnte nicht extrahiert werden - VERDÄCHTIG!',
                feld='datum',
                erwartet='YYYY-MM-DD',
                tatsaechlich=eintrag.datum
            ))
            
        # 10. Invalid date formats
        if eintrag.datum and not self._ist_gueltiges_datum(eintrag.datum):
            probleme.append(Validierungsproblem(
                typ='datenformat_fehler',
                schweregrad='kritisch',
                nachricht=f'Ungültiges Datumsformat: {eintrag.datum}',
                feld='datum',
                erwartet='YYYY-MM-DD oder DD.MM.YYYY',
                tatsaechlich=eintrag.datum
            ))
        
        # === WORKER COUNT ANOMALIES ===
        
        # 11. Zero workers
        if eintrag.gesamt_mitarbeiter <= 0:
            probleme.append(Validierungsproblem(
                typ='daten_anomalie',
                schweregrad='kritisch',
                nachricht=f'Keine oder ungültige Mitarbeiteranzahl: {eintrag.gesamt_mitarbeiter}',
                feld='mitarbeiteranzahl',
                erwartet='Mindestens 1 Mitarbeiter',
                tatsaechlich=str(eintrag.gesamt_mitarbeiter)
            ))
            
        # 12. Excessive worker count
        if eintrag.gesamt_mitarbeiter > 15:
            probleme.append(Validierungsproblem(
                typ='daten_anomalie',
                schweregrad='warnung',
                nachricht=f'Ungewöhnlich hohe Mitarbeiteranzahl: {eintrag.gesamt_mitarbeiter}',
                feld='mitarbeiteranzahl',
                erwartet='1-15 Mitarbeiter',
                tatsaechlich=str(eintrag.gesamt_mitarbeiter)
            ))
            
        # 13. Fractional workers (this would be caught in parsing, but double check)
        for gruppe in eintrag.arbeitergruppen:
            if gruppe.anzahl != int(gruppe.anzahl):
                probleme.append(Validierungsproblem(
                    typ='daten_anomalie',
                    schweregrad='kritisch',
                    nachricht=f'Bruchteile von Mitarbeitern nicht möglich: {gruppe.anzahl}',
                    feld='mitarbeiteranzahl',
                    erwartet='Ganze Zahlen',
                    tatsaechlich=str(gruppe.anzahl)
                ))

        # === CALCULATION ANOMALIES ===
        
        # 14. Math errors in calculations
        for gruppe in eintrag.arbeitergruppen:
            if gruppe.berechnung and '*' in gruppe.berechnung and '=' in gruppe.berechnung:
                rechenfehler = self._pruefe_rechnung(gruppe.berechnung)
                if rechenfehler:
                    probleme.append(Validierungsproblem(
                        typ='berechnungsabweichung',
                        schweregrad='warnung',
                        nachricht=f'Rechenfehler in Berechnung: {gruppe.berechnung} {rechenfehler}',
                        feld='berechnung',
                        erwartet='Korrekte Mathematik',
                        tatsaechlich=gruppe.berechnung
                    ))

        # 15. Total hours mismatch — compare contractor's stated total vs calculated
        if eintrag.arbeitergruppen:
            berechnete_summe = sum(g.gesamt_stunden for g in eintrag.arbeitergruppen)
            stated = eintrag.angegebene_gesamtstunden
            if stated > 0 and abs(berechnete_summe - stated) >= 0.1:
                probleme.append(Validierungsproblem(
                    typ='berechnungsabweichung',
                    schweregrad='warnung',
                    nachricht=f'Angegebene Stunden ({round(stated, 2)}h) weichen von Berechnung ({round(berechnete_summe, 2)}h) ab – berechneter Wert wurde verwendet',
                    feld='gesamtstunden',
                    erwartet=str(round(berechnete_summe, 2)),
                    tatsaechlich=str(round(stated, 2))
                ))
                
        # 16. Impossible hourly totals
        if eintrag.gesamtstunden > (eintrag.gesamt_mitarbeiter * 24):
            probleme.append(Validierungsproblem(
                typ='zeit_anomalie',
                schweregrad='kritisch',
                nachricht=f'Unmögliche Gesamtstunden: {eintrag.gesamtstunden}h für {eintrag.gesamt_mitarbeiter} Mitarbeiter (max: {eintrag.gesamt_mitarbeiter * 24}h)',
                feld='gesamtstunden',
                erwartet=f'Maximal {eintrag.gesamt_mitarbeiter * 24}h',
                tatsaechlich=f'{eintrag.gesamtstunden}h'
            ))
            
        # 17. Missing calculation basis
        if eintrag.gesamtstunden > 0 and not any(g.gesamt_stunden > 0 for g in eintrag.arbeitergruppen):
            probleme.append(Validierungsproblem(
                typ='fehlende_daten',
                schweregrad='warnung',
                nachricht='Gesamtstunden angegeben aber keine Berechnung/Aufschlüsselung gefunden',
                feld='berechnung',
                erwartet='Aufschlüsselung der Stunden',
                tatsaechlich='Keine Details'
            ))

        # === EXISTING LONG SHIFT CHECK ===
        # Zeitanomalie-Prüfungen (existing)
        if eintrag.arbeitsbeginn and eintrag.arbeitsende:
            # Prüfe längste Schicht aller Gruppen
            for gruppe in eintrag.arbeitergruppen:
                if gruppe.netto_stunden > 12:
                    probleme.append(Validierungsproblem(
                        typ='zeit_anomalie',
                        schweregrad='warnung',
                        nachricht=f'Ungewöhnlich lange Schicht für Gruppe: {gruppe.netto_stunden} Stunden',
                        feld='dauer',
                        erwartet='<12 Stunden',
                        tatsaechlich=f'{gruppe.netto_stunden} Stunden'
                    ))

        # Fehlende Daten prüfen (existing but improved)
        if not eintrag.projekt:
            probleme.append(Validierungsproblem(
                typ='fehlende_daten',
                schweregrad='fehler',
                nachricht='Projektname nicht gefunden',
                feld='projekt',
                erwartet='Projektname',
                tatsaechlich='Leer'
            ))
            
        return probleme
    
    def _ist_gueltige_zeit(self, zeit_str: str) -> bool:
        """Prüfe ob Zeitstring gültig ist (HH:MM, 00:00-23:59)."""
        if not zeit_str:
            return False
        
        # Entferne Leerzeichen und normalisiere
        zeit_str = zeit_str.strip().replace('.', ':')
        
        # Prüfe Format HH:MM
        if ':' not in zeit_str:
            return False
            
        try:
            teile = zeit_str.split(':')
            if len(teile) != 2:
                return False
                
            stunden = int(teile[0])
            minuten = int(teile[1])
            
            # Prüfe Gültigkeit
            return 0 <= stunden <= 23 and 0 <= minuten <= 59
            
        except ValueError:
            return False
    
    def _ist_pause_in_arbeitszeit(self, pause: Pausenzeit, start: str, ende: str) -> bool:
        """Prüfe ob Pause innerhalb der Arbeitszeit liegt."""
        try:
            def zeit_zu_minuten(zeit_str: str) -> int:
                teile = zeit_str.replace('.', ':').split(':')
                return int(teile[0]) * 60 + int(teile[1])
            
            start_min = zeit_zu_minuten(start)
            ende_min = zeit_zu_minuten(ende)
            pause_start_min = zeit_zu_minuten(pause.beginn)
            pause_ende_min = zeit_zu_minuten(pause.ende)
            
            # Berücksichtige Nachtschicht (über Mitternacht)
            if ende_min < start_min:
                ende_min += 24 * 60
                if pause_start_min < start_min:
                    pause_start_min += 24 * 60
                if pause_ende_min < start_min:
                    pause_ende_min += 24 * 60
            
            return start_min <= pause_start_min and pause_ende_min <= ende_min
            
        except (ValueError, IndexError):
            return False
    
    def _ist_zeitbereich_logisch(self, start: str, ende: str) -> bool:
        """Prüfe ob Zeitbereich logisch ist (Ende nach Start)."""
        try:
            def zeit_zu_minuten(zeit_str: str) -> int:
                teile = zeit_str.replace('.', ':').split(':')
                return int(teile[0]) * 60 + int(teile[1])
            
            start_min = zeit_zu_minuten(start)
            ende_min = zeit_zu_minuten(ende)
            
            # Nachtschicht über Mitternacht ist erlaubt
            if ende_min < start_min:
                return True  # Könnte Nachtschicht sein
            
            return ende_min > start_min
            
        except (ValueError, IndexError):
            return False
    
    def _pause_dauer_berechnen(self, pause: Pausenzeit) -> float:
        """Berechne Pausendauer in Stunden."""
        try:
            def zeit_zu_minuten(zeit_str: str) -> int:
                teile = zeit_str.replace('.', ':').split(':')
                return int(teile[0]) * 60 + int(teile[1])
            
            start_min = zeit_zu_minuten(pause.beginn)
            ende_min = zeit_zu_minuten(pause.ende)
            
            if ende_min < start_min:
                ende_min += 24 * 60  # Nachtschicht
                
            return (ende_min - start_min) / 60.0
            
        except (ValueError, IndexError):
            return 0.0
    
    def _zeitdauer_berechnen(self, start: str, ende: str) -> float:
        """Berechne Zeitdauer zwischen zwei Zeiten in Stunden."""
        try:
            def zeit_zu_minuten(zeit_str: str) -> int:
                teile = zeit_str.replace('.', ':').split(':')
                return int(teile[0]) * 60 + int(teile[1])
            
            start_min = zeit_zu_minuten(start)
            ende_min = zeit_zu_minuten(ende)
            
            if ende_min < start_min:
                ende_min += 24 * 60  # Nachtschicht
                
            return (ende_min - start_min) / 60.0
            
        except (ValueError, IndexError):
            return 0.0
    
    def _finde_ueberlappende_pausen(self, pausen: List[Pausenzeit]) -> List[str]:
        """Finde überlappende Pausen und gib Beschreibungen zurück."""
        if len(pausen) < 2:
            return []
        
        ueberlappungen = []
        
        try:
            def zeit_zu_minuten(zeit_str: str) -> int:
                teile = zeit_str.replace('.', ':').split(':')
                return int(teile[0]) * 60 + int(teile[1])
            
            for i, pause1 in enumerate(pausen):
                for j, pause2 in enumerate(pausen[i+1:], i+1):
                    p1_start = zeit_zu_minuten(pause1.beginn)
                    p1_ende = zeit_zu_minuten(pause1.ende)
                    p2_start = zeit_zu_minuten(pause2.beginn)
                    p2_ende = zeit_zu_minuten(pause2.ende)
                    
                    # Prüfe Überlappung
                    if (p1_start < p2_ende and p1_ende > p2_start):
                        ueberlappungen.append(f"{pause1.beginn}–{pause1.ende} ↔ {pause2.beginn}–{pause2.ende}")
            
            return ueberlappungen
            
        except (ValueError, IndexError):
            return []
    
    def _ist_gueltiges_datum(self, datum_str: str) -> bool:
        """Prüfe ob Datum gültig ist."""
        if not datum_str:
            return False
            
        try:
            # Prüfe YYYY-MM-DD Format
            if len(datum_str) == 10 and datum_str.count('-') == 2:
                jahr, monat, tag = datum_str.split('-')
                jahr, monat, tag = int(jahr), int(monat), int(tag)
                
                # Basis-Validierung
                if not (1900 <= jahr <= 2100 and 1 <= monat <= 12 and 1 <= tag <= 31):
                    return False
                
                # Monatsspezifische Validierung
                if monat in [4, 6, 9, 11] and tag > 30:
                    return False
                elif monat == 2:
                    ist_schaltjahr = (jahr % 4 == 0 and jahr % 100 != 0) or (jahr % 400 == 0)
                    if tag > (29 if ist_schaltjahr else 28):
                        return False
                        
                return True
                
        except (ValueError, IndexError):
            pass
            
        return False
    
    def _pruefe_rechnung(self, berechnung: str) -> str:
        """Prüfe mathematische Berechnung und gib Fehlerbeschreibung zurück."""
        if not berechnung or '*' not in berechnung or '=' not in berechnung:
            return ""
        
        try:
            # Parse "3*8=24" Format
            teile = berechnung.split('=')
            if len(teile) != 2:
                return ""
            
            linke_seite = teile[0].strip()
            rechte_seite = float(teile[1].strip().replace(',', '.'))
            
            # Parse Multiplikation
            if '*' in linke_seite:
                faktoren = linke_seite.split('*')
                if len(faktoren) == 2:
                    faktor1 = float(faktoren[0].strip().replace(',', '.'))
                    faktor2 = float(faktoren[1].strip().replace(',', '.'))
                    
                    erwartetes_ergebnis = faktor1 * faktor2
                    
                    if abs(erwartetes_ergebnis - rechte_seite) > 0.1:
                        return f"(korrekt wäre: {erwartetes_ergebnis})"
            
        except (ValueError, IndexError):
            return "(konnte nicht validiert werden)"
            
        return ""
    
    def _duplikate_pruefen(self, alle_eintraege: List[Arbeitseintrag]) -> None:
        """Prüfe auf Duplikate - gleiche Datum/Projekt/Arbeitszeiten und markiere als verdächtig."""
        for i, eintrag1 in enumerate(alle_eintraege):
            for j, eintrag2 in enumerate(alle_eintraege[i+1:], i+1):
                # Prüfe auf Duplikat: gleiches Datum, Projekt und Arbeitszeiten
                if (eintrag1.datum == eintrag2.datum and 
                    eintrag1.projekt == eintrag2.projekt and
                    eintrag1.arbeitsbeginn == eintrag2.arbeitsbeginn and 
                    eintrag1.arbeitsende == eintrag2.arbeitsende):
                    
                    # Füge Validierungsproblem zu beiden Einträgen hinzu
                    duplikat_problem = Validierungsproblem(
                        typ='daten_anomalie',
                        schweregrad='kritisch',
                        nachricht=f'Doppelter Eintrag erkannt: {eintrag1.projekt} am {eintrag1.datum} ({eintrag1.arbeitsbeginn}–{eintrag1.arbeitsende})',
                        feld='duplikat',
                        erwartet='Eindeutige Einträge',
                        tatsaechlich='Doppelt vorhanden'
                    )
                    
                    # Füge Problem zu beiden Einträgen hinzu
                    if not eintrag1.validierungsprobleme:
                        eintrag1.validierungsprobleme = []
                    eintrag1.validierungsprobleme.append(duplikat_problem)
                    
                    if not eintrag2.validierungsprobleme:
                        eintrag2.validierungsprobleme = []
                    eintrag2.validierungsprobleme.append(duplikat_problem)

    def _arbeitsdauer_berechnen(self, eintrag: Arbeitseintrag) -> float:
        """Berechne Arbeitsdauer minus Pausen."""
        if not eintrag.arbeitsbeginn or not eintrag.arbeitsende:
            return 0.0
            
        try:
            start_teile = eintrag.arbeitsbeginn.split(':')
            ende_teile = eintrag.arbeitsende.split(':')
            
            start_minuten = int(start_teile[0]) * 60 + int(start_teile[1])
            ende_minuten = int(ende_teile[0]) * 60 + int(ende_teile[1])
            
            gesamt_minuten = ende_minuten - start_minuten
            
            # Pausen abziehen
            pausen_minuten = sum(p.dauer_minuten for p in eintrag.pausen)
            arbeits_minuten = gesamt_minuten - pausen_minuten
            
            return arbeits_minuten / 60.0
        except:
            return 0.0


def main():
    """CLI-Schnittstelle zum Testen des Parsers."""
    import sys
    
    if len(sys.argv) < 2:
        print("Verwendung: python message_parser.py <nachrichten_text>")
        sys.exit(1)
        
    nachricht = sys.argv[1]
    parser = DeutscherNachrichtenParser()
    
    eintraege = parser.nachricht_parsen(nachricht)
    
    for eintrag in eintraege:
        print(f"\\n=== Arbeitseintrag ===")
        print(f"Datum: {eintrag.datum}")
        print(f"Projekt: {eintrag.projekt}")
        print(f"Arbeitszeit: {eintrag.arbeitsbeginn} - {eintrag.arbeitsende}")
        
        # Zeige Arbeitergruppen
        if len(eintrag.arbeitergruppen) > 1:
            print(f"\\n--- Arbeitergruppen ({len(eintrag.arbeitergruppen)}) ---")
            for i, gruppe in enumerate(eintrag.arbeitergruppen, 1):
                print(f"Gruppe {i}: {gruppe.anzahl} Mitarbeiter")
                if gruppe.pausen:
                    gesamte_pausenstunden = sum(p.dauer_minuten for p in gruppe.pausen) / 60
                    print(f"  Pausen: {gesamte_pausenstunden:.1f} Std.")
                    for j, pause in enumerate(gruppe.pausen, 1):
                        pause_std = pause.dauer_minuten / 60
                        print(f"    Pause {j}: {pause.beginn} - {pause.ende} ({pause_std:.1f} Std.)")
                else:
                    print(f"  Pausen: 0 Std.")
                    
                print(f"  Netto-Arbeitszeit pro Person: {gruppe.netto_stunden:.1f} Std.")
                print(f"  Gesamtstunden Gruppe: {gruppe.gesamt_stunden:.1f} Std.")
                if gruppe.berechnung:
                    print(f"  Berechnung: {gruppe.berechnung}")
                print()
        else:
            # Einzelne Gruppe - traditionelle Anzeige
            gruppe = eintrag.arbeitergruppen[0] if eintrag.arbeitergruppen else None
            if gruppe and gruppe.pausen:
                gesamte_pausenstunden = sum(p.dauer_minuten for p in gruppe.pausen) / 60
                print(f"Pausen gesamt: {gesamte_pausenstunden:.1f} Std.")
                for i, pause in enumerate(gruppe.pausen, 1):
                    pause_std = pause.dauer_minuten / 60
                    print(f"  Pause {i}: {pause.beginn} - {pause.ende} ({pause_std:.1f} Std.)")
            else:
                print("Pausen gesamt: 0 Std.")
            
        print(f"Gesamt-Mitarbeiter: {eintrag.gesamt_mitarbeiter}")
        
        # Berechne und zeige durchschnittliche Netto-Arbeitszeit
        if eintrag.arbeitergruppen:
            if len(eintrag.arbeitergruppen) == 1:
                netto_arbeitszeit = eintrag.arbeitergruppen[0].netto_stunden
                print(f"Netto-Arbeitszeit pro Person: {netto_arbeitszeit:.1f} Std.")
            else:
                # Bei mehreren Gruppen zeige gewichteten Durchschnitt
                total_person_stunden = sum(g.anzahl * g.netto_stunden for g in eintrag.arbeitergruppen)
                durchschnitt = total_person_stunden / eintrag.gesamt_mitarbeiter
                print(f"Durchschnittliche Netto-Arbeitszeit: {durchschnitt:.1f} Std.")
        
        print(f"Gesamtstunden alle Mitarbeiter: {eintrag.gesamtstunden:.1f} Std.")
        
        if eintrag.urspruengliche_berechnung:
            print(f"Ursprüngliche Berechnung: {eintrag.urspruengliche_berechnung}")
        
        if eintrag.notizen:
            print(f"Notizen: {eintrag.notizen}")
        
        # Validierung
        probleme = parser.eintrag_validieren(eintrag)
        if probleme:
            print(f"\\n⚠️  Validierungsprobleme:")
            for problem in probleme:
                print(f"  - {problem.schweregrad.upper()}: {problem.nachricht}")


if __name__ == '__main__':
    main()