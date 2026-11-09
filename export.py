#!/usr/bin/env python3
"""
pdf_export_tool.py
==================
Standalone PDF-Export-Werkzeug für den Messe Tracker.

Features:
- Kategorien können in der UI per Drag & Drop nach Wichtigkeit geordnet werden
  (Persistenz in ~/.messe_tracker/pdf_export_config.json).
- Kategorien werden im PDF farbcodiert (rot = wichtigste … grau = unwichtigste).
- Kunden-Seiten werden automatisch nach Kategorie-Wichtigkeit sortiert.
- Merch-Auswertung zeigt den VERBRAUCH (Menge die rausgegangen ist),
  nicht den aktuellen Bestand: Start + Nachgefüllt − Aktuell = Verbraucht.

Voraussetzungen:
    pip install reportlab PyQt5 matplotlib
"""
from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    Image as RLImage,
)

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
    QMessageBox, QGroupBox, QCheckBox, QTextEdit, QStatusBar,
    QListWidget, QListWidgetItem, QAbstractItemView,
)

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# =============================================================================
#  Konstanten
# =============================================================================
# Farbpalette für Kategorien - Index 0 = wichtigste, Index -1 = unwichtigste
CATEGORY_PALETTE = [
    "#dc2626",  # rot      – höchste Priorität
    "#ea580c",  # orange
    "#d97706",  # amber
    "#ca8a04",  # gelb
    "#65a30d",  # limette
    "#16a34a",  # grün
    "#0891b2",  # türkis
    "#2563eb",  # blau
    "#7c3aed",  # violett
    "#db2777",  # pink
    "#6b7280",  # grau     – Rest / unbekannte Kategorie
]

CONFIG_DIR = Path.home() / ".messe_tracker"
CONFIG_FILE = CONFIG_DIR / "pdf_export_config.json"
DEFAULT_DB = Path(__file__).parent / "messe_tracker.db"


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"category_order": []}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# =============================================================================
#  Read-only DB
# =============================================================================
class ReadDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Datenbank nicht gefunden:\n{path}")
        self.conn = sqlite3.connect(
            f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def _has_col(self, table: str, col: str) -> bool:
        try:
            rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            return any(r["name"] == col for r in rows)
        except sqlite3.Error:
            return False

    def messen(self):
        try:
            return self.conn.execute(
                "SELECT * FROM messen WHERE COALESCE(geloescht,0)=0 ORDER BY name"
            ).fetchall()
        except sqlite3.Error:
            return self.conn.execute("SELECT * FROM messen ORDER BY name").fetchall()

    def messe_by_id(self, messe_id: int):
        return self.conn.execute(
            "SELECT * FROM messen WHERE id=?", (messe_id,)).fetchone()

    def kategorien(self):
        try:
            rows = self.conn.execute(
                "SELECT name FROM kategorien WHERE COALESCE(geloescht,0)=0"
            ).fetchall()
        except sqlite3.Error:
            rows = self.conn.execute("SELECT name FROM kategorien").fetchall()
        return [r["name"] for r in rows if r["name"]]

    def kunden(self, messe_id: int):
        cols = ["k.*", "t.datum", "m.name AS messe_name"]
        cols.append("COALESCE(k.prioritaet,0) AS prioritaet"
                    if self._has_col("kunden", "prioritaet")
                    else "0 AS prioritaet")
        cols.append("COALESCE(k.am_stand,0) AS am_stand"
                    if self._has_col("kunden", "am_stand")
                    else "0 AS am_stand")
        sql = f"""
            SELECT {', '.join(cols)}, c.name AS kategorie_name
            FROM kunden k
            JOIN tage t ON k.tage_id = t.id
            JOIN messen m ON t.messe_id = m.id
            LEFT JOIN kategorien c ON k.kategorie_id = c.id
            WHERE m.id = ?
            ORDER BY k.zeit ASC
        """
        return self.conn.execute(sql, (messe_id,)).fetchall()

    def status_history(self, uuid: str):
        try:
            return self.conn.execute(
                "SELECT * FROM kunden_status_history WHERE kunden_uuid=? "
                "ORDER BY geaendert_am ASC", (uuid,)).fetchall()
        except sqlite3.Error:
            return []

    def tage_stats(self, messe_id: int):
        return self.conn.execute("""
            SELECT t.id, t.datum,
                (SELECT COUNT(*) FROM kunden k
                 WHERE k.tage_id = t.id) AS kunden_count,
                (SELECT MIN(zeit) FROM anwesenheit
                 WHERE tage_id = t.id AND typ='BETRETEN') AS first_in,
                (SELECT MAX(zeit) FROM anwesenheit
                 WHERE tage_id = t.id AND typ='VERLASSEN') AS last_out
            FROM tage t WHERE t.messe_id = ?
            ORDER BY t.datum
        """, (messe_id,)).fetchall()

    def merch_artikel(self, messe_id: int):
        try:
            return self.conn.execute("""
                SELECT a.id, a.name,
                  (SELECT wert FROM merch_aktionen m
                   WHERE m.artikel_id=a.id
                   ORDER BY zeit DESC, id DESC LIMIT 1) AS bestand,
                  (SELECT ereignis_typ FROM merch_aktionen m
                   WHERE m.artikel_id=a.id
                   ORDER BY zeit DESC, id DESC LIMIT 1) AS letzter_typ
                FROM merch_artikel a
                WHERE a.messe_id = ?
                ORDER BY a.name
            """, (messe_id,)).fetchall()
        except sqlite3.Error:
            return []

    def merch_history(self, messe_id: int):
        try:
            return self.conn.execute("""
                SELECT ma.zeit, ma.aktion, ma.ereignis_typ, ma.wert,
                       a.name AS artikel_name
                FROM merch_aktionen ma
                JOIN merch_artikel a ON ma.artikel_id = a.id
                WHERE a.messe_id = ?
                ORDER BY ma.zeit ASC, ma.id ASC
            """, (messe_id,)).fetchall()
        except sqlite3.Error:
            return []

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# =============================================================================
#  PDF-Exporter
# =============================================================================
class PDFExporter:
    ACCENT = colors.HexColor("#FF8200")
    LIGHT = colors.HexColor("#f4f4f4")
    MUTED = colors.HexColor("#888888")
    CONSUMED_BG = colors.HexColor("#fff3e0")
    CONSUMED_FG = colors.HexColor("#c2410c")

    def __init__(self, db: ReadDB, messe_id: int, out_path: Path,
                 cat_order: list[str],
                 include_overview=True, include_merch=True,
                 include_customers=True, include_chart=True):
        self.db = db
        self.messe_id = messe_id
        self.out_path = Path(out_path)
        self.cat_order = list(cat_order)
        self.opts = {
            "overview": include_overview,
            "merch": include_merch,
            "customers": include_customers,
            "chart": include_chart and HAS_MPL,
        }

        self.messe = db.messe_by_id(messe_id)
        self.kunden = db.kunden(messe_id)
        self.tage = db.tage_stats(messe_id)
        self.merch = db.merch_artikel(messe_id)
        self.merch_hist = db.merch_history(messe_id)

        # Verbrauch pro Produkt berechnen
        self.consumption = self._compute_consumption()
        # Kunden nach Kategorie-Priorität sortieren
        self.kunden_sorted = self._sort_kunden_by_cat()

        self.base = getSampleStyleSheet()
        self._register_styles()

    # ------------------------------------------------------------------
    def _register_styles(self):
        s = self.base
        s.add(ParagraphStyle("MTitle", parent=s["Title"], fontSize=30,
                             textColor=self.ACCENT, spaceAfter=10))
        s.add(ParagraphStyle("MSub", parent=s["Normal"], fontSize=12,
                             textColor=self.MUTED, spaceAfter=20))
        s.add(ParagraphStyle("MSection", parent=s["Heading2"], fontSize=15,
                             textColor=self.ACCENT,
                             spaceBefore=10, spaceAfter=8))
        s.add(ParagraphStyle("MCustomer", parent=s["Heading1"], fontSize=20,
                             textColor=self.ACCENT, spaceAfter=4))
        s.add(ParagraphStyle("MFieldLabel", parent=s["Normal"], fontSize=8,
                             textColor=self.MUTED, leading=10))
        s.add(ParagraphStyle("MFieldValue", parent=s["Normal"], fontSize=11,
                             leading=14, spaceAfter=4))
        s.add(ParagraphStyle("MFooter", parent=s["Normal"], fontSize=8,
                             textColor=self.MUTED, alignment=1))

    # ------------------------------------------------------------------
    #  Kategorie-Helfer
    # ------------------------------------------------------------------
    def _cat_color(self, name: str) -> str:
        if name in self.cat_order:
            idx = self.cat_order.index(name)
            return CATEGORY_PALETTE[idx % len(CATEGORY_PALETTE)]
        return "#888888"

    def _cat_rank(self, name: str) -> int | None:
        if name in self.cat_order:
            return self.cat_order.index(name) + 1
        return None

    def _sort_kunden_by_cat(self):
        def key(k):
            name = k["kategorie_name"] or ""
            rank = (self.cat_order.index(name)
                    if name in self.cat_order else 999)
            return (rank, k["zeit"] or "")
        return sorted(self.kunden, key=key)

    # ------------------------------------------------------------------
    #  Verbrauchsberechnung
    # ------------------------------------------------------------------
    def _compute_consumption(self) -> dict:
        """Berechnet pro Produkt: Start / Nachgefüllt / Aktuell / Verbraucht.

        Verbraucht = (Start + Nachfüllungen) − Aktuell
        wird direkt aus der Event-Historie hergeleitet, damit
        doppelte oder fehlende Einträge robust behandelt werden.
        """
        stats: dict[str, dict] = {}
        for m in self.merch:
            stats[m["name"]] = {"start": 0, "refilled": 0,
                                "current": 0, "consumed": 0}

        by_prod: dict[str, list] = {}
        for h in self.merch_hist:
            by_prod.setdefault(h["artikel_name"], []).append(h)

        for name, events in by_prod.items():
            if name not in stats:
                stats[name] = {"start": 0, "refilled": 0,
                               "current": 0, "consumed": 0}
            s = stats[name]
            stock = 0
            initialized = False
            for e in events:
                typ = e["ereignis_typ"] or e["aktion"] or ""
                try:
                    val = int(e["wert"])
                except (ValueError, TypeError):
                    continue
                if typ == "STARTBESTAND":
                    s["start"] = val
                    stock = val
                    initialized = True
                elif typ == "BESTAND":
                    if not initialized:
                        s["start"] = val
                        initialized = True
                    elif val < stock:
                        s["consumed"] += (stock - val)
                    stock = val
                elif typ == "NACHFUELLUNG":
                    if not initialized:
                        s["start"] = val
                        initialized = True
                    elif val > stock:
                        s["refilled"] += (val - stock)
                    stock = val
                s["current"] = stock
        return stats

    def _total_consumed(self) -> int:
        return sum(s["consumed"] for s in self.consumption.values())

    # ------------------------------------------------------------------
    def _draw_chrome(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(self.ACCENT)
        canvas.setLineWidth(2)
        canvas.line(40, A4[1] - 30, A4[0] - 40, A4[1] - 30)
        canvas.setFillColor(self.ACCENT)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(40, A4[1] - 25, "MESSE TRACKER")
        if self.messe:
            canvas.setFillColor(self.MUTED)
            canvas.setFont("Helvetica", 9)
            canvas.drawRightString(A4[0] - 40, A4[1] - 25,
                                   self.messe["name"] or "")
        canvas.setFillColor(self.MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(A4[0] / 2, 18, f"Seite {doc.page}")
        canvas.restoreState()

    # ------------------------------------------------------------------
    def export(self) -> Path:
        title = self.messe["name"] if self.messe else "Messe"
        doc = SimpleDocTemplate(
            str(self.out_path), pagesize=A4,
            leftMargin=40, rightMargin=40,
            topMargin=45, bottomMargin=40,
            title=f"Messe-Bericht {title}",
            author="Messe Tracker")

        story = []
        story.extend(self._cover())

        if self.opts["overview"]:
            story.append(PageBreak())
            story.extend(self._overview())

        if self.opts["merch"]:
            story.append(PageBreak())
            story.extend(self._merch_chapter())

        if self.opts["customers"]:
            for k in self.kunden_sorted:
                story.append(PageBreak())
                story.extend(self._customer_page(k))

        doc.build(story,
                  onFirstPage=self._draw_chrome,
                  onLaterPages=self._draw_chrome)
        return self.out_path

    # ------------------------------------------------------------------
    def _cover(self):
        s = self.base
        story = [Spacer(1, 90),
                 Paragraph("Messe-Bericht", s["MTitle"])]
        if self.messe:
            story.append(Paragraph(self.messe["name"] or "", s["Heading1"]))
            if self.messe["ort"]:
                story.append(Paragraph(self.messe["ort"], s["MSub"]))
        else:
            story.append(Paragraph("(unbekannte Messe)", s["MSub"]))

        dates = [k["datum"] for k in self.kunden if k["datum"]]
        if dates:
            story.append(Paragraph(
                f"Auswertungszeitraum: {min(dates)} bis {max(dates)}",
                s["Normal"]))
        story.append(Spacer(1, 30))

        am_stand = sum(1 for k in self.kunden if k["am_stand"])
        stats = [
            ("Kunden gesamt",      str(len(self.kunden))),
            ("Messetage",          str(len(self.tage))),
            ("Am Stand getroffen", str(am_stand)),
            ("Merch verbraucht",   str(self._total_consumed())),
        ]
        data = [[Paragraph(f"<b>{lbl}</b>", s["Normal"]),
                 Paragraph(f"<b>{val}</b>", s["Heading2"])]
                for lbl, val in stats]
        t = Table(data, colWidths=[300, 200])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, self.MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 60))
        story.append(Paragraph(
            f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            s["MFooter"]))
        return story

    # ------------------------------------------------------------------
    def _overview(self):
        s = self.base
        story = [Paragraph("Gesamtübersicht", s["MSection"])]

        n = len(self.kunden)
        am_stand = sum(1 for k in self.kunden if k["am_stand"])
        quote = (am_stand / n * 100) if n else 0
        interessenten = sum(1 for k in self.kunden
                            if "interessiert" in (k["kategorie_name"] or "").lower())
        anfragen = sum(1 for k in self.kunden
                       if "anfrage" in (k["kategorie_name"] or "").lower())
        auftraege = sum(1 for k in self.kunden
                        if "auftrag" in (k["kategorie_name"] or "").lower())
        fehlend = sum(1 for k in self.kunden
                      if not (k["email"] or k["telefon"]))
        avg_t = (n / len(self.tage)) if self.tage else 0

        data = [
            ["Kontakte gesamt",    str(n)],
            ["Messetage",          str(len(self.tage))],
            ["Ø Kontakte pro Tag", f"{avg_t:.1f}"],
            ["Am Stand getroffen", f"{am_stand} ({quote:.1f}%)"],
            ["Interessenten",      str(interessenten)],
            ["Anfragen",           str(anfragen)],
            ["Aufträge",           str(auftraege)],
            ["Ohne Kontaktdaten",  str(fehlend)],
            ["Merch verbraucht",   str(self._total_consumed())],
        ]
        t = Table(data, colWidths=[250, 200])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), self.LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)

        # --- Kategorien in Prioritätsreihenfolge ---
        story.append(Spacer(1, 22))
        story.append(Paragraph("Kategorien nach Priorität", s["MSection"]))
        cats: dict[str, int] = {}
        for k in self.kunden:
            c = k["kategorie_name"] or "(ohne)"
            cats[c] = cats.get(c, 0) + 1
        if cats:
            def sort_key(name):
                if name in self.cat_order:
                    return (0, self.cat_order.index(name), "")
                return (1, 999, name)
            ordered = sorted(cats.items(), key=lambda x: sort_key(x[0]))

            data = [["", "Kategorie", "Anzahl"]]
            for name, cnt in ordered:
                data.append(["", name, str(cnt)])
            tab = Table(data, colWidths=[10, 280, 120])
            style = [
                ("BACKGROUND", (0, 0), (-1, 0), self.ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (1, 1), (-1, -1),
                 [colors.white, self.LIGHT]),
            ]
            for i, (name, _) in enumerate(ordered):
                style.append(("BACKGROUND", (0, i + 1), (0, i + 1),
                              colors.HexColor(self._cat_color(name))))
            tab.setStyle(TableStyle(style))
            story.append(tab)

            # Legende: Farben + Rang
            story.append(Spacer(1, 10))
            legend = ", ".join(
                f"<font color='{self._cat_color(nm)}'>■</font> {i+1}. {nm}"
                for i, (nm, _) in enumerate(ordered))
            story.append(Paragraph(
                f"<font size=8 color='#666'>Priorität: {legend}</font>",
                s["Normal"]))
        else:
            story.append(Paragraph("Keine Kategorien-Daten vorhanden.",
                                   s["Normal"]))

        # --- Tage-Detail ---
        story.append(Spacer(1, 22))
        story.append(Paragraph("Messetage im Detail", s["MSection"]))
        if self.tage:
            data = [["Datum", "Kunden", "Erster Besuch", "Letzter Besuch"]]
            for t_row in self.tage:
                data.append([
                    t_row["datum"] or "–",
                    str(t_row["kunden_count"] or 0),
                    (t_row["first_in"] or "–")[:16],
                    (t_row["last_out"] or "–")[:16],
                ])
            tab = Table(data, colWidths=[100, 70, 160, 160])
            tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self.ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, self.LIGHT]),
            ]))
            story.append(tab)
        return story

    # ------------------------------------------------------------------
    def _merch_chapter(self):
        s = self.base
        story = [Paragraph("Merch – Verbrauch", s["MSection"])]

        # Tabelle: Verbrauch pro Produkt (nach Verbrauch sortiert)
        if self.consumption:
            # Nach Verbrauch absteigend sortieren
            items = sorted(self.consumption.items(),
                           key=lambda x: -x[1]["consumed"])

            data = [["Artikel", "Start", "Nachgefüllt",
                     "Bestand", "Verbraucht"]]
            total_start = total_refill = total_current = total_consumed = 0
            for name, st in items:
                data.append([
                    name,
                    str(st["start"]),
                    str(st["refilled"]),
                    str(st["current"]),
                    str(st["consumed"]),
                ])
                total_start += st["start"]
                total_refill += st["refilled"]
                total_current += st["current"]
                total_consumed += st["consumed"]
            data.append(["GESAMT", str(total_start), str(total_refill),
                         str(total_current), str(total_consumed)])

            tab = Table(data, colWidths=[150, 55, 75, 60, 80])
            tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self.ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2),
                 [colors.white, self.LIGHT]),
                # Verbraucht-Spalte hervorheben
                ("BACKGROUND", (-1, 1), (-1, -1), self.CONSUMED_BG),
                ("FONTNAME", (-1, 1), (-1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (-1, 1), (-1, -1), self.CONSUMED_FG),
                # Summenzeile
                ("BACKGROUND", (0, -1), (-1, -1), self.LIGHT),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, self.MUTED),
            ]))
            story.append(tab)
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                "<font size=8 color='#666'>Verbraucht = Start + Nachgefüllt "
                "− Bestand. Zeigt die tatsächlich abgegebene Menge.</font>",
                s["Normal"]))
        else:
            story.append(Paragraph("Keine Merch-Artikel angelegt.",
                                   s["Normal"]))

        # Chart: Bestand (links) + kumulierter Verbrauch (rechts)
        if self.opts["chart"] and self.merch_hist and self.consumption:
            story.append(Spacer(1, 18))
            story.append(Paragraph("Verlauf", s["MSection"]))
            try:
                fig = Figure(figsize=(10, 4), facecolor="white")
                ax_stock = fig.add_subplot(1, 2, 1)
                ax_cons = fig.add_subplot(1, 2, 2)

                # Zeitreihen pro Produkt bauen
                by_prod: dict[str, list] = {}
                for h in self.merch_hist:
                    by_prod.setdefault(h["artikel_name"], []).append(h)

                for name, events in by_prod.items():
                    pts_stock = []
                    pts_cons = []
                    stock = 0
                    cum_cons = 0
                    day_offsets: dict = {}
                    for e in events:
                        typ = e["ereignis_typ"] or e["aktion"] or ""
                        try:
                            val = int(e["wert"])
                        except (ValueError, TypeError):
                            continue
                        try:
                            ts = datetime.strptime(
                                str(e["zeit"]), "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue
                        # Da Flipper alle Events auf 12:00 setzt:
                        # pro Tag kleine Minuten-Offsets, damit die
                        # Zeitreihe lesbar bleibt.
                        d = ts.date()
                        off = day_offsets.get(d, 0)
                        day_offsets[d] = off + 1
                        ts = ts + timedelta(minutes=off)

                        if typ == "STARTBESTAND":
                            stock = val
                        elif typ == "BESTAND":
                            if val < stock:
                                cum_cons += (stock - val)
                            stock = val
                        elif typ == "NACHFUELLUNG":
                            stock = val
                        pts_stock.append((ts, stock))
                        pts_cons.append((ts, cum_cons))

                    if pts_stock:
                        xs, ys = zip(*pts_stock)
                        ax_stock.plot(xs, ys, marker="o", markersize=3,
                                      linewidth=1.4, label=name)
                    if pts_cons:
                        xs, ys = zip(*pts_cons)
                        ax_cons.plot(xs, ys, marker="o", markersize=3,
                                     linewidth=1.4, label=name)

                ax_stock.set_title("Bestand im Zeitverlauf", color="#333")
                ax_stock.set_ylabel("Stück")
                ax_stock.grid(True, alpha=0.3)
                ax_stock.legend(fontsize=6, loc="best")

                ax_cons.set_title("Kumulierter Verbrauch", color="#333")
                ax_cons.set_ylabel("Stück")
                ax_cons.grid(True, alpha=0.3)
                ax_cons.legend(fontsize=6, loc="best")

                for ax in (ax_stock, ax_cons):
                    fig.autofmt_xdate(rotation=30)
                fig.tight_layout()
                buf = BytesIO()
                fig.savefig(buf, format="png", dpi=110,
                            bbox_inches="tight")
                buf.seek(0)
                story.append(RLImage(buf, width=510, height=210))
            except Exception as exc:
                story.append(Paragraph(
                    f"(Chart konnte nicht erzeugt werden: {exc})",
                    s["Normal"]))

        # Vollständige Historie
        story.append(Spacer(1, 15))
        story.append(Paragraph("Alle Merch-Bewegungen", s["MSection"]))
        if self.merch_hist:
            data = [["Zeit", "Artikel", "Aktion", "Wert"]]
            for h in self.merch_hist:
                data.append([
                    (h["zeit"] or "")[:16],
                    h["artikel_name"] or "–",
                    h["ereignis_typ"] or h["aktion"] or "–",
                    str(h["wert"]),
                ])
            tab = Table(data, colWidths=[110, 180, 130, 60])
            tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self.ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, self.LIGHT]),
            ]))
            story.append(tab)
        else:
            story.append(Paragraph("Keine Merch-Bewegungen vorhanden.",
                                   s["Normal"]))
        return story

    # ------------------------------------------------------------------
    def _customer_page(self, k):
        s = self.base
        name = k["name"] or f"Kunde #{k['id']}"
        story = [Paragraph(f"{name}", s["MCustomer"])]

        prio_map = {0: "Niedrig", 1: "Mittel", 2: "Hoch"}
        try:
            prio = prio_map.get(int(k["prioritaet"] or 0), "Niedrig")
        except (TypeError, ValueError):
            prio = "Niedrig"
        stand = "Am Stand" if k["am_stand"] else "Nicht am Stand"

        cat_name = k["kategorie_name"] or "–"
        cat_color = self._cat_color(cat_name)
        cat_rank = self._cat_rank(cat_name)
        rank_txt = (f" <font size=9 color='#888'>(Rang {cat_rank}/"
                    f"{len(self.cat_order)})</font>"
                    if cat_rank else "")

        subtitle = (
            f"Kunde #{k['id']}  ·  "
            f"Kategorie: <font color='{cat_color}'><b>{cat_name}</b></font>"
            f"{rank_txt}  ·  "
            f"Priorität: {prio}  ·  {stand}"
        )
        story.append(Paragraph(subtitle, s["MSub"]))

        fields = [
            ("Name",       k["name"] or "–"),
            ("Firma",      k["firma"] or "–"),
            ("E-Mail",     k["email"] or "–"),
            ("Telefon",    k["telefon"] or "–"),
            ("Datum",      k["datum"] or "–"),
            ("Uhrzeit",    (k["zeit"] or "")[11:16]),
            ("Flipper-ID", k["flipper_id"] or "–"),
            ("Messe",      k["messe_name"] or "–"),
            ("Notiz",      k["notiz"] or "–"),
        ]
        data = [[Paragraph(lbl, s["MFieldLabel"]),
                 Paragraph(str(val), s["MFieldValue"])]
                for lbl, val in fields]
        t = Table(data, colWidths=[100, 380])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.2, self.MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)

        # Status-Historie
        hist = self.db.status_history(k["uuid"]) if k["uuid"] else []
        if hist:
            story.append(Spacer(1, 20))
            story.append(Paragraph("Status-Historie", s["MSection"]))
            data = [["Wann", "Alt", "Neu", "Quelle"]]
            for h in hist:
                data.append([
                    (h["geaendert_am"] or "")[:16],
                    h["alter_status"] or "–",
                    h["neuer_status"] or "–",
                    h["quelle"] or "–",
                ])
            tab = Table(data, colWidths=[120, 80, 80, 100])
            tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self.ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.3, self.MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(tab)
        return story


# =============================================================================
#  UI
# =============================================================================
QSS = """
QWidget { background: #000; color: #eee;
          font-family: 'Segoe UI', Arial; font-size: 10pt; }
QLabel { background: transparent; }
QGroupBox { background: #111; border: 1px solid #333; border-radius: 8px;
            margin-top: 14px; padding: 12px 10px 10px 10px;
            font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px;
                   padding: 0 6px; color: #FF8200; }
QLineEdit, QComboBox, QTextEdit {
    background: #1a1a1a; color: #eee; border: 1px solid #333;
    border-radius: 6px; padding: 6px; }
QListWidget { background: #1a1a1a; color: #eee; border: 1px solid #333;
              border-radius: 6px; }
QListWidget::item { padding: 6px 8px; }
QListWidget::item:selected { background: #FF8200; color: #000; }
QPushButton { background: #FF8200; color: #000; border: 0;
              border-radius: 8px; padding: 10px 18px;
              font-weight: 700; }
QPushButton:hover { background: #ffa040; }
QPushButton:disabled { background: #333; color: #888; }
QPushButton#Ghost { background: #1a1a1a; color: #eee;
                    border: 1px solid #333; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
"""


class ExportWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messe Tracker – PDF-Export")
        self.resize(980, 720)
        self.db: ReadDB | None = None
        self.cfg = load_config()
        self._build_ui()
        self._auto_load()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)

        # Datenbank
        db_box = QGroupBox("Datenbank")
        dbl = QHBoxLayout(db_box)
        self.ed_db = QLineEdit(str(DEFAULT_DB))
        btn_db = QPushButton("…")
        btn_db.setObjectName("Ghost")
        btn_db.setFixedWidth(40)
        btn_db.clicked.connect(self._pick_db)
        btn_reload = QPushButton("Neu laden")
        btn_reload.setObjectName("Ghost")
        btn_reload.clicked.connect(self._reload_db)
        dbl.addWidget(QLabel("Datei:"))
        dbl.addWidget(self.ed_db, 1)
        dbl.addWidget(btn_db)
        dbl.addWidget(btn_reload)
        v.addWidget(db_box)

        # Messe
        messe_box = QGroupBox("Messe")
        ml = QHBoxLayout(messe_box)
        ml.addWidget(QLabel("Auswahl:"))
        self.cb_messe = QComboBox()
        ml.addWidget(self.cb_messe, 1)
        v.addWidget(messe_box)

        # Splitter für Kategorien + Optionen
        lower = QHBoxLayout()

        # Kategorien-Priorität
        cat_box = QGroupBox(
            "Kategorie-Priorität (ziehen zum Umsortieren · oben = wichtigste)")
        cv = QVBoxLayout(cat_box)
        self.cat_list = QListWidget()
        self.cat_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.cat_list.setDefaultDropAction(Qt.MoveAction)
        self.cat_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.cat_list.model().rowsMoved.connect(self._save_cat_order)
        self.cat_list.setMinimumHeight(220)
        cv.addWidget(self.cat_list)
        cat_btns = QHBoxLayout()
        btn_up = QPushButton("▲ nach oben")
        btn_up.setObjectName("Ghost")
        btn_up.clicked.connect(lambda: self._move_cat(-1))
        btn_down = QPushButton("▼ nach unten")
        btn_down.setObjectName("Ghost")
        btn_down.clicked.connect(lambda: self._move_cat(1))
        btn_reset = QPushButton("Zurücksetzen")
        btn_reset.setObjectName("Ghost")
        btn_reset.clicked.connect(self._reset_cat_order)
        cat_btns.addWidget(btn_up)
        cat_btns.addWidget(btn_down)
        cat_btns.addStretch(1)
        cat_btns.addWidget(btn_reset)
        cv.addLayout(cat_btns)
        lower.addWidget(cat_box, 1)

        # Optionen
        opt_box = QGroupBox("Berichts-Inhalt")
        ol = QVBoxLayout(opt_box)
        self.cb_overview = QCheckBox("Titelseite + Gesamtübersicht")
        self.cb_overview.setChecked(True)
        self.cb_merch = QCheckBox("Merch-Verbrauch (Tabelle + Chart + Historie)")
        self.cb_merch.setChecked(True)
        self.cb_chart = QCheckBox("Diagramm zeichnen (matplotlib)")
        self.cb_chart.setChecked(HAS_MPL)
        self.cb_chart.setEnabled(HAS_MPL)
        self.cb_customers = QCheckBox("Pro Kunde eine eigene Seite "
                                      "(sortiert nach Kategorie)")
        self.cb_customers.setChecked(True)
        ol.addWidget(self.cb_overview)
        ol.addWidget(self.cb_merch)
        ol.addWidget(self.cb_chart)
        ol.addWidget(self.cb_customers)
        ol.addStretch(1)
        lower.addWidget(opt_box, 1)

        v.addLayout(lower, 1)

        # Aktionen
        act = QHBoxLayout()
        self.btn_export = QPushButton("PDF exportieren …")
        self.btn_export.clicked.connect(self._export)
        act.addStretch(1)
        act.addWidget(self.btn_export)
        v.addLayout(act)

        # Log
        v.addWidget(QLabel("Log:"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "background:#050505; font-family: monospace; font-size:9pt;")
        self.log.setMaximumHeight(140)
        v.addWidget(self.log)

        self.setStatusBar(QStatusBar())

    # ------------------------------------------------------------------
    #  Farb-Swatch für Kategorien
    # ------------------------------------------------------------------
    @staticmethod
    def _color_icon(hex_color: str) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(QColor(hex_color))
        return QIcon(pix)

    def _refresh_cat_list_style(self):
        """Aktualisiert Farb-Icons und Positionsnummern."""
        for i in range(self.cat_list.count()):
            item = self.cat_list.item(i)
            name = item.data(Qt.UserRole)
            color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
            item.setIcon(self._color_icon(color))
            item.setText(f"{i+1}. {name}")

    # ------------------------------------------------------------------
    #  Kategorie-Liste
    # ------------------------------------------------------------------
    def _populate_cat_list(self, db_cats: list[str]):
        saved = self.cfg.get("category_order") or []
        # Gespeicherte Reihenfolge nur für noch existierende Kategorien
        order = [c for c in saved if c in db_cats]
        # Neue Kategorien hinten anhängen
        for c in db_cats:
            if c not in order:
                order.append(c)

        self.cat_list.clear()
        for name in order:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.cat_list.addItem(item)
        self._refresh_cat_list_style()

    def _save_cat_order(self, *_):
        order = [self.cat_list.item(i).data(Qt.UserRole)
                 for i in range(self.cat_list.count())]
        self.cfg["category_order"] = order
        try:
            save_config(self.cfg)
        except Exception as exc:
            self._log(f"⚠️ Konnte Reihenfolge nicht speichern: {exc}")
        self._refresh_cat_list_style()

    def _move_cat(self, delta: int):
        row = self.cat_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if 0 <= new_row < self.cat_list.count():
            item = self.cat_list.takeItem(row)
            self.cat_list.insertItem(new_row, item)
            self.cat_list.setCurrentRow(new_row)
            self._save_cat_order()

    def _reset_cat_order(self):
        if not self.db:
            return
        self._populate_cat_list(self.db.kategorien())
        self._save_cat_order()

    # ------------------------------------------------------------------
    #  DB laden
    # ------------------------------------------------------------------
    def _pick_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "messe_tracker.db wählen", str(DEFAULT_DB.parent),
            "SQLite (*.db *.sqlite);;Alle Dateien (*)")
        if path:
            self.ed_db.setText(path)
            self._reload_db()

    def _auto_load(self):
        try:
            self._reload_db()
        except Exception as exc:
            self._warn(f"Konnte Datenbank nicht laden:\n{exc}")

    def _reload_db(self):
        if self.db:
            self.db.close()
            self.db = None
        try:
            self.db = ReadDB(Path(self.ed_db.text()))
        except Exception as exc:
            self._warn(str(exc))
            return

        # Messen füllen
        self.cb_messe.clear()
        try:
            rows = self.db.messen()
        except Exception as exc:
            self._warn(f"Fehler beim Lesen der Messen:\n{exc}")
            return
        if not rows:
            self.cb_messe.addItem("(keine Messe vorhanden)", None)
        for m in rows:
            label = m["name"] or f"Messe #{m['id']}"
            self.cb_messe.addItem(label, m["id"])

        # Kategorien
        try:
            cats = self.db.kategorien()
        except Exception as exc:
            self._warn(f"Fehler beim Lesen der Kategorien:\n{exc}")
            return
        self._populate_cat_list(cats)

        self._log(f"Datenbank geladen: {self.ed_db.text()}")
        self._log(f"{len(rows)} Messe(n), {len(cats)} Kategorie(n) gefunden.")

    # ------------------------------------------------------------------
    #  Export
    # ------------------------------------------------------------------
    def _export(self):
        if not self.db:
            self._warn("Keine Datenbank geladen.")
            return
        messe_id = self.cb_messe.currentData()
        if not messe_id:
            self._warn("Bitte eine Messe auswählen.")
            return

        # Aktuelle Reihenfolge sichern
        self._save_cat_order()
        cat_order = list(self.cfg.get("category_order") or [])

        messe = self.db.messe_by_id(messe_id)
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in (messe["name"] or "Messe"))
        default = f"Messe-Bericht_{safe}_{datetime.now():%Y%m%d_%H%M}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF speichern", default, "PDF-Dateien (*.pdf)")
        if not path:
            return

        self.btn_export.setEnabled(False)
        self.statusBar().showMessage("Exportiere …")
        try:
            self._log("─" * 60)
            self._log(f"Export gestartet: {path}")
            self._log(f"Kategorie-Reihenfolge: {cat_order}")
            exporter = PDFExporter(
                self.db, messe_id, Path(path), cat_order,
                include_overview=self.cb_overview.isChecked(),
                include_merch=self.cb_merch.isChecked(),
                include_customers=self.cb_customers.isChecked(),
                include_chart=self.cb_chart.isChecked())
            out = exporter.export()
            self._log(f"✅ Fertig: {out}")
            self.statusBar().showMessage("Export erfolgreich.", 5000)
            QMessageBox.information(
                self, "PDF exportiert",
                f"Bericht erfolgreich erstellt:\n\n{out}")
        except Exception as exc:
            self._log("❌ Fehler beim Export:")
            self._log(traceback.format_exc())
            self._warn(f"Export fehlgeschlagen:\n{exc}")
            self.statusBar().showMessage("Fehler beim Export.", 5000)
        finally:
            self.btn_export.setEnabled(True)

    # ------------------------------------------------------------------
    def _log(self, line: str):
        self.log.append(line)

    def _warn(self, msg: str):
        QMessageBox.warning(self, "Hinweis", msg)
        self._log(f"⚠️ {msg}")

    def closeEvent(self, event):
        if self.db:
            self.db.close()
        event.accept()


# =============================================================================
#  Entry
# =============================================================================
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = ExportWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())