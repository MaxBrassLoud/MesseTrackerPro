#!/usr/bin/env python3
"""
pdf_export_tool.py
==================
Standalone PDF-Export-Werkzeug für den Messe Tracker.

- Liest messe_tracker.db NUR lesend (keine Schreibzugriffe).
- Erzeugt einen vollständigen PDF-Bericht:
    1. Titelseite + Kennzahlen
    2. Gesamtübersicht (Tage, Kategorien, Am-Stand-Quote)
    3. Merch-Bestand + Bestandsverlauf (Chart) + komplette Historie
    4. Pro Kunde eine eigene Seite (Felder, Priorität, Status-Historie)

Voraussetzungen:
    pip install reportlab PyQt5 matplotlib
"""
from __future__ import annotations

import sqlite3
import sys
import traceback
from datetime import datetime
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
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog,
    QMessageBox, QGroupBox, QCheckBox, QTextEdit, QStatusBar,
)

# --- Matplotlib ist optional; ohne MPL wird der Chart weggelassen ---
try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


DEFAULT_DB = Path(__file__).parent / "messe_tracker.db"


# =============================================================================
#  Read-only DB
# =============================================================================
class ReadDB:
    """Read-only Wrapper um messe_tracker.db."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Datenbank nicht gefunden:\n{path}")
        # Read-only URI verhindert versehentliche Schreibzugriffe.
        self.conn = sqlite3.connect(
            f"file:{self.path}?mode=ro", uri=True,
            check_same_thread=False)
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
    """Erzeugt den vollständigen PDF-Bericht für eine Messe."""

    ACCENT = colors.HexColor("#FF8200")
    LIGHT = colors.HexColor("#f4f4f4")
    MUTED = colors.HexColor("#888888")

    def __init__(self, db: ReadDB, messe_id: int, out_path: Path,
                 include_overview=True, include_merch=True,
                 include_customers=True, include_chart=True):
        self.db = db
        self.messe_id = messe_id
        self.out_path = Path(out_path)
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
    def _draw_chrome(self, canvas, doc):
        canvas.saveState()
        # Kopf
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
        # Fuß
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
            for k in self.kunden:
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
            ("Merch-Artikel",      str(len(self.merch))),
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

        story.append(Spacer(1, 20))
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

        story.append(Spacer(1, 20))
        story.append(Paragraph("Kategorien-Verteilung", s["MSection"]))
        cats: dict[str, int] = {}
        for k in self.kunden:
            c = k["kategorie_name"] or "(ohne)"
            cats[c] = cats.get(c, 0) + 1
        if cats:
            data = [["Kategorie", "Anzahl"]]
            for name, cnt in sorted(cats.items(), key=lambda x: -x[1]):
                data.append([name, str(cnt)])
            tab = Table(data, colWidths=[300, 120])
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
        story = [Paragraph("Merch-Bestand & Verlauf", s["MSection"])]

        if self.merch:
            data = [["Artikel", "Aktueller Bestand", "Letzte Aktion"]]
            for m in self.merch:
                data.append([
                    m["name"] or "–",
                    str(m["bestand"] if m["bestand"] is not None else 0),
                    m["letzter_typ"] or "–",
                ])
            tab = Table(data, colWidths=[220, 120, 160])
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
        else:
            story.append(Paragraph("Keine Merch-Artikel angelegt.",
                                   s["Normal"]))

        # Chart
        if self.opts["chart"] and self.merch_hist:
            story.append(Spacer(1, 20))
            story.append(Paragraph("Bestandsverlauf", s["MSection"]))
            try:
                fig = Figure(figsize=(7, 3.6), facecolor="white")
                ax = fig.add_subplot(1, 1, 1)
                by_prod: dict[str, list] = {}
                for h in self.merch_hist:
                    by_prod.setdefault(h["artikel_name"], []).append(h)
                for name, events in by_prod.items():
                    pts = []
                    for e in events:
                        try:
                            ts = datetime.strptime(
                                str(e["zeit"]), "%Y-%m-%d %H:%M:%S")
                            pts.append((ts, int(e["wert"])))
                        except (ValueError, TypeError):
                            continue
                    if pts:
                        xs, ys = zip(*pts)
                        ax.plot(xs, ys, marker="o", markersize=4,
                                linewidth=1.5, label=name)
                ax.set_ylabel("Bestand")
                ax.set_title("Merch-Bestand im Zeitverlauf", color="#333")
                ax.legend(fontsize=7, loc="best")
                ax.grid(True, alpha=0.3)
                fig.autofmt_xdate()
                fig.tight_layout()
                buf = BytesIO()
                fig.savefig(buf, format="png", dpi=120,
                            bbox_inches="tight")
                buf.seek(0)
                story.append(RLImage(buf, width=500, height=250))
            except Exception as exc:
                story.append(Paragraph(
                    f"(Chart konnte nicht erzeugt werden: {exc})",
                    s["Normal"]))

        # Historie
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

        story.append(Paragraph(
            f"Kunde #{k['id']}  ·  Kategorie: {k['kategorie_name'] or '–'}  ·  "
            f"Priorität: {prio}  ·  {stand}", s["MSub"]))

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
        hist = []
        if k["uuid"]:
            hist = self.db.status_history(k["uuid"])
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
#  Kleine UI
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
        self.resize(760, 580)
        self.db: ReadDB | None = None
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

        # Optionen
        opt_box = QGroupBox("Berichts-Inhalt")
        ol = QVBoxLayout(opt_box)
        self.cb_overview = QCheckBox("Titelseite + Gesamtübersicht")
        self.cb_overview.setChecked(True)
        self.cb_merch = QCheckBox("Merch-Bestand, Verlauf & Historie")
        self.cb_merch.setChecked(True)
        self.cb_chart = QCheckBox("Diagramm im Merch-Kapitel (benötigt matplotlib)")
        self.cb_chart.setChecked(HAS_MPL)
        self.cb_chart.setEnabled(HAS_MPL)
        self.cb_customers = QCheckBox("Pro Kunde eine eigene Seite")
        self.cb_customers.setChecked(True)
        ol.addWidget(self.cb_overview)
        ol.addWidget(self.cb_merch)
        ol.addWidget(self.cb_chart)
        ol.addWidget(self.cb_customers)
        v.addWidget(opt_box)

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
        v.addWidget(self.log, 1)

        self.setStatusBar(QStatusBar())

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
        self._log(f"Datenbank geladen: {self.ed_db.text()}")
        self._log(f"{len(rows)} Messe(n) gefunden.")

    # ------------------------------------------------------------------
    def _export(self):
        if not self.db:
            self._warn("Keine Datenbank geladen.")
            return
        messe_id = self.cb_messe.currentData()
        if not messe_id:
            self._warn("Bitte eine Messe auswählen.")
            return

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
            self._log(f"Optionen: overview={self.cb_overview.isChecked()}, "
                      f"merch={self.cb_merch.isChecked()}, "
                      f"chart={self.cb_chart.isChecked()}, "
                      f"customers={self.cb_customers.isChecked()}")
            exporter = PDFExporter(
                self.db, messe_id, Path(path),
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