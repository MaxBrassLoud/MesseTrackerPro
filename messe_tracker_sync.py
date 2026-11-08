#!/usr/bin/env python3
"""
messe_tracker_app.py
====================
Die Master-Anwendung für den Messe Tracker.
Der Laptop verwaltet die Datenbank, der Flipper liefert die Rohdaten.
"""
from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

import matplotlib

matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QMessageBox, QFileDialog, QHeaderView,
    QAbstractItemView, QGroupBox, QLineEdit, QStatusBar,
    QTextEdit, QDialog, QFormLayout, QDialogButtonBox,
    QCheckBox, QListWidget, QInputDialog
)

APP_DIR = "/ext/apps_data/messe_tracker"
DAYS_DIR = f"{APP_DIR}/days"
MESSEN_DIR = f"{APP_DIR}/messen"
CONFIG_PATH = f"{APP_DIR}/config.txt"
DB_PATH = Path(__file__).parent / "messe_tracker.db"

FLIPPER = {
    "bg_main": "#000000", "bg_panel": "#111111", "bg_input": "#1a1a1a",
    "fg_text": "#eeeeee", "fg_muted": "#aaaaaa", "accent": "#FF8200",
    "accent_hover": "#ffa040", "accent_fg": "#000000", "border": "#333333",
    "success": "#4ade80", "danger": "#ff6b6b",
}

QSS = f"""
QWidget {{ background: {FLIPPER['bg_main']}; color: {FLIPPER['fg_text']}; font-family: 'Segoe UI', Arial; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {FLIPPER['bg_main']}; }}
QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: 22pt; color: {FLIPPER['accent']}; font-weight: 800; }}
QLabel#H2 {{ font-size: 14pt; color: {FLIPPER['accent']}; font-weight: 700; }}
QLabel#Sub {{ color: {FLIPPER['fg_muted']}; font-size: 9pt; }}
QLabel#Stat {{ font-size: 28pt; color: {FLIPPER['accent']}; font-weight: 800; }}
QLabel#StatLabel {{ color: {FLIPPER['fg_muted']}; font-size: 9pt; text-transform: uppercase; }}
QGroupBox {{ background: {FLIPPER['bg_panel']}; border: 1px solid {FLIPPER['border']}; border-radius: 10px; margin-top: 18px; padding: 14px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 8px; color: {FLIPPER['accent']}; }}
QPushButton {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; border: 0; border-radius: 8px; padding: 10px 20px; font-weight: 700; }}
QPushButton:hover {{ background: {FLIPPER['accent_hover']}; }}
QPushButton:disabled {{ background: {FLIPPER['border']}; color: {FLIPPER['fg_muted']}; }}
QPushButton#Ghost {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; border: 1px solid {FLIPPER['border']}; }}
QLineEdit, QComboBox, QTextEdit {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; border: 1px solid {FLIPPER['border']}; border-radius: 6px; padding: 8px; }}
QTableWidget {{ background: {FLIPPER['bg_panel']}; alternate-background-color: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; gridline-color: {FLIPPER['border']}; border: 1px solid {FLIPPER['border']}; }}
QTableWidget::item:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
QHeaderView::section {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['accent']}; padding: 8px; border: 0; border-bottom: 1px solid {FLIPPER['border']}; font-weight: 700; }}
QTabWidget::pane {{ border: 1px solid {FLIPPER['border']}; border-radius: 8px; background: {FLIPPER['bg_panel']}; top: -1px; }}
QTabBar::tab {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; padding: 10px 22px; border: 1px solid {FLIPPER['border']}; border-bottom: 0; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
"""


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_db()

    def init_db(self):
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS messen (id INTEGER PRIMARY KEY, flipper_id INTEGER UNIQUE, name TEXT, ort TEXT);
                CREATE TABLE IF NOT EXISTS kategorien (id INTEGER PRIMARY KEY, flipper_id INTEGER UNIQUE, name TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS tage (id INTEGER PRIMARY KEY, messe_id INTEGER, datum TEXT, UNIQUE(messe_id, datum), FOREIGN KEY(messe_id) REFERENCES messen(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS kunden (
                    id INTEGER PRIMARY KEY, tage_id INTEGER, flipper_id TEXT,
                    zeit TEXT, kategorie_id INTEGER, name TEXT, firma TEXT,
                    email TEXT, telefon TEXT, notiz TEXT, am_stand INTEGER,
                    UNIQUE(tage_id, flipper_id), 
                    FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE,
                    FOREIGN KEY(kategorie_id) REFERENCES kategorien(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS merch_artikel (id INTEGER PRIMARY KEY, messe_id INTEGER, name TEXT, UNIQUE(messe_id, name), FOREIGN KEY(messe_id) REFERENCES messen(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS merch_aktionen (
                    id INTEGER PRIMARY KEY, artikel_id INTEGER, tage_id INTEGER,
                    zeit TEXT, aktion TEXT, wert INTEGER, FOREIGN KEY(artikel_id) REFERENCES merch_artikel(id) ON DELETE CASCADE, FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS anwesenheit (
                    id INTEGER PRIMARY KEY, tage_id INTEGER, typ TEXT, zeit TEXT, UNIQUE(tage_id, typ, zeit), FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE
                );
            """)

            # --- AUTOMATISCHE MIGRATION ---
            # 1. 'ort' in 'messen'
            cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(messen)").fetchall()]
            if "ort" not in cols: self.conn.execute("ALTER TABLE messen ADD COLUMN ort TEXT")
            if "flipper_id" not in cols: self.conn.execute("ALTER TABLE messen ADD COLUMN flipper_id INTEGER UNIQUE")

            # 2. 'flipper_id' in 'kategorien'
            cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(kategorien)").fetchall()]
            if "flipper_id" not in cols: self.conn.execute(
                "ALTER TABLE kategorien ADD COLUMN flipper_id INTEGER UNIQUE")

            # 3. 'kategorie_id' in 'kunden' (Migration von 'kategorie' Text zu ID)
            cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(kunden)").fetchall()]
            if "kategorie_id" not in cols:
                self.conn.execute("ALTER TABLE kunden ADD COLUMN kategorie_id INTEGER")
                if "kategorie" in cols:  # Alte Spalte existiert noch
                    for row in self.conn.execute("SELECT id, kategorie FROM kunden").fetchall():
                        if row["kategorie"]:
                            self.conn.execute("INSERT OR IGNORE INTO kategorien (name) VALUES (?)", (row["kategorie"],))
                            kid = \
                            self.conn.execute("SELECT id FROM kategorien WHERE name=?", (row["kategorie"],)).fetchone()[
                                "id"]
                            self.conn.execute("UPDATE kunden SET kategorie_id=? WHERE id=?", (kid, row["id"]))

            # Standard-Kategorien falls leer
            if not self.conn.execute("SELECT 1 FROM kategorien LIMIT 1").fetchone():
                for cat in ["Interessiert", "Anfrage", "Auftrag"]:
                    self.conn.execute("INSERT INTO kategorien (name) VALUES (?)", (cat,))

    def _get_or_create(self, table, **kwargs):
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        cur = self.conn.execute(f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
                                list(kwargs.values()))
        if cur.lastrowid and cur.rowcount > 0: return cur.lastrowid
        where = " AND ".join(f"{k}=?" for k in kwargs.keys())
        return self.conn.execute(f"SELECT id FROM {table} WHERE {where}", list(kwargs.values())).fetchone()[0]

    def get_messen(self):
        return self.conn.execute("SELECT * FROM messen ORDER BY name").fetchall()

    def get_kategorien(self):
        return self.conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()

    def import_flipper_data(self, data):
        # 1. Kategorien
        if data.get("config"):
            for line in data["config"].splitlines():
                line = line.strip()
                if not line: continue
                if "|" in line:
                    fid_str, name = line.split("|", 1)
                    fid = int(fid_str)
                    self.conn.execute(
                        "INSERT INTO kategorien (flipper_id, name) VALUES (?, ?) ON CONFLICT(flipper_id) DO UPDATE SET name=excluded.name",
                        (fid, name))
                else:
                    self.conn.execute("INSERT OR IGNORE INTO kategorien (name) VALUES (?)", (line,))

        # 2. Messen
        messe_map = {}  # Flipper-ID -> Lokale DB ID
        for filename, text in data.get("messen", {}).items():
            display_name = filename
            fid = None
            for line in text.splitlines():
                if line.startswith("ID="):
                    fid = int(line[3:])
                elif line.startswith("NAME="):
                    display_name = line[5:].strip()

            if fid is not None:
                self.conn.execute(
                    "INSERT INTO messen (flipper_id, name) VALUES (?, ?) ON CONFLICT(flipper_id) DO UPDATE SET name=excluded.name",
                    (fid, display_name))
                row = self.conn.execute("SELECT id FROM messen WHERE flipper_id=?", (fid,)).fetchone()
                if row: messe_map[fid] = row["id"]
            else:
                mid = self._get_or_create("messen", name=display_name)

        # 3. Tage
        for date_str, text in data.get("days", {}).items():
            lines = text.splitlines()
            messe_val = "Unbekannt"
            events, kunden, merch_actions = [], [], []

            for line in lines:
                if line.startswith("MESSE "):
                    messe_val = line[6:].strip()
                elif line.startswith("BETRETEN ") or line.startswith("VERLASSEN "):
                    parts = line.split(" ", 1)
                    events.append({"typ": parts[0], "zeit": parts[1]})
                elif line.startswith("KUNDE|"):
                    p = line.split("|")
                    if len(p) >= 7:
                        kunden.append({
                            "flipper_id": p[1].lstrip("#"), "zeit": f"{p[2]} {p[3]}:00",
                            "kategorie_raw": p[4], "name": p[5],
                            "firma": p[6] if len(p) >= 10 else "",
                            "email": p[7] if len(p) >= 10 else "",
                            "telefon": p[8] if len(p) >= 10 else "",
                            "notiz": p[9] if len(p) >= 10 else (p[6] if len(p) < 10 else "")
                        })
                elif line.startswith("MERCH "):
                    p = line.split(" ", 2)
                    if len(p) == 3:
                        name, _, val = p[2].rpartition(";")
                        try:
                            merch_actions.append(
                                {"aktion": p[1], "name": name, "wert": int(val), "zeit": date_str + " 12:00:00"})
                        except ValueError:
                            pass

            # Messe ID auflösen
            try:
                fid = int(messe_val)
                messe_id = messe_map.get(fid)
            except ValueError:
                row = self.conn.execute("SELECT id FROM messen WHERE name=?", (messe_val,)).fetchone()
                messe_id = row["id"] if row else None

            if not messe_id:
                messe_id = self._get_or_create("messen", name=messe_val)

            tage_id = self._get_or_create("tage", messe_id=messe_id, datum=date_str)

            for ev in events:
                self.conn.execute("INSERT OR IGNORE INTO anwesenheit (tage_id, typ, zeit) VALUES (?, ?, ?)",
                                  (tage_id, ev["typ"], ev["zeit"]))

            for k in kunden:
                # Kategorie ID auflösen
                try:
                    cat_fid = int(k["kategorie_raw"])
                    cat_row = self.conn.execute("SELECT id FROM kategorien WHERE flipper_id=?", (cat_fid,)).fetchone()
                    cat_id = cat_row["id"] if cat_row else None
                except ValueError:
                    cat_row = self.conn.execute("SELECT id FROM kategorien WHERE name=?",
                                                (k["kategorie_raw"],)).fetchone()
                    cat_id = cat_row["id"] if cat_row else None

                if cat_id is None:
                    self.conn.execute("INSERT OR IGNORE INTO kategorien (name) VALUES (?)", (k["kategorie_raw"],))
                    cat_id = \
                    self.conn.execute("SELECT id FROM kategorien WHERE name=?", (k["kategorie_raw"],)).fetchone()["id"]

                am_stand = 0
                last_ev = None
                for ev in events:
                    if ev["zeit"] <= k["zeit"]: last_ev = ev
                if last_ev and last_ev["typ"] == "BETRETEN": am_stand = 1

                self.conn.execute("""
                    INSERT OR IGNORE INTO kunden (tage_id, flipper_id, zeit, kategorie_id, name, firma, email, telefon, notiz, am_stand)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (tage_id, k["flipper_id"], k["zeit"], cat_id, k["name"], k["firma"], k["email"], k["telefon"],
                      k["notiz"], am_stand))

            for ma in merch_actions:
                art_id = self._get_or_create("merch_artikel", messe_id=messe_id, name=ma["name"])
                self.conn.execute(
                    "INSERT INTO merch_aktionen (artikel_id, tage_id, zeit, aktion, wert) VALUES (?, ?, ?, ?, ?)",
                    (art_id, tage_id, ma["zeit"], ma["aktion"], ma["wert"]))

            self.conn.commit()

    def get_kunden(self, messe_id=None):
        sql = """SELECT k.*, t.datum, m.name as messe_name, c.name as kategorie_name 
                 FROM kunden k 
                 JOIN tage t ON k.tage_id = t.id 
                 JOIN messen m ON t.messe_id = m.id 
                 LEFT JOIN kategorien c ON k.kategorie_id = c.id"""
        params = []
        if messe_id:
            sql += " WHERE m.id = ?"
            params.append(messe_id)
        sql += " ORDER BY k.zeit DESC"
        return self.conn.execute(sql, params).fetchall()

    def get_merch(self, messe_id):
        sql = "SELECT a.id, a.name, (SELECT wert FROM merch_aktionen m2 WHERE m2.artikel_id = a.id ORDER BY zeit DESC, id DESC LIMIT 1) as bestand FROM merch_artikel a WHERE a.messe_id = ?"
        return self.conn.execute(sql, (messe_id,)).fetchall()


class FlipperCLI:
    def __init__(self, port, log_func):
        self.log = log_func
        self.ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=2)
        time.sleep(0.3)
        self._drain()
        self.ser.write(b"\r\n")
        time.sleep(0.2)
        self._drain()

    def _drain(self):
        raw = b""
        end_time = time.time() + 2.0
        while time.time() < end_time:
            if self.ser.in_waiting:
                raw += self.ser.read(self.ser.in_waiting)
                end_time = time.time() + 0.1
            else:
                time.sleep(0.01)
        return raw

    def command(self, cmd):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r\n").encode())
        self.ser.flush()
        raw = self._drain()
        text = raw.decode('utf-8', errors='replace')
        text = re.sub(r'\x1b\[[0-9;]*m', '', text).replace('\r\n', '\n').replace('\r', '\n')
        lines = text.split('\n')
        if lines and cmd in lines[0]: lines = lines[1:]
        if lines and lines[-1].strip() in (">:", ">"): lines = lines[:-1]
        result = "\n".join(lines).strip()
        if cmd.startswith("storage read"):
            result = re.sub(r'^Size:\s*\d+\s*\n', '', result, flags=re.IGNORECASE).strip()
        return result

    def close(self):
        self.ser.close()


class FetchWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port

    def run(self):
        try:
            if not self.port:
                ports = [p.device for p in list_ports.comports() if
                         "flipper" in (p.description or "").lower() or getattr(p, "vid", 0) == 0x0483]
                if not ports: raise RuntimeError("Kein Flipper gefunden.")
                self.port = ports[0]

            self.log.emit(f"Verbinde mit {self.port} …")
            cli = FlipperCLI(self.port, self.log.emit)
            try:
                data = {"days": {}, "messen": {}, "config": ""}
                self.log.emit("Lese Kategorien …")
                data["config"] = cli.command(f"storage read {CONFIG_PATH}")

                self.log.emit("Lese Messen …")
                out = cli.command(f"storage list {MESSEN_DIR}")
                m_files = [l.split("] ")[1].rsplit(" ", 1)[0] for l in out.split('\n') if l.strip().startswith("[F]")]
                for f in m_files:
                    data["messen"][f.replace(".txt", "")] = cli.command(f"storage read {MESSEN_DIR}/{f}")

                self.log.emit("Lese Tage …")
                out = cli.command(f"storage list {DAYS_DIR}")
                d_files = [l.split("] ")[1].rsplit(" ", 1)[0] for l in out.split('\n') if l.strip().startswith("[F]")]
                for f in d_files:
                    data["days"][f.replace(".txt", "")] = cli.command(f"storage read {DAYS_DIR}/{f}")

                self.finished.emit(data)
            finally:
                cli.close()
        except Exception as e:
            self.error.emit(str(e))


class MesseDialog(QDialog):
    def __init__(self, name="", ort=""):
        super().__init__()
        self.setWindowTitle("Messe")
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.ort = QLineEdit(ort)
        form.addRow("Name der Messe:", self.name)
        form.addRow("Ort (optional):", self.ort)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept);
        btns.rejected.connect(self.reject)
        form.addRow(btns)


class CustomerDialog(QDialog):
    def __init__(self, db, customer=None):
        super().__init__()
        self.setWindowTitle("Kunde bearbeiten" if customer else "Neuer Kunde")
        form = QFormLayout(self)
        self.name = QLineEdit(customer["name"] if customer else "")
        self.firma = QLineEdit(customer["firma"] if customer else "")
        self.email = QLineEdit(customer["email"] if customer else "")
        self.telefon = QLineEdit(customer["telefon"] if customer else "")
        self.notiz = QTextEdit(customer["notiz"] if customer else "")
        self.notiz.setMaximumHeight(80)

        self.kategorie = QComboBox()
        self.cat_data = db.get_kategorien()
        for cat in self.cat_data: self.kategorie.addItem(cat["name"], cat["id"])
        if customer and customer["kategorie_id"]:
            idx = self.kategorie.findData(customer["kategorie_id"])
            if idx >= 0: self.kategorie.setCurrentIndex(idx)

        self.am_stand = QCheckBox("Am Stand getroffen")
        if customer: self.am_stand.setChecked(bool(customer["am_stand"]))

        form.addRow("Name:", self.name);
        form.addRow("Firma:", self.firma)
        form.addRow("E-Mail:", self.email);
        form.addRow("Telefon:", self.telefon)
        form.addRow("Kategorie:", self.kategorie);
        form.addRow("Notiz:", self.notiz)
        form.addRow(self.am_stand)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept);
        btns.rejected.connect(self.reject)
        form.addRow(btns)


class DashboardTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.port_combo = QComboBox()
        self.btn_sync = QPushButton("Verbinden & Synchronisieren")
        self.btn_sync.clicked.connect(self.sync)
        h.addWidget(QLabel("Port:"));
        h.addWidget(self.port_combo, 1);
        h.addWidget(self.btn_sync)
        v.addLayout(h)

        h_stats = QHBoxLayout()
        self.stat_cards = {}
        for key, label in [("kunden", "Kunden (Aktive Messe)"), ("tage", "Messetage"), ("stand", "Am Stand getroffen")]:
            card = QGroupBox(label);
            l = QVBoxLayout(card)
            lbl = QLabel("0", objectName="Stat");
            l.addWidget(lbl)
            self.stat_cards[key] = lbl;
            h_stats.addWidget(card)
        v.addLayout(h_stats)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background: #050505; font-family: monospace;")
        v.addWidget(QLabel("Synchronisations-Log:"))
        v.addWidget(self.log_view, 1)

    def refresh(self):
        self.port_combo.clear()
        for p in list_ports.comports(): self.port_combo.addItem(f"{p.device} ({p.description})", p.device)

        fid = self.main.current_fair_id
        kunden = self.main.db.get_kunden(fid) if fid else []
        tage = len(self.main.db.conn.execute("SELECT id FROM tage WHERE messe_id=?", (fid,)).fetchall()) if fid else 0
        am_stand = sum(1 for k in kunden if k["am_stand"])

        self.stat_cards["kunden"].setText(str(len(kunden)))
        self.stat_cards["tage"].setText(str(tage))
        self.stat_cards["stand"].setText(str(am_stand))

    def sync(self):
        port = self.port_combo.currentData()
        self.btn_sync.setEnabled(False);
        self.log_view.clear()
        self.worker = FetchWorker(port)
        self.worker.log.connect(self.log_view.append)
        self.worker.error.connect(lambda e: QMessageBox.critical(self, "Fehler", e))
        self.worker.finished.connect(self._on_sync_done)
        self.worker.finished.connect(lambda: self.btn_sync.setEnabled(True))
        self.worker.error.connect(lambda: self.btn_sync.setEnabled(True))
        self.worker.start()

    def _on_sync_done(self, data):
        self.main.db.import_flipper_data(data)
        self.log_view.append("✅ Synchronisation abgeschlossen.")
        self.main.refresh_all()


class SettingsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)

        # Messen
        m_box = QGroupBox("Messen")
        ml = QVBoxLayout(m_box)
        mh = QHBoxLayout()
        btn_m_add = QPushButton("+ Messe");
        btn_m_add.clicked.connect(self.add_messe)
        btn_m_edit = QPushButton("Bearbeiten");
        btn_m_edit.clicked.connect(self.edit_messe)
        btn_m_del = QPushButton("Löschen");
        btn_m_del.setObjectName("Ghost");
        btn_m_del.clicked.connect(self.delete_messe)
        mh.addWidget(btn_m_add);
        mh.addWidget(btn_m_edit);
        mh.addWidget(btn_m_del);
        mh.addStretch(1)
        ml.addLayout(mh)
        self.m_table = QTableWidget(0, 3)
        self.m_table.setHorizontalHeaderLabels(["Name", "Ort", "Flipper-ID"])
        self.m_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.m_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.m_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        ml.addWidget(self.m_table)
        v.addWidget(m_box)

        # Kategorien
        k_box = QGroupBox("Kategorien")
        kl = QVBoxLayout(k_box)
        kh = QHBoxLayout()
        btn_k_add = QPushButton("+ Kategorie");
        btn_k_add.clicked.connect(self.add_kategorie)
        btn_k_del = QPushButton("Löschen");
        btn_k_del.setObjectName("Ghost");
        btn_k_del.clicked.connect(self.delete_kategorie)
        kh.addWidget(btn_k_add);
        kh.addWidget(btn_k_del);
        kh.addStretch(1)
        kl.addLayout(kh)
        self.k_table = QTableWidget(0, 2)
        self.k_table.setHorizontalHeaderLabels(["Name", "Flipper-ID"])
        self.k_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.k_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        kl.addWidget(self.k_table)
        v.addWidget(k_box)

        # Export
        e_box = QGroupBox("Export")
        el = QVBoxLayout(e_box)
        btn_csv = QPushButton("Kunden als CSV exportieren");
        btn_csv.clicked.connect(self.export_csv)
        btn_pdf = QPushButton("PDF-Bericht erstellen");
        btn_pdf.clicked.connect(self.export_pdf)
        el.addWidget(btn_csv);
        el.addWidget(btn_pdf)
        v.addWidget(e_box)

    def refresh(self):
        messen = self.main.db.get_messen()
        self.m_table.setRowCount(len(messen))
        for r, m in enumerate(messen):
            self.m_table.setItem(r, 0, QTableWidgetItem(m["name"]))
            self.m_table.setItem(r, 1, QTableWidgetItem(m["ort"] or ""))
            self.m_table.setItem(r, 2, QTableWidgetItem(str(m["flipper_id"]) if m["flipper_id"] else "-"))
            self.m_table.item(r, 0).setData(Qt.UserRole, m["id"])

        kats = self.main.db.get_kategorien()
        self.k_table.setRowCount(len(kats))
        for r, k in enumerate(kats):
            self.k_table.setItem(r, 0, QTableWidgetItem(k["name"]))
            self.k_table.setItem(r, 1, QTableWidgetItem(str(k["flipper_id"]) if k["flipper_id"] else "-"))
            self.k_table.item(r, 0).setData(Qt.UserRole, k["id"])

    def add_messe(self):
        dlg = MesseDialog()
        if dlg.exec_():
            self.main.db.conn.execute("INSERT INTO messen (name, ort) VALUES (?, ?)", (dlg.name.text(), dlg.ort.text()))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def edit_messe(self):
        row = self.m_table.currentRow()
        if row < 0: return
        mid = self.m_table.item(row, 0).data(Qt.UserRole)
        dlg = MesseDialog(self.m_table.item(row, 0).text(), self.m_table.item(row, 1).text())
        if dlg.exec_():
            self.main.db.conn.execute("UPDATE messen SET name=?, ort=? WHERE id=?",
                                      (dlg.name.text(), dlg.ort.text(), mid))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete_messe(self):
        row = self.m_table.currentRow()
        if row < 0: return
        if QMessageBox.question(self, "Löschen", "Messe und ALLE zugehörigen Daten löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute("DELETE FROM messen WHERE id=?", (self.m_table.item(row, 0).data(Qt.UserRole),))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def add_kategorie(self):
        name, ok = QInputDialog.getText(self, "Kategorie", "Name:")
        if ok and name:
            self.main.db.conn.execute("INSERT OR IGNORE INTO kategorien (name) VALUES (?)", (name,))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete_kategorie(self):
        row = self.k_table.currentRow()
        if row >= 0:
            if QMessageBox.question(self, "Löschen", "Kategorie löschen?") == QMessageBox.Yes:
                self.main.db.conn.execute("DELETE FROM kategorien WHERE id=?",
                                          (self.k_table.item(row, 0).data(Qt.UserRole),))
                self.main.db.conn.commit()
                self.main.refresh_all()

    def export_csv(self):
        fid = self.main.current_fair_id
        if not fid: return
        path, _ = QFileDialog.getSaveFileName(self, "CSV speichern", "kunden.csv", "CSV (*.csv)")
        if not path: return
        kunden = self.main.db.get_kunden(fid)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(
                ["ID", "Flipper-ID", "Datum", "Name", "Firma", "E-Mail", "Telefon", "Kategorie", "Am Stand", "Notiz"])
            for k in kunden:
                writer.writerow([k["id"], k["flipper_id"], k["zeit"], k["name"], k["firma"], k["email"], k["telefon"],
                                 k["kategorie_name"], "Ja" if k["am_stand"] else "Nein", k["notiz"]])
        QMessageBox.information(self, "Export", "CSV gespeichert.")

    def export_pdf(self):
        fid = self.main.current_fair_id
        if not fid: return
        path, _ = QFileDialog.getSaveFileName(self, "PDF speichern", "bericht.pdf", "PDF (*.pdf)")
        if not path: return
        if not path.endswith(".pdf"): path += ".pdf"

        doc = SimpleDocTemplate(path, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = [Paragraph("Messe Tracker Bericht", styles['Title']), Spacer(1, 12)]
        kunden = self.main.db.get_kunden(fid)

        elements.append(Paragraph(f"Gesamtzahl Kunden: {len(kunden)}", styles['Normal']))
        elements.append(Spacer(1, 12))

        data = [["ID", "Name", "Firma", "Kategorie", "Stand"]]
        for k in kunden:
            data.append([k["id"], k["name"], k["firma"], k["kategorie_name"] or "-", "Ja" if k["am_stand"] else "Nein"])

        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(FLIPPER["accent"])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(t)
        doc.build(elements)
        QMessageBox.information(self, "Export", "PDF gespeichert.")


class CustomersTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        btn_add = QPushButton("+ Kunde");
        btn_add.clicked.connect(self.add)
        btn_edit = QPushButton("Bearbeiten");
        btn_edit.clicked.connect(self.edit)
        btn_del = QPushButton("Löschen");
        btn_del.setObjectName("Ghost");
        btn_del.clicked.connect(self.delete)
        h.addWidget(btn_add);
        h.addWidget(btn_edit);
        h.addWidget(btn_del);
        h.addStretch(1)
        v.addLayout(h)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Flipper-ID", "Datum", "Name", "Firma", "Kategorie", "Stand", "Notiz"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        v.addWidget(self.table)

    def refresh(self):
        fid = self.main.current_fair_id
        if not fid: self.table.setRowCount(0); return

        kunden = self.main.db.get_kunden(fid)
        self.table.setRowCount(len(kunden))
        for r, k in enumerate(kunden):
            self.table.setItem(r, 0, QTableWidgetItem(str(k["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(k["flipper_id"] or "-"))
            self.table.setItem(r, 2, QTableWidgetItem(k["zeit"][:16]))
            self.table.setItem(r, 3, QTableWidgetItem(k["name"] or ""))
            self.table.setItem(r, 4, QTableWidgetItem(k["firma"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(k["kategorie_name"] or ""))
            self.table.setItem(r, 6, QTableWidgetItem("Ja" if k["am_stand"] else "Nein"))
            self.table.setItem(r, 7, QTableWidgetItem(k["notiz"] or ""))
            self.table.item(r, 0).setData(Qt.UserRole, k["id"])

    def _get_selected(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.UserRole) if row >= 0 else None

    def add(self):
        fid = self.main.current_fair_id
        if not fid: return QMessageBox.warning(self, "Fehler", "Keine Messe ausgewählt.")
        dlg = CustomerDialog(self.main.db)
        if dlg.exec_():
            datum = datetime.now().strftime("%Y-%m-%d")
            tage_id = self.main.db._get_or_create("tage", messe_id=fid, datum=datum)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.main.db.conn.execute(
                "INSERT INTO kunden (tage_id, zeit, name, firma, email, telefon, kategorie_id, notiz, am_stand) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tage_id, now, dlg.name.text(), dlg.firma.text(), dlg.email.text(), dlg.telefon.text(),
                 dlg.kategorie.currentData(), dlg.notiz.toPlainText(), 1 if dlg.am_stand.isChecked() else 0))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def edit(self):
        cid = self._get_selected()
        if not cid: return
        k = self.main.db.conn.execute("SELECT * FROM kunden WHERE id=?", (cid,)).fetchone()
        dlg = CustomerDialog(self.main.db, k)
        if dlg.exec_():
            self.main.db.conn.execute(
                "UPDATE kunden SET name=?, firma=?, email=?, telefon=?, kategorie_id=?, notiz=?, am_stand=? WHERE id=?",
                (dlg.name.text(), dlg.firma.text(), dlg.email.text(), dlg.telefon.text(), dlg.kategorie.currentData(),
                 dlg.notiz.toPlainText(), 1 if dlg.am_stand.isChecked() else 0, cid))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete(self):
        cid = self._get_selected()
        if cid and QMessageBox.question(self, "Löschen", "Kunde löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute("DELETE FROM kunden WHERE id=?", (cid,))
            self.main.db.conn.commit()
            self.main.refresh_all()


class MerchTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        btn_add = QPushButton("+ Artikel");
        btn_add.clicked.connect(self.add_article)
        btn_del = QPushButton("Löschen");
        btn_del.setObjectName("Ghost");
        btn_del.clicked.connect(self.delete_article)
        btn_count = QPushButton("Bestand aufnehmen");
        btn_count.clicked.connect(self.count_stock)
        h.addWidget(btn_add);
        h.addWidget(btn_del);
        h.addWidget(btn_count);
        h.addStretch(1)
        v.addLayout(h)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Artikel", "Bestand"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        v.addWidget(self.table)

    def refresh(self):
        fid = self.main.current_fair_id
        if not fid: self.table.setRowCount(0); return
        items = self.main.db.get_merch(fid)
        self.table.setRowCount(len(items))
        for r, item in enumerate(items):
            self.table.setItem(r, 0, QTableWidgetItem(str(item["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(item["name"]))
            self.table.setItem(r, 2, QTableWidgetItem(str(item["bestand"] or 0)))
            self.table.item(r, 0).setData(Qt.UserRole, item["id"])

    def add_article(self):
        fid = self.main.current_fair_id
        if not fid: return
        name, ok = QInputDialog.getText(self, "Neuer Artikel", "Name:")
        if ok and name:
            self.main.db.conn.execute("INSERT OR IGNORE INTO merch_artikel (messe_id, name) VALUES (?, ?)", (fid, name))
            self.main.db.conn.commit()
            self.refresh()

    def delete_article(self):
        row = self.table.currentRow()
        if row < 0: return
        aid = self.table.item(row, 0).data(Qt.UserRole)
        if QMessageBox.question(self, "Löschen", "Artikel löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute("DELETE FROM merch_artikel WHERE id=?", (aid,))
            self.main.db.conn.commit()
            self.refresh()

    def count_stock(self):
        row = self.table.currentRow()
        if row < 0: return
        aid = self.table.item(row, 0).data(Qt.UserRole)
        name = self.table.item(row, 1).text()
        val, ok = QInputDialog.getInt(self, f"Bestand: {name}", "Neuer Bestand:", 0, 0, 100000)
        if ok:
            fid = self.main.current_fair_id
            datum = datetime.now().strftime("%Y-%m-%d")
            tage_id = self.main.db._get_or_create("tage", messe_id=fid, datum=datum)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.main.db.conn.execute(
                "INSERT INTO merch_aktionen (artikel_id, tage_id, zeit, aktion, wert) VALUES (?, ?, ?, 'BESTAND', ?)",
                (aid, tage_id, now, val))
            self.main.db.conn.commit()
            self.refresh()


class AnalyticsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        self.fig = Figure(figsize=(8, 5), facecolor=FLIPPER["bg_panel"])
        self.canvas = FigureCanvas(self.fig)
        v.addWidget(self.canvas, 1)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #fff; padding: 10px; font-weight: bold;")
        v.addWidget(self.summary)

    def refresh(self):
        self.fig.clear()
        ax1 = self.fig.add_subplot(1, 2, 1)
        ax2 = self.fig.add_subplot(1, 2, 2)

        for ax in (ax1, ax2):
            ax.set_facecolor(FLIPPER["bg_panel"])
            ax.tick_params(colors=FLIPPER["fg_text"])
            for spine in ax.spines.values(): spine.set_color(FLIPPER["border"])
            ax.title.set_color(FLIPPER["accent"])

        fid = self.main.current_fair_id
        kunden = self.main.db.get_kunden(fid) if fid else []
        if not kunden:
            ax1.text(0.5, 0.5, "Keine Daten", ha='center', va='center', color=FLIPPER["fg_text"],
                     transform=ax1.transAxes)
            self.canvas.draw();
            return

        cats = {}
        for k in kunden:
            c = k["kategorie_name"] or "Leer"
            cats.setdefault(c, {"Stand": 0, "Nicht": 0})
            if k["am_stand"]:
                cats[c]["Stand"] += 1
            else:
                cats[c]["Nicht"] += 1

        names = list(cats.keys())
        stand = [cats[n]["Stand"] for n in names]
        nicht = [cats[n]["Nicht"] for n in names]
        ax1.bar(names, stand, label="Am Stand", color=FLIPPER["accent"])
        ax1.bar(names, nicht, bottom=stand, label="Nicht am Stand", color="#555")
        ax1.set_title("Kategorien: Stand vs. Nicht-Stand")
        ax1.legend()
        ax1.tick_params(axis='x', rotation=30)

        hours = [int(k["zeit"][11:13]) for k in kunden]
        ax2.hist(hours, bins=range(8, 20), color=FLIPPER["accent"], align='left')
        ax2.set_title("Kunden pro Uhrzeit")

        self.fig.tight_layout()
        self.canvas.draw()

        total = len(kunden)
        am_stand = sum(1 for k in kunden if k["am_stand"])
        quote = (am_stand / total * 100) if total else 0
        self.summary.setText(f"Von {total} Kunden wurden {am_stand} am Stand getroffen ({quote:.1f}%).")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messe Tracker – Master")
        self.resize(1200, 800)
        self.db = Database(DB_PATH)
        self.current_fair_id = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        top.addWidget(QLabel("Aktive Messe:", objectName="H2"))
        self.fair_combo = QComboBox()
        self.fair_combo.currentIndexChanged.connect(self._on_fair_changed)
        top.addWidget(self.fair_combo, 1)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tab_dash = DashboardTab(self)
        self.tab_settings = SettingsTab(self)
        self.tab_cust = CustomersTab(self)
        self.tab_merch = MerchTab(self)
        self.tab_analytics = AnalyticsTab(self)

        self.tabs.addTab(self.tab_dash, "Start & Sync")
        self.tabs.addTab(self.tab_settings, "Einstellungen")
        self.tabs.addTab(self.tab_cust, "Kunden")
        self.tabs.addTab(self.tab_merch, "Merch")
        self.tabs.addTab(self.tab_analytics, "Auswertung")

        layout.addWidget(self.tabs)
        self.setStatusBar(QStatusBar())
        self.refresh_all()

    def _on_fair_changed(self):
        self.current_fair_id = self.fair_combo.currentData()
        self.tab_dash.refresh()
        self.tab_cust.refresh()
        self.tab_merch.refresh()
        self.tab_analytics.refresh()

    def refresh_all(self):
        curr = self.current_fair_id
        self.fair_combo.blockSignals(True)
        self.fair_combo.clear()
        messen = self.db.get_messen()
        for m in messen:
            self.fair_combo.addItem(m["name"], m["id"])

        if curr:
            idx = self.fair_combo.findData(curr)
            if idx >= 0:
                self.fair_combo.setCurrentIndex(idx)
            else:
                self.current_fair_id = self.fair_combo.currentData()
        else:
            self.current_fair_id = self.fair_combo.currentData()
        self.fair_combo.blockSignals(False)

        self.tab_settings.refresh()
        self._on_fair_changed()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())