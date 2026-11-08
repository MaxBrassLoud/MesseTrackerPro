#!/usr/bin/env python3
"""
messe_tracker_ui.py
===================

PyQt5-Oberfläche für den Messe Tracker – liest die Log-Daten direkt
über die serielle CLI des Flippers (USB CDC-ACM, kein Massenspeicher
nötig) und zeigt sie im Flipper-Farbschema an.

Neu: Live-Log-Fenster in der UI und 100% robuste, zeitbasierte
Serielle Kommunikation (wie das Diagnose-Tool).
"""
from __future__ import annotations

import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

import serial
from serial.tools import list_ports

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QMessageBox, QFileDialog, QHeaderView,
    QAbstractItemView, QGroupBox, QLineEdit, QFrame, QStatusBar,
    QTextEdit
)

# ===========================================================================
# Konfiguration
# ===========================================================================
APP_DIR = "/ext/apps_data/messe_tracker"
DAYS_DIR = f"{APP_DIR}/days"
CONFIG_PATH = f"{APP_DIR}/config.txt"
STATE_PATH = f"{APP_DIR}/state.txt"

FLIPPER = {
    "bg_main": "#000000",
    "bg_panel": "#111111",
    "bg_input": "#1a1a1a",
    "fg_text": "#eeeeee",
    "fg_muted": "#aaaaaa",
    "accent": "#FF8200",
    "accent_hover": "#ffa040",
    "accent_fg": "#000000",
    "border": "#333333",
    "success": "#4ade80",
    "danger": "#ff6b6b",
}

QSS = f"""
QWidget {{
    background: {FLIPPER['bg_main']};
    color: {FLIPPER['fg_text']};
    font-family: 'Segoe UI', 'SF Pro', 'DejaVu Sans', Arial, sans-serif;
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {FLIPPER['bg_main']}; }}
QMessageBox {{ background: {FLIPPER['bg_panel']}; }}

QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: 22pt; color: {FLIPPER['accent']}; font-weight: 800; letter-spacing: 1px; }}
QLabel#H2 {{ font-size: 14pt; color: {FLIPPER['accent']}; font-weight: 700; }}
QLabel#Sub {{ color: {FLIPPER['fg_muted']}; font-size: 9pt; }}
QLabel#Stat {{ font-size: 28pt; color: {FLIPPER['accent']}; font-weight: 800; }}
QLabel#StatLabel {{ color: {FLIPPER['fg_muted']}; font-size: 9pt; text-transform: uppercase; letter-spacing: 1px; }}

QGroupBox {{
    background: {FLIPPER['bg_panel']};
    border: 1px solid {FLIPPER['border']};
    border-radius: 10px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 8px; color: {FLIPPER['accent']}; font-size: 10pt; }}

QPushButton {{
    background: {FLIPPER['accent']};
    color: {FLIPPER['accent_fg']};
    border: 0;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: 700;
    font-size: 10pt;
}}
QPushButton:hover {{ background: {FLIPPER['accent_hover']}; }}
QPushButton:pressed {{ background: #e67500; }}
QPushButton:disabled {{ background: {FLIPPER['border']}; color: {FLIPPER['fg_muted']}; }}
QPushButton#Ghost {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; border: 1px solid {FLIPPER['border']}; font-weight: 600; }}
QPushButton#Ghost:hover {{ background: #222; border-color: {FLIPPER['accent']}; }}

QLineEdit, QComboBox, QTextEdit {{
    background: {FLIPPER['bg_input']};
    color: {FLIPPER['fg_text']};
    border: 1px solid {FLIPPER['border']};
    border-radius: 6px;
    padding: 8px 10px;
    selection-background-color: {FLIPPER['accent']};
    selection-color: {FLIPPER['accent_fg']};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {FLIPPER['accent']}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {FLIPPER['bg_input']};
    color: {FLIPPER['fg_text']};
    selection-background-color: {FLIPPER['accent']};
    selection-color: {FLIPPER['accent_fg']};
    border: 1px solid {FLIPPER['border']};
}}

QTableWidget {{
    background: {FLIPPER['bg_panel']};
    alternate-background-color: {FLIPPER['bg_input']};
    color: {FLIPPER['fg_text']};
    gridline-color: {FLIPPER['border']};
    border: 1px solid {FLIPPER['border']};
    border-radius: 6px;
}}
QTableWidget::item {{ padding: 6px; }}
QTableWidget::item:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
QHeaderView::section {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['accent']}; padding: 8px; border: 0; border-bottom: 1px solid {FLIPPER['border']}; font-weight: 700; font-size: 9pt; }}

QTabWidget::pane {{ border: 1px solid {FLIPPER['border']}; border-radius: 8px; background: {FLIPPER['bg_panel']}; top: -1px; }}
QTabBar::tab {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; padding: 10px 22px; border: 1px solid {FLIPPER['border']}; border-bottom: 0; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
QTabBar::tab:hover:!selected {{ background: #222; }}

QStatusBar {{ background: {FLIPPER['bg_panel']}; color: {FLIPPER['fg_muted']}; border-top: 1px solid {FLIPPER['border']}; }}
QStatusBar::item {{ border: 0; }}

QScrollBar:vertical {{ background: {FLIPPER['bg_main']}; width: 12px; border: 0; }}
QScrollBar::handle:vertical {{ background: {FLIPPER['border']}; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {FLIPPER['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


# ===========================================================================
# Flipper CLI Client (Drain-basiert, 100% wie das Diagnose-Tool)
# ===========================================================================
class FlipperCLI:
    def __init__(self, port, log_func):
        self.port = port
        self.log = log_func
        self.log(f"Öffne seriellen Port {port} (115200 Baud) …")
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=2)
        except Exception as e:
            self.log(f"FEHLER beim Öffnen: {e}")
            raise

        time.sleep(0.3)
        self._drain("Initialisierung")
        self.ser.write(b"\r\n")
        time.sleep(0.2)
        self._drain("Initial-Prompt")

    def _drain(self, label=""):
        """Liest alles, was kommt, bis für 100ms Ruhe ist (wie Diagnose-Tool)."""
        raw = b""
        end_time = time.time() + 2.0  # Maximal 2 Sekunden warten
        while time.time() < end_time:
            if self.ser.in_waiting:
                raw += self.ser.read(self.ser.in_waiting)
                end_time = time.time() + 0.1  # Timer zurücksetzen bei neuen Daten
            else:
                time.sleep(0.01)

        if raw:
            if len(raw) > 100:
                self.log(f"[{label}] Empfangen ({len(raw)} Bytes)")
            else:
                self.log(f"[{label}] Roh: {raw!r}")
        return raw

    def command(self, cmd):
        self.log(f"→ {cmd}")
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r\n").encode())
        self.ser.flush()

        raw = self._drain(cmd)
        text = raw.decode('utf-8', errors='replace')

        # ANSI Escape Sequences (Farben) entfernen
        text = re.sub(r'\x1b\[[0-9;]*m', '', text)
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Echo (Befehl in erster Zeile) und Prompt am Ende entfernen
        lines = text.split('\n')
        if lines and cmd in lines[0]:
            lines = lines[1:]
        if lines and lines[-1].strip() in (">:", ">"):
            lines = lines[:-1]

        result = "\n".join(lines).strip()

        if cmd.startswith("storage read"):
            result = re.sub(r'^Size:\s*\d+\s*\n', '', result, flags=re.IGNORECASE).strip()

        if result:
            preview = result if len(result) < 300 else result[:300] + "…"
            self.log(f"← {preview}")
        else:
            self.log(f"← (leer)")

        return result

    def list_dir(self, path):
        out = self.command(f"storage list {path}")
        entries = []
        for line in out.split('\n'):
            line = line.strip()
            if not line: continue
            if line.startswith("[D]"):
                entries.append((line[3:].strip(), True))
            elif line.startswith("[F]"):
                name = line[3:].strip()
                if " " in name:
                    name = name.rsplit(" ", 1)[0]  # Größe abschneiden
                entries.append((name, False))
        return entries

    def read_file(self, path):
        out = self.command(f"storage read {path}")
        if "error" in out.lower() and "not" in out.lower():
            return None
        return out

    def close(self):
        self.log("Schließe Port.")
        try:
            self.ser.close()
        except Exception:
            pass


def find_ports():
    flipper_ports, other_ports = [], []
    for p in list_ports.comports():
        dev = p.device or ""
        desc = p.description or ""
        if not dev: continue

        is_flipper = (
                (getattr(p, "vid", None) == 0x0483 and getattr(p, "pid", None) == 0x5740)
                or "flipper" in desc.lower()
                or "usbmodem" in dev.lower()
        )
        entry = (dev, desc or dev)
        if is_flipper:
            flipper_ports.append(entry)
        else:
            other_ports.append(entry)
    return flipper_ports + other_ports


# ===========================================================================
# Worker (Hintergrund-Thread)
# ===========================================================================
class FetchWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port

    def run(self):
        try:
            self.finished.emit(self._fetch())
        except Exception as exc:
            self.error.emit(str(exc))

    def _fetch(self) -> dict:
        port = self.port
        if not port:
            ports = find_ports()
            if not ports:
                raise RuntimeError("Kein COM-Port gefunden. Bitte Kabel prüfen.")
            port = ports[0][0]

        cli = FlipperCLI(port, log_func=self.log.emit)
        try:
            data = {"state": None, "config": None, "days": {}, "port": port}

            self.log.emit("Lese state.txt …")
            data["state"] = cli.read_file(STATE_PATH)

            self.log.emit("Lese config.txt …")
            data["config"] = cli.read_file(CONFIG_PATH)

            self.log.emit("Liste Tages-Logs …")
            entries = cli.list_dir(DAYS_DIR)

            # Dateien extrahieren (Endung .txt)
            files = [n for n, is_dir in entries if not is_dir and n.endswith(".txt")]
            self.log.emit(f"Gefundene Log-Dateien: {len(files)}")

            if not files:
                raise RuntimeError(
                    "Keine Tages-Logs auf dem Flipper gefunden.\n\n"
                    "Bitte prüfen:\n"
                    "  1. Wurde auf dem Flipper ein Tag gestartet?\n"
                    "  2. Siehe Log-Fenster unten: Was meldet 'storage list'?"
                )

            for name in files:
                self.log.emit(f"Lese Datei: {name} …")
                content = cli.read_file(f"{DAYS_DIR}/{name}")
                if content:
                    data["days"][name[:-4]] = content

            if not data["days"]:
                raise RuntimeError("Logs gefunden, aber keine lesbar. Siehe Log-Fenster.")

            return data
        finally:
            cli.close()


# ===========================================================================
# Parsing
# ===========================================================================
def parse_kunde(line: str) -> dict | None:
    parts = line.split("|")
    if len(parts) < 7: return None
    try:
        entry = {
            "id": parts[1].lstrip("#"), "date": parts[2], "time": parts[3],
            "category": parts[4], "name": parts[5],
            "company": "", "email": "", "phone": "", "notes": "",
        }
        if len(parts) >= 10:
            entry.update(company=parts[6], email=parts[7], phone=parts[8], notes=parts[9])
        else:
            entry["notes"] = parts[6]
        return entry
    except IndexError:
        return None


def parse_day(text: str, date_hint: str) -> dict:
    day = {"date": date_hint, "messe": "", "contacts": [], "merch": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith("MESSE "):
            day["messe"] = line[6:]
        elif line.startswith("KUNDE|"):
            c = parse_kunde(line)
            if c: day["contacts"].append(c)
        elif line.startswith("MERCH "):
            parts = line.split(" ", 2)
            if len(parts) == 3:
                name, _, val = parts[2].rpartition(";")
                try:
                    day["merch"].append({"action": parts[1], "name": name, "value": int(val)})
                except ValueError:
                    pass
    return day


def build_days(data: dict) -> list[dict]:
    days = []
    for date_hint, text in data.get("days", {}).items():
        days.append(parse_day(text, date_hint))
    days.sort(key=lambda d: d["date"])
    return days


# ===========================================================================
# Widgets (StatCard, Overview, Contacts, Merch, Export)
# ===========================================================================
class StatCard(QWidget):
    def __init__(self, label: str, value: str = "—"):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(2)
        self._value = QLabel(value)
        self._value.setObjectName("Stat")
        v.addWidget(self._value)
        lbl = QLabel(label)
        lbl.setObjectName("StatLabel")
        v.addWidget(lbl)
        self.setStyleSheet(
            f"StatCard {{ background: {FLIPPER['bg_panel']}; border: 1px solid {FLIPPER['border']}; border-radius: 10px; }}")

    def set_value(self, text: str): self._value.setText(text)


def make_stat_row(values):
    row = QHBoxLayout()
    row.setSpacing(12)
    for label, value in values:
        row.addWidget(StatCard(label, value), 1)
    return row


class OverviewTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stat_row = make_stat_row([("Tage", "—"), ("Kontakte", "—"), ("Messen", "—"), ("Kategorien", "—")])
        self.stat_cards = [self.stat_row.itemAt(i).widget() for i in range(self.stat_row.count())]
        outer.addLayout(self.stat_row)

        split = QHBoxLayout()
        split.setSpacing(12)
        self.messe_box = QGroupBox("Kontakte pro Messe")
        self.messe_layout = QVBoxLayout(self.messe_box)
        split.addWidget(self.messe_box, 1)
        self.cat_box = QGroupBox("Kontakte pro Kategorie")
        self.cat_layout = QVBoxLayout(self.cat_box)
        split.addWidget(self.cat_box, 1)
        outer.addLayout(split)

        recent_box = QGroupBox("Letzte Kontakte")
        rv = QVBoxLayout(recent_box)
        self.recent = QTableWidget(0, 5)
        self.recent.setHorizontalHeaderLabels(["Datum", "Messe", "Kategorie", "Name", "Firma"])
        self.recent.verticalHeader().setVisible(False)
        self.recent.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent.setAlternatingRowColors(True)
        h = self.recent.horizontalHeader()
        for i in range(3): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        rv.addWidget(self.recent)
        outer.addWidget(recent_box, 1)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def update_from_days(self, days):
        total = sum(len(d["contacts"]) for d in days)
        messen = {d["messe"] for d in days if d["messe"]}
        cats = Counter()
        for d in days:
            for c in d["contacts"]: cats[c["category"] or "(leer)"] += 1

        self.stat_cards[0].set_value(str(len(days)))
        self.stat_cards[1].set_value(str(total))
        self.stat_cards[2].set_value(str(len(messen)))
        self.stat_cards[3].set_value(str(len(cats)))

        self._clear(self.messe_layout)
        by_messe = Counter()
        for d in days: by_messe[d["messe"] or "(ohne Messe)"] += len(d["contacts"])
        for name, count in by_messe.most_common():
            self.messe_layout.addWidget(self._bar_row(name, count, max(by_messe.values()) if by_messe else 1))
        self.messe_layout.addStretch(1)

        self._clear(self.cat_layout)
        for name, count in cats.most_common():
            self.cat_layout.addWidget(self._bar_row(name, count, max(cats.values()) if cats else 1))
        self.cat_layout.addStretch(1)

        contacts = [(d["messe"], c) for d in days for c in d["contacts"]]
        contacts.sort(key=lambda x: (x[1]["date"], x[1]["time"]), reverse=True)
        self.recent.setRowCount(min(10, len(contacts)))
        for r, (m, c) in enumerate(contacts[:10]):
            self.recent.setItem(r, 0, QTableWidgetItem(f"{c['date']} {c['time']}".strip()))
            self.recent.setItem(r, 1, QTableWidgetItem(m or "—"))
            self.recent.setItem(r, 2, QTableWidgetItem(c["category"] or "—"))
            self.recent.setItem(r, 3, QTableWidgetItem(c["name"] or "—"))
            self.recent.setItem(r, 4, QTableWidgetItem(c["company"] or "—"))

    def _bar_row(self, name, value, maxval):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(name)
        lbl.setMinimumWidth(120)
        h.addWidget(lbl)
        bar = QFrame()
        bar.setFixedHeight(10)
        bar.setStyleSheet(f"background: {FLIPPER['accent']}; border-radius: 5px;")
        bar.setFixedWidth(max(6, int((value / maxval) * 300)))
        h.addWidget(bar)
        val_lbl = QLabel(str(value))
        val_lbl.setStyleSheet(f"color: {FLIPPER['accent']}; font-weight: 700;")
        h.addWidget(val_lbl)
        h.addStretch(1)
        return w


class ContactsTab(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suche …")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)
        self.counter = QLabel("0 Kontakte")
        self.counter.setObjectName("Sub")
        top.addWidget(self.counter)
        v.addLayout(top)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Datum", "Messe", "Kategorie", "Name", "Firma", "E-Mail", "Telefon", "Notiz"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        for i in range(3): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(7, QHeaderView.Stretch)
        v.addWidget(self.table)
        self._rows = []

    def update_from_days(self, days):
        self._rows = []
        for d in days:
            for c in d["contacts"]:
                self._rows.append(
                    [f"{c['date']} {c['time']}".strip(), d["messe"] or "—", c["category"] or "—", c["name"] or "—",
                     c["company"] or "—", c["email"] or "—", c["phone"] or "—", c["notes"] or ""])
        self._rows.sort(key=lambda r: r[0], reverse=True)
        self._apply_filter()

    def _apply_filter(self):
        needle = self.search.text().strip().lower()
        rows = [r for r in self._rows if not needle or any(needle in cell.lower() for cell in r)]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(cell))
        self.table.setSortingEnabled(True)
        self.counter.setText(f"{len(rows)} Kontakte")


class MerchTab(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Artikel", "Aktueller Bestand"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        v.addWidget(self.table)

    def update_from_days(self, days):
        stock = {}
        for d in days:
            for m in d["merch"]:
                if m["action"] in ("BESTAND", "NACHGEFUELLT"):
                    stock[m["name"]] = m["value"]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(stock))
        for r, (name, value) in enumerate(sorted(stock.items())):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            v_item = QTableWidgetItem(str(value))
            v_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, v_item)
        self.table.setSortingEnabled(True)


class ExportTab(QWidget):
    def __init__(self):
        super().__init__()
        self._days = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("CSV-Export", objectName="H2"))
        v.addWidget(QLabel("Exportiert alle Kontakte als semikolon-getrennte CSV.", objectName="Sub"))
        self.info = QLabel("Noch keine Daten geladen.", objectName="Sub")
        v.addWidget(self.info)
        btn = QPushButton("CSV-Datei speichern …")
        btn.clicked.connect(self._export)
        v.addWidget(btn)
        v.addStretch(1)

    def update_from_days(self, days):
        self._days = days
        total = sum(len(d["contacts"]) for d in days)
        self.info.setText(f"{total} Kontakte aus {len(days)} Tag(en) bereit.")

    def _export(self):
        if not self._days:
            QMessageBox.information(self, "Keine Daten", "Bitte zuerst Daten laden.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "CSV speichern", "kontakte.csv", "CSV (*.csv)")
        if not path: return
        if not path.lower().endswith(".csv"): path += ".csv"

        count = 0
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(
                ["Messe", "Datum", "Zeit", "ID", "Kategorie", "Name", "Firma", "E-Mail", "Telefon", "Notiz"])
            for d in self._days:
                for c in d["contacts"]:
                    writer.writerow(
                        [d["messe"], c["date"], c["time"], c["id"], c["category"], c["name"], c["company"], c["email"],
                         c["phone"], c["notes"]])
                    count += 1
        QMessageBox.information(self, "Export fertig", f"{count} Kontakte gespeichert in:\n{path}")


# ===========================================================================
# Hauptfenster
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messe Tracker – Flipper Sync")
        self.resize(1180, 850)  # Etwas höher für das Log-Fenster
        self.worker = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 12)

        # Kopfzeile
        header = QHBoxLayout()
        header.addWidget(QLabel("MESSE TRACKER", objectName="H1"))
        header.addWidget(QLabel("Flipper Sync", objectName="Sub"))
        header.addStretch(1)
        header.addWidget(QLabel("Port:", objectName="Sub"))

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        self._refresh_ports()
        header.addWidget(self.port_combo)

        btn_refresh = QPushButton("↻")
        btn_refresh.setObjectName("Ghost")
        btn_refresh.setFixedWidth(40)
        btn_refresh.clicked.connect(self._refresh_ports)
        header.addWidget(btn_refresh)

        self.connect_btn = QPushButton("Verbinden & Laden")
        self.connect_btn.clicked.connect(self._connect)
        header.addWidget(self.connect_btn)
        root.addLayout(header)

        # Statuszeile
        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {FLIPPER['fg_muted']}; font-size: 14pt;")
        status_row.addWidget(self.status_dot)
        self.status_label = QLabel("Nicht verbunden", objectName="Sub")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_overview = OverviewTab()
        self.tab_contacts = ContactsTab()
        self.tab_merch = MerchTab()
        self.tab_export = ExportTab()
        self.tabs.addTab(self.tab_overview, "Übersicht")
        self.tabs.addTab(self.tab_contacts, "Kontakte")
        self.tabs.addTab(self.tab_merch, "Merch")
        self.tabs.addTab(self.tab_export, "Export")
        root.addWidget(self.tabs, 2)  # Hauptbereich

        # === NEU: LOG-FENSTER ===
        log_box = QGroupBox("Verbindungs-Logs (Debug)")
        lb_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 9pt; background: #050505;")
        self.log_view.setMinimumHeight(150)
        self.log_view.setMaximumHeight(250)
        lb_layout.addWidget(self.log_view)
        root.addWidget(log_box, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Bereit.")

    def _refresh_ports(self):
        curr = self.port_combo.currentData()
        self.port_combo.clear()
        self.port_combo.addItem("Auto (suchen)", None)
        for dev, desc in find_ports():
            self.port_combo.addItem(f"{dev} — {desc}", dev)
        if curr:
            idx = self.port_combo.findData(curr)
            if idx >= 0: self.port_combo.setCurrentIndex(idx)

    def _set_status(self, state, text):
        colors = {"idle": FLIPPER["fg_muted"], "busy": FLIPPER["accent"], "ok": FLIPPER["success"],
                  "error": FLIPPER["danger"]}
        self.status_dot.setStyleSheet(f"color: {colors.get(state, FLIPPER['fg_muted'])}; font-size: 14pt;")
        self.status_label.setText(text)

    def _connect(self):
        if self.worker and self.worker.isRunning(): return
        port = self.port_combo.currentData()

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Verbinde …")
        self._set_status("busy", "Verbinde mit Flipper …")
        self.log_view.clear()
        self.log_view.append(f"--- Starte Verbindung ({time.strftime('%H:%M:%S')}) ---")

        self.worker = FetchWorker(port)
        self.worker.log.connect(self.log_view.append)
        self.worker.finished.connect(self._on_data)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(lambda: self._worker_done())
        self.worker.error.connect(lambda: self._worker_done())
        self.worker.start()

    def _worker_done(self):
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Aktualisieren")

    def _on_error(self, msg):
        self._set_status("error", "Verbindung fehlgeschlagen")
        self.log_view.append(f"❌ FEHLER: {msg}")
        QMessageBox.critical(self, "Verbindung fehlgeschlagen", msg)

    def _on_data(self, data):
        days = build_days(data)
        total = sum(len(d["contacts"]) for d in days)
        port = data.get("port") or "?"

        self._set_status("ok", f"Erfolgreich geladen über {port}")
        self.tab_overview.update_from_days(days)
        self.tab_contacts.update_from_days(days)
        self.tab_merch.update_from_days(days)
        self.tab_export.update_from_days(days)
        self.log_view.append(f"✅ Erfolg: {len(days)} Tag(e), {total} Kontakte verarbeitet.")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(2000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())