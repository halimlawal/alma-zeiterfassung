#!/usr/bin/env python3
"""
Deutscher Berichtsgenerator für Auftragnehmerstunden
Generiert strukturierte wöchentliche Berichte im deutschen Template-Format.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from dataclasses import dataclass
from message_parser import Arbeitseintrag, Pausenzeit, Arbeitergruppe, Validierungsproblem

@dataclass
class Wochenbericht:
    woche_start: str  # YYYY-MM-DD
    woche_ende: str   # YYYY-MM-DD
    projekt: str
    eintraege: List[Arbeitseintrag]
    gesamtstunden: float

class DeutscherBerichtsgenerator:
    def __init__(self):
        # Deutsche Wochentage
        self.wochentage = [
            'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 
            'Freitag', 'Samstag', 'Sonntag'
        ]
        
        # Deutsche Monate
        self.monate = [
            'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
            'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'
        ]

    def eintraege_nach_wochen_und_projekten_gruppieren(self, eintraege: List[Arbeitseintrag]) -> Dict[str, Dict[str, List[Arbeitseintrag]]]:
        """Gruppiere Arbeitseinträge nach Wochen UND Projekten (separate Berichte pro Projekt)."""
        wochen_projekt_gruppen = {}
        
        for eintrag in eintraege:
            woche_key = self._woche_berechnen(eintrag.datum)
            projekt = eintrag.projekt or "Unbekanntes Projekt"
            
            if woche_key not in wochen_projekt_gruppen:
                wochen_projekt_gruppen[woche_key] = {}
            
            if projekt not in wochen_projekt_gruppen[woche_key]:
                wochen_projekt_gruppen[woche_key][projekt] = []
                
            wochen_projekt_gruppen[woche_key][projekt].append(eintrag)
            
        return wochen_projekt_gruppen

    def _woche_berechnen(self, datum_str: str) -> str:
        """Berechne Wochenschlüssel (Samstag-Freitag) für ein Datum."""
        try:
            datum = datetime.strptime(datum_str, "%Y-%m-%d")
            # Finde den Samstag dieser Woche (Wochenbeginn)
            # weekday(): Montag=0, Sonntag=6
            tage_bis_samstag = (datum.weekday() + 2) % 7  # Samstag als Wochenbeginn
            woche_start = datum - timedelta(days=tage_bis_samstag)
            
            return woche_start.strftime("%Y-%m-%d")
        except ValueError:
            # Fallback auf aktuelles Datum
            return datetime.now().strftime("%Y-%m-%d")

    def wochenbericht_generieren(self, eintraege: List[Arbeitseintrag], woche_start: str, projekt: str = None) -> str:
        """Generiere einen Wochenbericht im deutschen Template-Format für ein spezifisches Projekt."""
        if not eintraege:
            return ""
            
        # Berechne Wochenende (Freitag)
        start_datum = datetime.strptime(woche_start, "%Y-%m-%d")
        ende_datum = start_datum + timedelta(days=6)  # Samstag bis Freitag = 6 Tage
        
        # Nutze übergebenes Projekt oder ermittle Hauptprojekt
        if not projekt:
            projekt = self._hauptprojekt_ermitteln(eintraege)
        
        # Sortiere Einträge nach Datum
        eintraege_sortiert = sorted(eintraege, key=lambda x: x.datum)
        
        # Beginne Bericht
        bericht = self._bericht_header_generieren(start_datum, ende_datum, projekt)
        
        # Generiere Einträge für jeden Tag
        gesamt_stunden = 0.0
        for i, eintrag in enumerate(eintraege_sortiert):
            tages_bericht = self._tages_eintrag_generieren(eintrag)
            bericht += tages_bericht
            gesamt_stunden += eintrag.gesamtstunden or 0.0
            
            # Füge Trennlinie hinzu (außer beim letzten Eintrag)
            if i < len(eintraege_sortiert) - 1:
                bericht += "⸻\n\n"

        # KW-Gesamtstunden am Ende des Berichts
        kw = start_datum.isocalendar()[1]
        start_str_kw = f"{start_datum.day:02d}.{start_datum.month:02d}"
        ende_str_kw = f"{ende_datum.day:02d}.{ende_datum.month:02d}"
        std_ganz = int(gesamt_stunden)
        minuten = int(round((gesamt_stunden - std_ganz) * 60))
        std_str = f"{std_ganz}h {minuten:02d}min" if minuten else f"{std_ganz}h"
        bericht += f"\n{'═' * 30}\n"
        bericht += f"Gesamt KW-{kw:02d} ({start_str_kw}–{ende_str_kw}): {std_str} Arbeitsstunden\n"
        
        return bericht

    def _hauptprojekt_ermitteln(self, eintraege: List[Arbeitseintrag]) -> str:
        """Ermittle das Hauptprojekt basierend auf Häufigkeit."""
        projekt_counter = {}
        for eintrag in eintraege:
            projekt = eintrag.projekt or "Unbekanntes Projekt"
            projekt_counter[projekt] = projekt_counter.get(projekt, 0) + 1
            
        if not projekt_counter:
            return "Unbekanntes Projekt"
            
        return max(projekt_counter.keys(), key=projekt_counter.get)

    def _bericht_header_generieren(self, start_datum: datetime, ende_datum: datetime, projekt: str) -> str:
        """Generiere Header im deutschen Format."""
        start_str = f"{start_datum.day:02d}.{start_datum.month:02d}"
        ende_str = f"{ende_datum.day:02d}.{ende_datum.month:02d}"
        
        header = "-" * 10 + "\n"
        header += f"Arbeitsstunden Übersicht der Woche  {start_str} - {ende_str}\n"
        header += f"Auftrag: {projekt}\n"
        header += "-" * 10 + "\n\n"
        
        return header

    def _tages_eintrag_generieren(self, eintrag: Arbeitseintrag) -> str:
        """Generiere Eintrag für einen einzelnen Tag im Template-Format - EXAKT wie template.txt."""
        try:
            if eintrag.datum:
                datum = datetime.strptime(eintrag.datum, "%Y-%m-%d")
                wochentag = self.wochentage[datum.weekday()]
                tag_monat = f"{datum.day:02d}.{datum.month:02d}.{datum.year}"
            else:
                # Fehlende Datum - markiere als verdächtig
                wochentag = "⚠️ UNBEKANNT"
                tag_monat = "⚠️ DATUM FEHLT - VERDÄCHTIG!"
        except ValueError:
            wochentag = "⚠️ UNGÜLTIG"
            tag_monat = f"⚠️ UNGÜLTIGES DATUM: {eintrag.datum}"
        
        eintrag_text = f"{wochentag}, {tag_monat}\n\n"
        
        # Zeige Validierungsprobleme/Anomalien falls vorhanden
        if eintrag.validierungsprobleme:
            eintrag_text += "⚠️ ANOMALIEN ERKANNT:\n"
            for problem in eintrag.validierungsprobleme:
                symbol = "🔴" if problem.schweregrad == "kritisch" else "🟡" if problem.schweregrad == "warnung" else "🔵"
                eintrag_text += f"{symbol} {problem.schweregrad.upper()}: {problem.nachricht}\n"
            eintrag_text += "\n"
        
        # Arbeitszeit
        if eintrag.arbeitsbeginn and eintrag.arbeitsende:
            eintrag_text += f"Arbeitszeit: {eintrag.arbeitsbeginn}–{eintrag.arbeitsende} Uhr\n"
        
        # Leistung (falls vorhanden) — entferne "Leistung:" Präfix falls bereits vorhanden
        if eintrag.notizen:
            leistung = re.sub(r'^[Ll]eistung\s*:\s*', '', eintrag.notizen.strip())
            eintrag_text += f"Leistung: {leistung}\n"
        
        # Unterscheide zwischen einfachen und komplexen Szenarien
        if len(eintrag.arbeitergruppen) <= 1:
            # Einfaches Szenario - traditionelles Format EXAKT wie Template
            eintrag_text += self._einfaches_format_generieren(eintrag)
        else:
            # Komplexes Multi-Group-Szenario - EXAKT wie Template  
            eintrag_text += "\n"  # Leerzeile nach "Arbeitszeit Baustelle:" wie im Template
            eintrag_text += self._komplexes_format_generieren(eintrag)
        
        # Tagesgesamt - summiere alle Arbeitergruppen für diesen Tag
        if eintrag.datum:
            try:
                datum = datetime.strptime(eintrag.datum, "%Y-%m-%d")
                tag_datum_kurz = f"{datum.day:02d}.{datum.month:02d}.{datum.year}"
            except ValueError:
                tag_datum_kurz = "⚠️ UNGÜLTIGES DATUM"
        else:
            tag_datum_kurz = "⚠️ DATUM FEHLT"
            
        tages_gesamt = sum(gruppe.gesamt_stunden for gruppe in eintrag.arbeitergruppen)
        gesamt_str = self._format_stunden(tages_gesamt)
        eintrag_text += f"\nGesamt {tag_datum_kurz}: {gesamt_str} Arbeitsstunden\n\n"
        
        return eintrag_text

    def _format_stunden(self, stunden: float) -> str:
        """Formatiere Stunden im deutschen Format: ganze Zahlen ohne Dezimal, sonst mit Komma."""
        rounded = round(stunden, 2)
        if rounded == int(rounded):
            return str(int(rounded))
        # Entferne unnötige Nullen (9.50 → 9,5)
        formatted = f"{rounded:.2f}".rstrip('0').replace('.', ',')
        return formatted

    def _einfaches_format_generieren(self, eintrag: Arbeitseintrag) -> str:
        """Generiere Format für einfache Szenarien (eine Arbeitergruppe) - exakt wie template.txt."""
        text = ""
        
        gruppe = eintrag.arbeitergruppen[0] if eintrag.arbeitergruppen else None
        
        # Pausen - MUSS dem Template entsprechen
        if gruppe and gruppe.pausen:
            pausen_text = self._pausen_formatieren(gruppe.pausen)
            text += f"Pausen: {pausen_text}\n"
        
        text += "\n"
        
        # Einsatz - exakt wie Template
        text += f"Einsatz: {eintrag.gesamt_mitarbeiter} Mitarbeiter\n"
        
        # Arbeitszeit nach Abzug der Pausen - exakt wie Template
        text += "Arbeitszeit nach Abzug der Pausen:\n"
        
        if gruppe:
            # Deutsche Zahlenformatierung (Komma statt Punkt)
            netto_str = self._format_stunden(gruppe.netto_stunden)
            gesamt_str = self._format_stunden(gruppe.gesamt_stunden)
            text += f"{gruppe.anzahl} Mitarbeiter × {netto_str} Stunden = {gesamt_str} Arbeitsstunden\n"
        
        return text

    def _komplexes_format_generieren(self, eintrag: Arbeitseintrag) -> str:
        """Generiere Format für komplexe Multi-Group-Szenarien - EXAKT wie template.txt."""
        text = ""
        
        for i, gruppe in enumerate(eintrag.arbeitergruppen):
            if i > 0:
                text += "\n"  # Leerzeile zwischen Gruppen
                
            # Format exakt wie im Template für mehrere Gruppen
            if gruppe.anzahl == 1:
                text += f"1 Mitarbeiter:\n"
            else:
                text += f"{gruppe.anzahl} Mitarbeiter:\n"
            
            # Pausen für diese Gruppe - EXAKT wie Template mit richtigem Singular/Plural
            if gruppe.pausen:
                pausen_text = self._pausen_formatieren(gruppe.pausen)
                if len(gruppe.pausen) == 1:
                    text += f"Pause {pausen_text}\n"  # Singular ohne Doppelpunkt
                else:
                    text += f"Pausen {pausen_text}\n"  # Plural ohne Doppelpunkt
            # Keine else-Klausel da im Template nicht gezeigt
            
            # Berechnung für diese Gruppe - exakt wie Template mit deutscher Formatierung
            netto_str = self._format_stunden(gruppe.netto_stunden)
            gesamt_str = self._format_stunden(gruppe.gesamt_stunden)
            text += f"{gruppe.anzahl} × {netto_str} Stunden = {gesamt_str} Arbeitsstunden\n"
        
        return text

    def _pausen_formatieren(self, pausen: List[Pausenzeit]) -> str:
        """Formatiere Pausen EXAKT im deutschen Template-Stil wie in template.txt."""
        if not pausen:
            return ""
        
        # Entferne Duplikate basierend auf Zeit
        einzigartige_pausen = []
        gesehen = set()
        for pause in pausen:
            pause_key = f"{pause.beginn}-{pause.ende}"
            if pause_key not in gesehen:
                einzigartige_pausen.append(pause)
                gesehen.add(pause_key)
        
        pausen = einzigartige_pausen
            
        if len(pausen) == 1:
            pause = pausen[0]
            return f"{pause.beginn}–{pause.ende} Uhr"
        elif len(pausen) == 2:
            p1, p2 = pausen[0], pausen[1]
            return f"{p1.beginn}–{p1.ende} Uhr und {p2.beginn}–{p2.ende} Uhr"
        else:
            # Mehr als 2 Pausen - mit Kommata und "und" für die letzte
            pausen_liste = []
            for i, pause in enumerate(pausen):
                if i == len(pausen) - 1:  # Letzte Pause
                    pausen_liste.append(f"und {pause.beginn}–{pause.ende} Uhr")
                else:
                    pausen_liste.append(f"{pause.beginn}–{pause.ende} Uhr")
            return ", ".join(pausen_liste)

    def gesamtbericht_generieren(self, alle_eintraege: List[Arbeitseintrag]) -> Dict[str, str]:
        """Generiere alle Wochenberichte für die gegebenen Einträge - ein Bericht pro Projekt pro Woche."""
        wochen_projekt_gruppen = self.eintraege_nach_wochen_und_projekten_gruppieren(alle_eintraege)
        berichte = {}
        
        for woche_start, projekt_gruppen in wochen_projekt_gruppen.items():
            for projekt, eintraege in projekt_gruppen.items():
                if eintraege:  # Nur wenn Einträge vorhanden
                    # Eindeutiger Schlüssel: Woche + Projekt
                    bericht_key = f"{woche_start}_{projekt.replace(' ', '_').replace('/', '_')}"
                    bericht = self.wochenbericht_generieren(eintraege, woche_start, projekt)
                    berichte[bericht_key] = bericht
                    
        return berichte

    def wochenstatistik_erstellen(self, alle_eintraege: List[Arbeitseintrag]) -> Dict[str, Dict]:
        """Erstelle Statistiken für jede Woche gruppiert nach Projekten."""
        wochen_projekt_gruppen = self.eintraege_nach_wochen_und_projekten_gruppieren(alle_eintraege)
        statistiken = {}
        
        for woche_start, projekt_gruppen in wochen_projekt_gruppen.items():
            start_datum = datetime.strptime(woche_start, "%Y-%m-%d")
            ende_datum = start_datum + timedelta(days=6)
            
            woche_stats = {
                'woche_start': start_datum.strftime("%d.%m.%Y"),
                'woche_ende': ende_datum.strftime("%d.%m.%Y"),
                'projekte': {}
            }
            
            # Statistiken pro Projekt in dieser Woche
            woche_gesamt_stunden = 0
            woche_gesamt_mitarbeiter_tage = 0
            woche_gesamt_arbeitstage = 0
            
            for projekt, eintraege in projekt_gruppen.items():
                # Berechne Projekt-Statistiken
                gesamt_stunden = sum(e.gesamtstunden for e in eintraege)
                gesamt_mitarbeiter_tage = sum(e.gesamt_mitarbeiter for e in eintraege)
                arbeitstage = len(eintraege)
                
                woche_stats['projekte'][projekt] = {
                    'gesamt_stunden': gesamt_stunden,
                    'arbeitstage': arbeitstage,
                    'mitarbeiter_tage': gesamt_mitarbeiter_tage,
                    'durchschnitt_pro_tag': gesamt_stunden / arbeitstage if arbeitstage > 0 else 0,
                    'durchschnitt_pro_mitarbeiter': gesamt_stunden / gesamt_mitarbeiter_tage if gesamt_mitarbeiter_tage > 0 else 0,
                    'eintraege_anzahl': len(eintraege)
                }
                
                # Addiere zu Wochen-Gesamt
                woche_gesamt_stunden += gesamt_stunden
                woche_gesamt_mitarbeiter_tage += gesamt_mitarbeiter_tage
                woche_gesamt_arbeitstage += arbeitstage
            
            # Wochen-Gesamt-Statistiken
            woche_stats['gesamt'] = {
                'stunden': woche_gesamt_stunden,
                'arbeitstage': woche_gesamt_arbeitstage,
                'mitarbeiter_tage': woche_gesamt_mitarbeiter_tage,
                'projekt_anzahl': len(projekt_gruppen),
                'durchschnitt_pro_tag': woche_gesamt_stunden / woche_gesamt_arbeitstage if woche_gesamt_arbeitstage > 0 else 0
            }
            
            statistiken[woche_start] = woche_stats
            
        return statistiken

    def aggregationsbericht_erstellen(self, alle_eintraege: List[Arbeitseintrag]) -> str:
        """Erstelle einen Aggregationsbericht über alle Wochen und Projekte."""
        statistiken = self.wochenstatistik_erstellen(alle_eintraege)
        
        if not statistiken:
            return "Keine Arbeitseinträge gefunden."
        
        bericht = "=" * 60 + "\n"
        bericht += "WÖCHENTLICHE ARBEITSZEIT-AGGREGATION\n"
        bericht += "=" * 60 + "\n\n"
        
        # Sortiere Wochen chronologisch
        sortierte_wochen = sorted(statistiken.keys())
        
        gesamt_alle_stunden = 0
        gesamt_alle_projekte = set()
        
        for woche in sortierte_wochen:
            stats = statistiken[woche]
            
            bericht += f"Woche {stats['woche_start']} - {stats['woche_ende']}\n"
            bericht += "-" * 40 + "\n"
            
            # Projekt-Details
            for projekt, projekt_stats in stats['projekte'].items():
                bericht += f"  📋 {projekt}:\n"
                bericht += f"     • {projekt_stats['gesamt_stunden']:.1f} Stunden ({projekt_stats['arbeitstage']} Tage)\n"
                bericht += f"     • {projekt_stats['mitarbeiter_tage']} Mitarbeiter-Tage\n"
                bericht += f"     • ⌀ {projekt_stats['durchschnitt_pro_tag']:.1f} Std./Tag\n"
                bericht += f"     • ⌀ {projekt_stats['durchschnitt_pro_mitarbeiter']:.1f} Std./Mitarbeiter\n\n"
                
                gesamt_alle_projekte.add(projekt)
            
            # Wochen-Zusammenfassung
            woche_gesamt = stats['gesamt']
            bericht += f"  📊 Woche Gesamt: {woche_gesamt['stunden']:.1f} Stunden\n"
            bericht += f"     {woche_gesamt['projekt_anzahl']} Projekt(e), {woche_gesamt['arbeitstage']} Arbeitstage\n"
            bericht += f"     ⌀ {woche_gesamt['durchschnitt_pro_tag']:.1f} Stunden/Tag\n\n"
            
            gesamt_alle_stunden += woche_gesamt['stunden']
        
        # Gesamt-Zusammenfassung
        bericht += "=" * 40 + "\n"
        bericht += "GESAMT-ZUSAMMENFASSUNG\n"
        bericht += "=" * 40 + "\n"
        bericht += f"🕒 Gesamtstunden: {gesamt_alle_stunden:.1f}\n"
        bericht += f"📋 Projekte: {len(gesamt_alle_projekte)} ({', '.join(sorted(gesamt_alle_projekte))})\n"
        bericht += f"📅 Wochen: {len(statistiken)}\n"
        
        if len(statistiken) > 0:
            durchschnitt_pro_woche = gesamt_alle_stunden / len(statistiken)
            bericht += f"⌀ Durchschnitt pro Woche: {durchschnitt_pro_woche:.1f} Stunden\n"
        
        return bericht

    def dateinamen_generieren(self, woche_start: str, projekt: str) -> str:
        """Generiere strukturierte Dateinamen für Berichte."""
        start_datum = datetime.strptime(woche_start, "%Y-%m-%d")
        ende_datum = start_datum + timedelta(days=6)
        
        # Format: woche-DD-MM-bis-DD-MM_projekt-name.txt
        start_str = start_datum.strftime("%d-%m")
        ende_str = ende_datum.strftime("%d-%m")
        projekt_clean = re.sub(r'[^\w\s-]', '', projekt).strip().replace(' ', '-')
        
        return f"woche-{start_str}-bis-{ende_str}_{projekt_clean}.txt"

    def _projekt_overlap_aufloesen(self, projekt_clean: str, kw_verzeichnis: str,
                                    start_str: str, ende_str: str) -> str:
        """
        Prüft ob eine bereits existierende Berichtsdatei in diesem Verzeichnis
        einen überlappenden Projektnamen hat (einer ist Substring des anderen).
        Falls ja, wird der kürzere (kanonischere) Name zurückgegeben.

        Beispiel: 'Manhartstraße-5-Bad-Tölz' überschneidet sich mit 'Bad-Tölz'
        → gibt 'Bad-Tölz' zurück, damit beide in dieselbe Datei landen.
        """
        import os

        if not os.path.exists(kw_verzeichnis):
            return projekt_clean

        prefix = f"{start_str}-bis-{ende_str}-"
        neu_norm = re.sub(r'[^a-z0-9äöüß]', '', projekt_clean.lower())

        for dateiname in os.listdir(kw_verzeichnis):
            if not dateiname.startswith(prefix) or not dateiname.endswith('.txt'):
                continue

            existierend_clean = dateiname[len(prefix):-4]  # Strip prefix + .txt
            existierend_norm = re.sub(r'[^a-z0-9äöüß]', '', existierend_clean.lower())

            if not existierend_norm or not neu_norm:
                continue

            # Einer enthält den anderen (mind. 4 Zeichen für sinnvollen Match)
            if (neu_norm in existierend_norm or existierend_norm in neu_norm) and \
               min(len(neu_norm), len(existierend_norm)) >= 4:
                # Nimm den kürzeren (kanonischeren) Namen
                if len(existierend_clean) <= len(projekt_clean):
                    return existierend_clean
                else:
                    # Benenne existierende Datei um auf den kürzeren neuen Namen
                    alter_pfad = os.path.join(kw_verzeichnis, dateiname)
                    neuer_pfad = os.path.join(kw_verzeichnis, f"{prefix}{projekt_clean}.txt")
                    os.rename(alter_pfad, neuer_pfad)
                    return projekt_clean

        return projekt_clean

    def berichte_speichern(self, alle_eintraege: List[Arbeitseintrag],
                           ausgabe_verzeichnis: str = "berichte",
                           config_pfad: str = None,
                           gruppenname: str = None) -> Dict[str, str]:
        """Speichere alle Berichte unter berichte/YYYY/Gruppenname KW-NN/DD-MM-bis-DD-MM-Projekt.txt
        und aktualisiere config.json mit dem Datum des letzten Berichts."""
        import os
        import json

        os.makedirs(ausgabe_verzeichnis, exist_ok=True)

        berichte = self.gesamtbericht_generieren(alle_eintraege)
        gespeicherte_dateien = {}
        neueste_datum = None  # Datum der jüngsten Nachricht (nicht Wochenende)

        # Bestimme das tatsächlich jüngste Eintragsdatum aus den Einträgen selbst
        for eintrag in alle_eintraege:
            if eintrag.datum:
                try:
                    eintrag_datum = datetime.strptime(eintrag.datum, "%Y-%m-%d")
                    if neueste_datum is None or eintrag_datum > neueste_datum:
                        neueste_datum = eintrag_datum
                except ValueError:
                    pass

        for bericht_key, bericht_inhalt in berichte.items():
            # Schlüssel: "2026-09-19_Bad_Tölz"
            teile = bericht_key.split('_', 1)
            woche_start = teile[0]
            projekt = teile[1].replace('_', ' ') if len(teile) > 1 else "Unbekannt"

            try:
                start_datum = datetime.strptime(woche_start, "%Y-%m-%d")
            except ValueError:
                start_datum = datetime.now()

            ende_datum = start_datum + timedelta(days=6)
            jahr = start_datum.year
            kalenderwoche = start_datum.isocalendar()[1]

            # berichte/2026/Adam Sub & Alma KW-39/
            gruppe_clean = re.sub(r'[^\w\s\-äöüÄÖÜß&]', '', gruppenname or "Unbekannt").strip() if gruppenname else "Unbekannt"
            kw_verzeichnis = os.path.join(ausgabe_verzeichnis, str(jahr), gruppe_clean, f"KW-{kalenderwoche:02d}")
            os.makedirs(kw_verzeichnis, exist_ok=True)

            # 19-09-bis-25-09-Bad-Tölz.txt  (title-case projekt for consistent filenames)
            start_str = start_datum.strftime("%d-%m")
            ende_str = ende_datum.strftime("%d-%m")
            projekt_clean = re.sub(r'[^\w\s\-äöüÄÖÜß]', '', projekt).strip()
            projekt_clean = '-'.join(w.capitalize() for w in projekt_clean.split())

            # Automatische Overlap-Erkennung: prüfe ob ein bereits existierender
            # Bericht in diesem Verzeichnis einen Projektnamen enthält, der im
            # aktuellen Projektnamen (oder umgekehrt) enthalten ist.
            projekt_clean = self._projekt_overlap_aufloesen(projekt_clean, kw_verzeichnis, start_str, ende_str)
            dateiname = f"{start_str}-bis-{ende_str}-{projekt_clean}.txt"

            dateipfad = os.path.join(kw_verzeichnis, dateiname)

            try:
                # Wenn Datei bereits existiert (gleicher Projektname, gleiche Woche),
                # Einträge zusammenführen statt überschreiben
                if os.path.exists(dateipfad):
                    with open(dateipfad, 'r', encoding='utf-8') as f:
                        vorhandener_inhalt = f.read()
                    # Neuen Tageseintrag anhängen (nach dem Header der bestehenden Datei)
                    with open(dateipfad, 'a', encoding='utf-8') as f:
                        # Trennlinie + neuer Inhalt ohne Header
                        header_ende = bericht_inhalt.find('\n\n', bericht_inhalt.find('---\n\n'))
                        neuer_eintrag = bericht_inhalt[header_ende + 2:] if header_ende > 0 else bericht_inhalt
                        f.write("⸻\n\n" + neuer_eintrag)
                    print(f"✓ Erweitert: {dateipfad}")
                else:
                    with open(dateipfad, 'w', encoding='utf-8') as f:
                        f.write(bericht_inhalt)
                    print(f"✓ Gespeichert: {dateipfad}")

                gespeicherte_dateien[bericht_key] = dateipfad
                neueste_datei = dateipfad  # Merke letzte Datei für Config

            except Exception as e:
                print(f"✗ Fehler beim Speichern {dateipfad}: {e}")

        # Config aktualisieren wenn eine Gruppe angegeben und Config vorhanden
        if config_pfad and gruppenname and neueste_datum and gespeicherte_dateien:
            self._config_aktualisieren(
                config_pfad, gruppenname,
                neueste_datum.strftime("%Y-%m-%d"),
                neueste_datei
            )

        return gespeicherte_dateien

    def _config_aktualisieren(self, config_pfad: str, gruppenname: str,
                               letztes_datum: str, letzte_datei: str) -> None:
        """Aktualisiere letzter_bericht_datum und letzter_kw_bericht (relativer KW-Ordnerpfad) in config.json."""
        import json, os
        from datetime import datetime as _dt, timedelta as _td

        if not os.path.exists(config_pfad):
            return

        try:
            with open(config_pfad, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Checkpoint auf letztes_datum + 1 Tag setzen (exklusiv), damit
            # beim nächsten Lauf dieselben Nachrichten nicht nochmal verarbeitet werden.
            try:
                checkpoint_datum = (_dt.strptime(letztes_datum, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                checkpoint_datum = letztes_datum

            # Projekt-Root = 3 Ebenen über der config-Datei
            # (.kiro/skills/subunternehmer-stunden-kompilierung/config.json)
            projekt_root = os.path.abspath(
                os.path.join(os.path.dirname(config_pfad), '..', '..', '..')
            )
            kw_ordner_abs = os.path.dirname(os.path.abspath(letzte_datei))
            kw_ordner_relativ = os.path.relpath(kw_ordner_abs, projekt_root)

            for gruppe in config.get("whatsapp_gruppen", []):
                if gruppe["gruppenname"] == gruppenname:
                    gruppe["letzter_bericht_datum"] = checkpoint_datum
                    gruppe["letzter_kw_bericht"] = kw_ordner_relativ
                    break

            with open(config_pfad, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            print(f"✓ Config aktualisiert: {gruppenname} → letzter Bericht {letztes_datum} (Checkpoint: ab {checkpoint_datum})")

        except Exception as e:
            print(f"⚠️ Config-Update fehlgeschlagen: {e}")


def main():
    """CLI-Schnittstelle zum Testen des Berichtsgenerators."""
    import sys
    from message_parser import DeutscherNachrichtenParser
    
    if len(sys.argv) < 2:
        print("Verwendung: python report_generator.py <nachrichten_text> [--save]")
        print("Beispiel: python report_generator.py 'Bad Tölz 28.9.26\\nArbeitsbeginn:07.00-17:30\\nPause: 11:00-12:00\\nInsgesamt 9'")
        print("  --save: Speichere Berichte in Dateien")
        sys.exit(1)
        
    nachricht = sys.argv[1]
    speichere_dateien = '--save' in sys.argv
    
    # Parse Nachrichten
    parser = DeutscherNachrichtenParser()
    eintraege = parser.nachricht_parsen(nachricht)
    
    if not eintraege:
        print("Keine Arbeitseinträge gefunden.")
        sys.exit(1)
    
    # Generiere Berichte
    generator = DeutscherBerichtsgenerator()
    
    if speichere_dateien:
        # Speichere Berichte in Dateien
        print("\\n" + "="*60)
        print("DATEIEN SPEICHERN")
        print("="*60)
        gespeicherte_dateien = generator.berichte_speichern(eintraege)
        print(f"Berichte gespeichert in {len(gespeicherte_dateien)} Dateien:")
        for key, pfad in gespeicherte_dateien.items():
            if key != 'aggregation':  # Zeige keine Aggregation
                print(f"  {key}: {pfad}")
    else:
        # Standard: Zeige einzelne Berichte
        berichte = generator.gesamtbericht_generieren(eintraege)
        for woche_projekt, bericht in berichte.items():
            print(f"\\n{'='*60}")
            print(f"WOCHENBERICHT: {woche_projekt}")
            print('='*60)
            print(bericht)


if __name__ == '__main__':
    main()