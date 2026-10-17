"""Auswertung: interaktive Timeline-Charts mit matplotlib."""
import os
from datetime import datetime
from collections import defaultdict

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTabWidget, QComboBox, QTableWidget,
                             QTableWidgetItem, QFileDialog, QMessageBox,
                             QSizePolicy)
from PyQt5.QtCore import Qt

from core.export import export_contacts_csv


def _parse_dt(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


def _theme_colors(theme):
    return dict(
        bg=theme["bg_panel"], fg=theme["fg_text"], muted=theme["fg_muted"],
        accent=theme["accent"], border=theme["border"], main=theme["bg_main"],
    )


def _style_axes(ax, c):
    ax.set_facecolor(c["bg"])
    for spine in ax.spines.values():
        spine.set_color(c["border"])
    ax.tick_params(colors=c["fg"], labelsize=8)
    ax.xaxis.label.set_color(c["fg"])
    ax.yaxis.label.set_color(c["fg"])
    ax.title.set_color(c["accent"])
    ax.title.set_fontweight("bold")
    ax.grid(True, color=c["border"], alpha=0.35, linestyle="--", linewidth=0.5)


def _style_figure(fig, c):
    fig.patch.set_facecolor(c["bg"])


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=9, height=4.5, dpi=90):
        self.fig = Figure(figsize=(width, height), dpi=dpi,
                          constrained_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(300)


# ======================================================================
# Tab 1 – Übersicht
# ======================================================================
class OverviewTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.stats = QLabel()
        self.stats.setStyleSheet("font-size:11pt;padding:6px;")
        bar.addWidget(self.stats, 1)
        btn = QPushButton("Aktualisieren")
        btn.setObjectName("Ghost")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.canvas = MplCanvas(self, height=7)
        v.addWidget(self.canvas, 1)

    def refresh(self):
        fair_id = self.ctx.current_fair_id
        fig = self.canvas.fig
        fig.clear()
        colors = _theme_colors(self.main.current_theme)
        _style_figure(fig, colors)
        if not fair_id:
            self.stats.setText("Bitte zuerst eine Messe auswählen.")
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Keine Messe ausgewählt", ha='center',
                    va='center', color=colors["fg"], transform=ax.transAxes)
            _style_axes(ax, colors)
            self.canvas.draw()
            return

        db = self.ctx.db
        contacts = db.search_contacts(fair_id=fair_id)
        companies = {c["company"] for c in contacts if c["company"]}
        fair_days = db.list_fair_days(fair_id)
        intervals = db.attendance_intervals(fair_id)
        total_blocks = sum(len(v) for v in intervals.values())

        self.stats.setText(
            f"<b>{len(contacts)}</b> Kontakte · "
            f"<b>{len(companies)}</b> Unternehmen · "
            f"<b>{len(fair_days)}</b> Messetage · "
            f"<b>{total_blocks}</b> Anwesenheitsblöcke")

        ax1 = fig.add_subplot(2, 2, 1)
        ax2 = fig.add_subplot(2, 2, 2)
        ax3 = fig.add_subplot(2, 2, 3)
        ax4 = fig.add_subplot(2, 2, 4)

        # 1 – Kumulierte Kontakte
        tl = db.cumulative_contacts_timeline(fair_id)
        ax1.set_title("Kumulierte Kontakte")
        if tl:
            xs = [_parse_dt(t) for t, _ in tl]
            ys = [n for _, n in tl]
            ax1.step(xs, ys, where='post', color=colors["accent"], linewidth=2)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.'))
            ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax1.set_ylabel("Anzahl")
        else:
            ax1.text(.5, .5, "Keine Daten", ha='center', va='center',
                     color=colors["fg"], transform=ax1.transAxes)
        _style_axes(ax1, colors)

        # 2 – Kontakte pro Tag
        ax2.set_title("Kontakte pro Tag")
        by_day = db.contacts_by_day(fair_id)
        if by_day:
            days = [d for d, _ in by_day]
            counts = [c for _, c in by_day]
            ax2.bar(range(len(days)), counts, color=colors["accent"])
            ax2.set_xticks(range(len(days)))
            ax2.set_xticklabels(days, rotation=30, ha='right')
            ax2.set_ylabel("Anzahl")
        else:
            ax2.text(.5, .5, "Keine Daten", ha='center', va='center',
                     color=colors["fg"], transform=ax2.transAxes)
        _style_axes(ax2, colors)

        # 3 – Kontakte nach Stunde
        ax3.set_title("Kontakte nach Tageszeit")
        by_hour = db.contacts_by_hour(fair_id)
        if by_hour:
            hours = [h for h, _ in by_hour]
            counts = [c for _, c in by_hour]
            ax3.bar(hours, counts, color=colors["accent"])
            ax3.set_xlabel("Stunde")
            ax3.set_ylabel("Anzahl")
        else:
            ax3.text(.5, .5, "Keine Daten", ha='center', va='center',
                     color=colors["fg"], transform=ax3.transAxes)
        _style_axes(ax3, colors)

        # 4 – Status-Verteilung
        ax4.set_title("Status-Verteilung")
        stats = db.dashboard_stats(fair_id)
        active = {k: v for k, v in stats["by_status"].items() if v > 0}
        if active:
            status_colors = {s["name"]: s["color"]
                             for s in db.list_statuses()}
            palette = [status_colors.get(k, colors["accent"]) for k in active]
            wedges, texts, autotexts = ax4.pie(
                active.values(), labels=list(active.keys()),
                autopct='%1.0f%%', colors=palette, startangle=90)
            for t in texts + autotexts:
                t.set_color(colors["fg"])
                t.set_fontsize(9)
        else:
            ax4.text(.5, .5, "Keine Daten", ha='center', va='center',
                     color=colors["fg"], transform=ax4.transAxes)
        self.canvas.draw()


# ======================================================================
# Tab 2 – Kontakte-Verlauf
# ======================================================================
class ContactsTimelineTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Kumulierte Kontakte pro Status"))
        bar.addStretch(1)
        btn = QPushButton("Aktualisieren")
        btn.setObjectName("Ghost")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.canvas = MplCanvas(self, height=4)
        v.addWidget(self.canvas, 2)
        v.addWidget(QLabel("Letzte 30 Kontakte (chronologisch)"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Zeit", "Name", "Firma", "Status", "Quelle", "Mitarbeiter"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)

    def refresh(self):
        fig = self.canvas.fig
        fig.clear()
        colors = _theme_colors(self.main.current_theme)
        _style_figure(fig, colors)
        ax = fig.add_subplot(111)
        ax.set_title("Kumulierte Kontakte pro Status")
        _style_axes(ax, colors)

        if not self.ctx.current_fair_id:
            self.table.setRowCount(0)
            self.canvas.draw()
            return

        db = self.ctx.db
        tl = db.status_timeline(self.ctx.current_fair_id)
        status_colors = {s["name"]: s["color"] for s in db.list_statuses()}
        if tl:
            for status, points in tl.items():
                xs = [_parse_dt(t) for t, _ in points]
                ys = [n for _, n in points]
                if not xs:
                    continue
                ax.step(xs, ys, where='post',
                        label=status,
                        color=status_colors.get(status, colors["accent"]),
                        linewidth=2)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m. %H:%M'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            fig.autofmt_xdate(rotation=25, ha='right')
            ax.set_ylabel("Kontakte (kumuliert)")
            ax.legend(loc="upper left", facecolor=colors["bg"],
                      edgecolor=colors["border"], labelcolor=colors["fg"],
                      fontsize=9)
        else:
            ax.text(.5, .5, "Keine Daten", ha='center', va='center',
                    color=colors["fg"], transform=ax.transAxes)
        self.canvas.draw()

        # Tabelle
        rows = db.search_contacts(fair_id=self.ctx.current_fair_id)[:30]
        emps = {e["id"]: e["name"] for e in db.list_employees()}
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            values = [
                _fmt_dt(c["created_at"]),
                c.get("name") or "",
                c.get("company") or "",
                c.get("status") or "",
                c.get("source") or "",
                emps.get(c.get("employee_id"), ""),
            ]
            for col, val in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(str(val)))


# ======================================================================
# Tab 3 – Merch-Entwicklung
# ======================================================================
class MerchTimelineTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Artikel:"))
        self.item_combo = QComboBox()
        self.item_combo.currentIndexChanged.connect(self._replot)
        bar.addWidget(self.item_combo, 1)
        btn = QPushButton("Aktualisieren")
        btn.setObjectName("Ghost")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.canvas = MplCanvas(self, height=4)
        v.addWidget(self.canvas, 2)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Zeit", "Gezählt", "Ausgabe seit vorher", "Kumulativ ausgegeben",
             "Mitarbeiter", "Notiz"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)

    def refresh(self):
        self.item_combo.blockSignals(True)
        current = self.item_combo.currentData()
        self.item_combo.clear()
        if self.ctx.current_fair_id:
            for it in self.ctx.db.list_merch_items(self.ctx.current_fair_id):
                self.item_combo.addItem(it["name"], it["id"])
        if current is not None:
            idx = self.item_combo.findData(current)
            if idx >= 0:
                self.item_combo.setCurrentIndex(idx)
        self.item_combo.blockSignals(False)
        self._replot()

    def _replot(self):
        fig = self.canvas.fig
        fig.clear()
        colors = _theme_colors(self.main.current_theme)
        _style_figure(fig, colors)
        ax = fig.add_subplot(111)
        ax2 = ax.twinx()
        ax2.set_facecolor(colors["bg"])
        ax2.tick_params(colors=colors["muted"], labelsize=8)
        ax2.yaxis.label.set_color(colors["muted"])

        item_id = self.item_combo.currentData()
        self.table.setRowCount(0)
        if item_id is None:
            ax.text(.5, .5, "Kein Artikel vorhanden", ha='center', va='center',
                    color=colors["fg"], transform=ax.transAxes)
            _style_axes(ax, colors)
            self.canvas.draw()
            return

        db = self.ctx.db
        series = db.merch_series(item_id)
        ax.set_title(f"Merch-Verlauf: {self.item_combo.currentText()}")
        if not series:
            ax.text(.5, .5, "Noch keine Zählungen", ha='center', va='center',
                    color=colors["fg"], transform=ax.transAxes)
            _style_axes(ax, colors)
            self.canvas.draw()
            return

        xs = [_parse_dt(s["timestamp"]) for s in series]
        stocks = [s["counted_stock"] for s in series]
        cumulative = [s["cumulative"] for s in series]

        ax.plot(xs, stocks, color=colors["accent"], marker='o',
                linewidth=2, markersize=7, label="Bestand")
        ax.fill_between(xs, stocks, color=colors["accent"], alpha=0.15)
        ax.set_ylabel("Bestand (gezählt)", color=colors["accent"])
        ax.tick_params(axis='y', colors=colors["accent"])
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m. %H:%M'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate(rotation=25, ha='right')

        ax2.plot(xs, cumulative, color="#4A9EFF", marker='s',
                 linewidth=1.6, markersize=5, linestyle='--',
                 label="Kumulativ ausgegeben")
        ax2.set_ylabel("Kumulativ ausgegeben", color="#4A9EFF")

        _style_axes(ax, colors)

        # Legende kombinieren
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left",
                  facecolor=colors["bg"], edgecolor=colors["border"],
                  labelcolor=colors["fg"], fontsize=9)

        self.canvas.draw()

        # Tabelle
        emps = {e["id"]: e["name"] for e in db.list_employees()}
        # Für Mitarbeiter-Info: aus merch_counts direkt laden
        with db._lock:
            rows = db.conn.execute(
                """SELECT timestamp, counted_stock, issued_since_previous,
                          employee_id, note
                   FROM merch_counts WHERE item_id=?
                   ORDER BY timestamp, id""", (item_id,)).fetchall()
        self.table.setRowCount(len(rows))
        cum = 0
        for r, row in enumerate(rows):
            cum += row["issued_since_previous"]
            values = [
                _fmt_dt(row["timestamp"]),
                row["counted_stock"],
                row["issued_since_previous"],
                cum,
                emps.get(row["employee_id"], ""),
                row["note"] or "",
            ]
            for col, val in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(str(val)))


# ======================================================================
# Tab 4 – Anwesenheit (Gantt)
# ======================================================================
class AttendanceGanttTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.info = QLabel()
        self.info.setStyleSheet("padding:4px;")
        bar.addWidget(self.info, 1)
        btn = QPushButton("Aktualisieren")
        btn.setObjectName("Ghost")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.canvas = MplCanvas(self, height=4)
        v.addWidget(self.canvas, 2)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Mitarbeiter", "Anwesenheitsblöcke",
             "Gesamtdauer", "Letztes Ereignis"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)

    def refresh(self):
        fig = self.canvas.fig
        fig.clear()
        colors = _theme_colors(self.main.current_theme)
        _style_figure(fig, colors)
        ax = fig.add_subplot(111)
        ax.set_title("Anwesenheits-Timeline")
        _style_axes(ax, colors)

        if not self.ctx.current_fair_id:
            self.table.setRowCount(0)
            self.canvas.draw()
            return

        db = self.ctx.db
        intervals = db.attendance_intervals(self.ctx.current_fair_id)
        emps = {e["id"]: e["name"] for e in db.list_employees()}
        active_emps = {e["id"] for e in db.list_employees(active_only=True)}
        no_events = active_emps - set(intervals.keys())

        if not intervals:
            ax.text(.5, .5, "Keine Anwesenheitsdaten", ha='center', va='center',
                    color=colors["fg"], transform=ax.transAxes)
            self.canvas.draw()
            self._fill_table({}, emps, {})
            return

        # Daten für Gantt + Tabelle aufbereiten
        rows = []
        for emp_id, spans in intervals.items():
            total_sec = 0
            for start, end in spans:
                s_dt, e_dt = _parse_dt(start), _parse_dt(end)
                if s_dt and e_dt:
                    total_sec += max(0, (e_dt - s_dt).total_seconds())
            last_end = max((e for _, e in spans), default="")
            rows.append((emp_id, spans, total_sec, last_end))

        # Nach Name sortieren
        rows.sort(key=lambda r: emps.get(r[0], ""))
        labels = []
        for idx, (emp_id, spans, total_sec, _last) in enumerate(rows):
            labels.append(emps.get(emp_id, f"ID {emp_id}"))
            for start, end in spans:
                s_dt, e_dt = _parse_dt(start), _parse_dt(end)
                if not s_dt or not e_dt:
                    continue
                ax.barh(idx, (e_dt - s_dt).total_seconds() / 86400,
                        left=s_dt, height=0.65,
                        color=colors["accent"], alpha=0.85,
                        edgecolor=colors["border"], linewidth=0.5)

        # Dynamische Höhe
        self.canvas.setMinimumHeight(max(300, 50 * len(rows) + 120))
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m. %H:%M'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate(rotation=25, ha='right')
        ax.set_xlabel("Zeit")
        self.canvas.draw()

        # Info-Zeile
        msg = f"{len(intervals)} Mitarbeiter mit Anwesenheitsereignissen"
        if no_events:
            names = ", ".join(emps.get(i, f"ID {i}") for i in no_events)
            msg += f" · Ohne Ereignisse: {names}"
        self.info.setText(msg)

        # Tabelle
        self._fill_table(intervals, emps, dict((r[0], r) for r in rows))

    def _fill_table(self, intervals, emps, rows_map):
        self.table.setRowCount(len(rows_map))
        for r, (emp_id, (_eid, spans, total_sec, last_end)) in enumerate(
                rows_map.items()):
            hours = total_sec / 3600
            values = [
                emps.get(emp_id, f"ID {emp_id}"),
                len(spans),
                f"{hours:.2f} h",
                _fmt_dt(last_end),
            ]
            for col, val in enumerate(values):
                self.table.setItem(r, col, QTableWidgetItem(str(val)))


# ======================================================================
# Tab 5 – Unternehmen / Neukunden
# ======================================================================
class CompaniesTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Kumulierte eindeutige Unternehmen"))
        bar.addStretch(1)
        btn = QPushButton("Aktualisieren")
        btn.setObjectName("Ghost")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        v.addLayout(bar)
        self.canvas = MplCanvas(self, height=3.5)
        v.addWidget(self.canvas, 2)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Erstkontakt", "Unternehmen", "Anzahl Kontakte"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)

    def refresh(self):
        fig = self.canvas.fig
        fig.clear()
        colors = _theme_colors(self.main.current_theme)
        _style_figure(fig, colors)
        ax = fig.add_subplot(111)
        ax.set_title("Neue Unternehmen im Zeitverlauf")
        _style_axes(ax, colors)

        if not self.ctx.current_fair_id:
            self.table.setRowCount(0)
            self.canvas.draw()
            return

        db = self.ctx.db
        tl = db.unique_companies_timeline(self.ctx.current_fair_id)
        if tl:
            xs = [_parse_dt(t) for t, _ in tl]
            ys = list(range(1, len(tl) + 1))
            ax.step(xs, ys, where='post', color=colors["accent"], linewidth=2)
            ax.scatter(xs, ys, color=colors["accent"], s=25, zorder=3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m. %H:%M'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            fig.autofmt_xdate(rotation=25, ha='right')
            ax.set_ylabel("Unternehmen (kumuliert)")
        else:
            ax.text(.5, .5, "Keine Daten", ha='center', va='center',
                    color=colors["fg"], transform=ax.transAxes)
        self.canvas.draw()

        # Tabelle: Unternehmen mit Konten
        rows = db.search_contacts(fair_id=self.ctx.current_fair_id)
        counts = defaultdict(int)
        first = {}
        for c in rows:
            company = c.get("company") or ""
            if not company:
                continue
            counts[company] += 1
            if company not in first or c["created_at"] < first[company]:
                first[company] = c["created_at"]
        sorted_companies = sorted(first.items(), key=lambda x: x[1])
        self.table.setRowCount(len(sorted_companies))
        for r, (company, ts) in enumerate(sorted_companies):
            self.table.setItem(r, 0, QTableWidgetItem(_fmt_dt(ts)))
            self.table.setItem(r, 1, QTableWidgetItem(company))
            self.table.setItem(r, 2, QTableWidgetItem(str(counts[company])))


# ======================================================================
# Tab 6 – Export
# ======================================================================
class ExportTab(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        t = QLabel("CSV-Export der Kundenkartei")
        t.setObjectName("Title")
        v.addWidget(t)
        v.addWidget(QLabel(
            "Exportiert alle Kontakte der aktuell gewählten Messe als CSV "
            "(UTF-8 mit BOM, Semikolon-getrennt, Excel-kompatibel)."))
        b = QPushButton("CSV exportieren")
        b.clicked.connect(self.export)
        v.addWidget(b)
        v.addStretch(1)

    def refresh(self):
        pass

    def export(self):
        if not self.ctx.current_fair_id:
            QMessageBox.warning(self, "Messe",
                                "Bitte zuerst eine Messe auswählen.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV speichern", "kontakte.csv", "CSV (*.csv)")
        if not path:
            return
        n = export_contacts_csv(self.ctx.db, self.ctx.current_fair_id, path)
        QMessageBox.information(
            self, "Export", f"{n} Kontakte exportiert nach:\n{path}")


# ======================================================================
# Hauptseite
# ======================================================================
class ReportsPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Auswertung")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch(1)
        v.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._tab_widgets = [
            OverviewTab(ctx, main),
            ContactsTimelineTab(ctx, main),
            MerchTimelineTab(ctx, main),
            AttendanceGanttTab(ctx, main),
            CompaniesTab(ctx, main),
            ExportTab(ctx, main),
        ]
        labels = ["Übersicht", "Kontakte-Verlauf", "Merch",
                  "Anwesenheit", "Unternehmen", "Export"]
        for w, label in zip(self._tab_widgets, labels):
            self.tabs.addTab(w, label)
        v.addWidget(self.tabs, 1)

    def _on_tab_changed(self, idx):
        w = self.tabs.widget(idx)
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as e:
                QMessageBox.warning(
                    self, "Fehler",
                    f"Chart konnte nicht geladen werden:\n{e}")

    def refresh(self):
        w = self.tabs.currentWidget()
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as e:
                QMessageBox.warning(
                    self, "Fehler",
                    f"Chart konnte nicht geladen werden:\n{e}")