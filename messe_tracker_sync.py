#!/usr/bin/env python3
"""
messe_tracker_sync.py
=====================
Master-Anwendung für den Messe Tracker.

Enthält:
- Robuste Flipper-CLI (Prompt-Erkennung, Fehler, Timeouts, Größenprüfung)
- Sicherer write_file() mit Backup / Rollback / semantischer Verifikation
- Idempotenter, transaktionaler Import mit Event-Keys
- Sortierte Anwesenheitsauswertung
- Keine künstliche Messe "Unbekannt"
- UUIDs, Herkunft, Status-Historie, Soft-Delete
- Erweiterte Analytics mit Filtern
- Thread-sicheres Beenden (kein 0xC0000409)
"""
from __future__ import annotations

import csv
import hashlib
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
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
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QMessageBox, QFileDialog, QHeaderView,
    QAbstractItemView, QGroupBox, QLineEdit, QStatusBar,
    QTextEdit, QDialog, QFormLayout, QDialogButtonBox,
    QCheckBox, QInputDialog, QScrollArea,
)

APP_DIR = "/ext/apps_data/messe_tracker"
DAYS_DIR = f"{APP_DIR}/days"
MESSEN_DIR = f"{APP_DIR}/messen"
CONFIG_PATH = f"{APP_DIR}/config.txt"
DB_PATH = Path(__file__).parent / "messe_tracker.db"
SCHEMA_VERSION = 2

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
QLabel#Stat {{ font-size: 26pt; color: {FLIPPER['accent']}; font-weight: 800; }}
QLabel#StatLabel {{ color: {FLIPPER['fg_muted']}; font-size: 9pt; text-transform: uppercase; }}
QGroupBox {{ background: {FLIPPER['bg_panel']}; border: 1px solid {FLIPPER['border']}; border-radius: 10px; margin-top: 18px; padding: 14px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 8px; color: {FLIPPER['accent']}; }}
QPushButton {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; border: 0; border-radius: 8px; padding: 10px 20px; font-weight: 700; }}
QPushButton:hover {{ background: {FLIPPER['accent_hover']}; }}
QPushButton:disabled {{ background: {FLIPPER['border']}; color: {FLIPPER['fg_muted']}; }}
QPushButton#Ghost {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; border: 1px solid {FLIPPER['border']}; }}
QLineEdit, QComboBox, QTextEdit, QDateEdit, QSpinBox {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; border: 1px solid {FLIPPER['border']}; border-radius: 6px; padding: 6px; }}
QTableWidget {{ background: {FLIPPER['bg_panel']}; alternate-background-color: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; gridline-color: {FLIPPER['border']}; border: 1px solid {FLIPPER['border']}; }}
QTableWidget::item:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
QHeaderView::section {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['accent']}; padding: 8px; border: 0; border-bottom: 1px solid {FLIPPER['border']}; font-weight: 700; }}
QTabWidget::pane {{ border: 1px solid {FLIPPER['border']}; border-radius: 8px; background: {FLIPPER['bg_panel']}; top: -1px; }}
QTabBar::tab {{ background: {FLIPPER['bg_input']}; color: {FLIPPER['fg_text']}; padding: 10px 22px; border: 1px solid {FLIPPER['border']}; border-bottom: 0; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {FLIPPER['accent']}; color: {FLIPPER['accent_fg']}; }}
QScrollArea {{ border: 0; }}
"""


def sanitize_name(name: str) -> str:
    res = "".join(c if c.isalnum() or c in "-_" else ("_" if c == " " else "") for c in name)
    return res or "Messe"


def valid_ts(ts: str) -> bool:
    if not ts:
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            datetime.strptime(ts.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


# =========================================================================
# Flipper CLI
# =========================================================================
class FlipperCLIError(Exception):
    pass


class FlipperCLI:
    """Robuster Flipper-CLI-Client mit Prompt- und Größenprüfung."""

    PROMPT_MARKERS = (b">: ", b"> ")
    ERROR_MARKERS = (
        "storage error", "cannot ", "not found", "not exist",
        "no such file", "failed", "invalid", "error:", "error "
    )

    def __init__(self, port: str, log_func, baud: int = 115200):
        self.log = log_func
        self.ser = serial.Serial(port, baud, timeout=0.1, write_timeout=2)
        time.sleep(0.3)
        self._drain()
        try:
            self.command("", timeout=2.0, allow_empty=True)
        except FlipperCLIError:
            pass

    # ------------------------------------------------------------------
    @staticmethod
    def _canon(data: bytes) -> bytes:
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    def _drain(self, quiet: float = 0.05, max_wait: float = 1.5) -> bytes:
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        raw = b""
        last_data = time.time()
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if self.ser.in_waiting:
                raw += self.ser.read(self.ser.in_waiting)
                last_data = time.time()
            else:
                if time.time() - last_data >= quiet:
                    break
                time.sleep(0.01)
        return raw

    def _read_until_prompt(self, timeout: float = 5.0) -> bytes:
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self.ser.read(1)
            if not chunk:
                continue
            buf += chunk
            for prompt in self.PROMPT_MARKERS:
                if len(buf) >= len(prompt) and bytes(buf[-len(prompt):]) == prompt:
                    settle_end = time.time() + 0.15
                    while time.time() < settle_end:
                        if self.ser.in_waiting:
                            buf += self.ser.read(self.ser.in_waiting)
                            settle_end = time.time() + 0.05
                        else:
                            time.sleep(0.01)
                    return bytes(buf)
        raise FlipperCLIError(
            f"Timeout ({timeout}s) – letzte 200 Bytes: {bytes(buf)[-200:]!r}"
        )

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

    @staticmethod
    def _contains_error(text: str) -> bool:
        low = text.lower()
        return any(m in low for m in FlipperCLI.ERROR_MARKERS)

    # ------------------------------------------------------------------
    def command(self, cmd: str, timeout: float = 5.0, allow_empty: bool = False) -> str:
        self._drain()
        if cmd:
            try:
                self.ser.write((cmd + "\r\n").encode("utf-8"))
                self.ser.flush()
            except serial.SerialException as exc:
                raise FlipperCLIError(f"Verbindung verloren: {exc}") from exc
        raw = self._read_until_prompt(timeout)
        text = self._strip_ansi(raw.decode("utf-8", errors="replace"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Echo-Zeile entfernen
        if cmd:
            first_nl = text.find("\n")
            if first_nl >= 0 and cmd.split()[0] in text[:first_nl]:
                text = text[first_nl + 1:]

        # Prompt entfernen - zeilenbasiert (robust gegen Leerzeichen)
        lines = text.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip() in (">:", ">"):
            lines.pop()
        text = "\n".join(lines)

        # Führende Whitespace entfernen, trailing NICHT (Datei-Inhalt bewahren)
        text = text.lstrip("\r\n")
        return text

    # ------------------------------------------------------------------
    def list_dir(self, path: str, timeout: float = 5.0) -> list[tuple[str, bool]]:
        out = self.command(f"storage list {path}", timeout=timeout)
        if self._contains_error(out) and "[" not in out:
            raise FlipperCLIError(f"List fehlgeschlagen für {path}: {out[:120]!r}")
        entries = []
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            is_dir = False
            if line.startswith("[D]"):
                is_dir, name = True, line[3:].strip()
            elif line.startswith("[F]"):
                name = line[3:].strip()
                if " " in name:
                    name = name.rsplit(" ", 1)[0]
            else:
                continue
            if name:
                entries.append((name, is_dir))
        return entries

    def read_file(self, path: str, timeout: float = 10.0) -> str | None:
        try:
            raw = self.command(f"storage read {path}", timeout=timeout,
                               allow_empty=True)
        except FlipperCLIError:
            raise
        if self._contains_error(raw) and not raw.startswith("Size:"):
            return None

        expected_size: int | None = None
        m = re.match(r"^Size:\s*(\d+)\s*\n", raw + "\n", re.IGNORECASE)
        if m:
            expected_size = int(m.group(1))
            raw = re.sub(r"^Size:\s*\d+\s*\n", "", raw, count=1, flags=re.IGNORECASE)

        if expected_size is None:
            self.log(f"WARNUNG: {path}: Keine Size-Zeile – kann Größe nicht prüfen")
            return raw

        data = raw.encode("utf-8")
        self.log(
            f"INFO: {path}: Size-Line = {expected_size} B, gelesen = {len(data)} B"
        )

        if len(data) < expected_size:
            settle = self._drain(quiet=0.1, max_wait=1.0)
            if settle:
                raw += self._strip_ansi(settle.decode("utf-8", errors="replace"))
                data = raw.encode("utf-8")
            if len(data) < expected_size:
                raise FlipperCLIError(
                    f"Unvollständig gelesen: Size-Line meldet {expected_size} B, "
                    f"nur {len(data)} B empfangen für {path}"
                )

        if len(data) > expected_size:
            extra = len(data) - expected_size
            self.log(
                f"INFO: {path}: {extra} Byte Prompt-Artefakt am Ende "
                f"werden anhand Size-Line abgeschnitten"
            )
            # Auf die vom Flipper gemeldete Dateigröße kürzen
            data = data[:expected_size]
            raw = data.decode("utf-8", errors="strict")

        return raw

    def _file_exists(self, path: str) -> bool:
        out = self.command(f"storage stat {path}")
        return not self._contains_error(out) and out.strip() != ""

    # ------------------------------------------------------------------
    def write_file(self, path: str, content: str) -> None:
        data = content.encode("utf-8")
        tmp = f"{path}.tmp"
        bak = f"{path}.bak"

        for p in (tmp, bak):
            try:
                self.command(f"storage remove {p}", allow_empty=True)
            except FlipperCLIError:
                pass

        # --- 1. Schreiben ---
        self._drain()
        try:
            self.ser.write(f"storage write {tmp}\r\n".encode())
            self.ser.flush()
        except serial.SerialException as exc:
            raise FlipperCLIError(
                f"Verbindung beim Start von storage write verloren: {exc}"
            ) from exc
        time.sleep(0.25)
        self._drain()

        chunk = 128
        for i in range(0, len(data), chunk):
            try:
                self.ser.write(data[i:i + chunk])
                self.ser.flush()
            except serial.SerialException as exc:
                raise FlipperCLIError(
                    f"Verbindung beim Senden an {tmp} verloren "
                    f"(Offset {i}): {exc}"
                ) from exc
            time.sleep(0.02)
            self._drain()

        try:
            self.ser.write(b"\x03")
            self.ser.flush()
        except serial.SerialException as exc:
            raise FlipperCLIError(
                f"Verbindung beim Schließen von {tmp} verloren: {exc}"
            ) from exc
        time.sleep(0.35)
        self._drain()

        # --- 2. Verifikation temp (Size-basiert) ---
        readback = self.read_file(tmp)
        if readback is None:
            raise FlipperCLIError(f"Verifikation: {tmp} nicht lesbar")
        self._verify_files_match(tmp, data, readback.encode("utf-8"))

        # --- 3. Backup der Zieldatei ---
        existed = self._file_exists(path)
        if existed:
            try:
                self.command(f"storage rename {path} {bak}", allow_empty=True)
            except FlipperCLIError as exc:
                raise FlipperCLIError(
                    f"Backup {bak} fehlgeschlagen: {exc}"
                ) from exc

        # --- 4. Rename temp -> final ---
        try:
            self.command(f"storage rename {tmp} {path}", allow_empty=True)
        except FlipperCLIError as exc:
            if existed:
                try:
                    self.command(f"storage rename {bak} {path}",
                                 allow_empty=True)
                except FlipperCLIError:
                    self.log(f"FEHLER: Rollback {bak}->{path} fehlgeschlagen")
            raise FlipperCLIError(
                f"Rename {tmp}->{path} fehlgeschlagen: {exc}"
            ) from exc

        # --- 5. Endverifikation (Size-basiert) ---
        final = self.read_file(path)
        if final is None:
            if existed:
                try:
                    self.command(f"storage remove {path}", allow_empty=True)
                    self.command(f"storage rename {bak} {path}",
                                 allow_empty=True)
                except FlipperCLIError:
                    pass
            raise FlipperCLIError(
                f"Endverifikation fehlgeschlagen: {path} nicht lesbar"
            )

        try:
            self._verify_files_match(path, data, final.encode("utf-8"))
        except FlipperCLIError:
            if existed:
                try:
                    self.command(f"storage remove {path}", allow_empty=True)
                    self.command(f"storage rename {bak} {path}",
                                 allow_empty=True)
                except FlipperCLIError:
                    self.log(
                        f"FEHLER: Rollback {bak}->{path} fehlgeschlagen"
                    )
            raise

        # --- 6. Backup entfernen ---
        if existed:
            try:
                self.command(f"storage remove {bak}", allow_empty=True)
            except FlipperCLIError:
                self.log(f"WARNUNG: {bak} konnte nicht entfernt werden")

        self.log(
            f"Datei verifiziert geschrieben: {path} ({len(data)} B)"
        )

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def _verify_files_match(self, path: str, expected: bytes, actual: bytes) -> None:
        """Vergleicht geschriebene Bytes mit erwarteten.

        - Exakte Übereinstimmung: OK
        - Nur Zeilenenden (\n vs \r\n): WARNUNG, OK
        - Nur Whitespace-Unterschied: WARNUNG, OK
        - Sonstiger Unterschied: FlipperCLIError mit Hexdump
        """
        if expected == actual:
            return

        canon_e = self._canon(expected)
        canon_a = self._canon(actual)
        if canon_e == canon_a:
            self.log(
                f"WARNUNG: {path}: Zeilenenden weichen ab "
                f"({len(expected)}B vs {len(actual)}B), Inhalt identisch"
            )
            return

        if canon_e.strip() == canon_a.strip():
            self.log(
                f"WARNUNG: {path}: Nur Whitespace-Unterschiede "
                f"({len(expected)}B vs {len(actual)}B), Inhalt identisch"
            )
            return

        # Echter Mismatch – Hexdump der ersten 80 Bytes zur Diagnose
        dump_e = canon_e.strip()[:80].hex()
        dump_a = canon_a.strip()[:80].hex()
        raise FlipperCLIError(
            f"Verifikation fehlgeschlagen für {path}:\n"
            f"  erwartet: {len(expected)} B\n"
            f"  erhalten: {len(actual)} B\n"
            f"  expected hex: {dump_e}\n"
            f"  actual   hex: {dump_a}"
        )


# =========================================================================
# Database
# =========================================================================
class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._migrate()

    # ------------------------------------------------------------------
    def _backup(self) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        bak = self.path.with_name(
            f"{self.path.stem}.backup_{int(time.time())}{self.path.suffix}"
        )
        shutil.copy2(self.path, bak)
        return bak

    # ------------------------------------------------------------------
    def _migrate(self) -> None:
        cur = self.conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]
        if version >= SCHEMA_VERSION:
            return

        self._backup()

        with self._lock:
            if version < 1:
                self._schema_v1()
                self.conn.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                self._schema_v2()
                self.conn.execute("PRAGMA user_version = 2")
            self.conn.commit()

    # ------------------------------------------------------------------
    def _schema_v1(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messen (
                id INTEGER PRIMARY KEY, flipper_id INTEGER UNIQUE,
                name TEXT, ort TEXT, geloescht INTEGER DEFAULT 0,
                uuid TEXT);
            CREATE TABLE IF NOT EXISTS kategorien (
                id INTEGER PRIMARY KEY, flipper_id INTEGER UNIQUE,
                name TEXT UNIQUE, geloescht INTEGER DEFAULT 0,
                uuid TEXT);
            CREATE TABLE IF NOT EXISTS tage (
                id INTEGER PRIMARY KEY, messe_id INTEGER, datum TEXT,
                UNIQUE(messe_id, datum),
                FOREIGN KEY(messe_id) REFERENCES messen(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS kunden (
                id INTEGER PRIMARY KEY, tage_id INTEGER,
                flipper_id TEXT, zeit TEXT, kategorie_id INTEGER,
                name TEXT, firma TEXT, email TEXT, telefon TEXT,
                notiz TEXT, am_stand INTEGER,
                UNIQUE(tage_id, flipper_id),
                FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE,
                FOREIGN KEY(kategorie_id) REFERENCES kategorien(id) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS merch_artikel (
                id INTEGER PRIMARY KEY, messe_id INTEGER, name TEXT,
                UNIQUE(messe_id, name),
                FOREIGN KEY(messe_id) REFERENCES messen(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS merch_aktionen (
                id INTEGER PRIMARY KEY, artikel_id INTEGER, tage_id INTEGER,
                zeit TEXT, aktion TEXT, wert INTEGER,
                FOREIGN KEY(artikel_id) REFERENCES merch_artikel(id) ON DELETE CASCADE,
                FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS anwesenheit (
                id INTEGER PRIMARY KEY, tage_id INTEGER, typ TEXT, zeit TEXT,
                UNIQUE(tage_id, typ, zeit),
                FOREIGN KEY(tage_id) REFERENCES tage(id) ON DELETE CASCADE);
        """)
        if not self.conn.execute("SELECT 1 FROM kategorien LIMIT 1").fetchone():
            for cat in ("Interessiert", "Anfrage", "Auftrag"):
                self.conn.execute(
                    "INSERT INTO kategorien (name, uuid) VALUES (?, ?)",
                    (cat, str(uuid.uuid4())))

    # ------------------------------------------------------------------
    def _schema_v2(self) -> None:
        def has_col(table: str, col: str) -> bool:
            rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            return any(r["name"] == col for r in rows)

        for col, ddl in [
            ("uuid", "ALTER TABLE kunden ADD COLUMN uuid TEXT"),
            ("event_key", "ALTER TABLE kunden ADD COLUMN event_key TEXT"),
            ("herkunft", "ALTER TABLE kunden ADD COLUMN herkunft TEXT DEFAULT 'flipper'"),
            ("updated_at", "ALTER TABLE kunden ADD COLUMN updated_at TEXT"),
            ("prioritaet", "ALTER TABLE kunden ADD COLUMN prioritaet INTEGER DEFAULT 0"),
            ("prioritaet_notiz", "ALTER TABLE kunden ADD COLUMN prioritaet_notiz TEXT"),
        ]:
            if not has_col("kunden", col):
                self.conn.execute(ddl)

        for table in ("messen", "kategorien"):
            for col in ("uuid",):
                if not has_col(table, col):
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            if not has_col(table, "geloescht"):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN geloescht INTEGER DEFAULT 0")

        for col, ddl in [
            ("uuid", "ALTER TABLE merch_aktionen ADD COLUMN uuid TEXT"),
            ("event_key", "ALTER TABLE merch_aktionen ADD COLUMN event_key TEXT"),
            ("ereignis_typ", "ALTER TABLE merch_aktionen ADD COLUMN ereignis_typ TEXT DEFAULT 'SONSTIGES'"),
        ]:
            if not has_col("merch_aktionen", col):
                self.conn.execute(ddl)

        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS kunden_status_history (
                id INTEGER PRIMARY KEY,
                kunden_uuid TEXT NOT NULL,
                alter_status TEXT,
                neuer_status TEXT,
                geaendert_am TEXT NOT NULL,
                quelle TEXT);
            CREATE TABLE IF NOT EXISTS import_konflikte (
                id INTEGER PRIMARY KEY,
                event_key TEXT,
                feld TEXT,
                alt TEXT,
                neu TEXT,
                zeit TEXT);
        """)

        for table in ("messen", "kategorien", "kunden", "merch_aktionen"):
            rows = self.conn.execute(
                f"SELECT id FROM {table} WHERE uuid IS NULL").fetchall()
            for r in rows:
                self.conn.execute(
                    f"UPDATE {table} SET uuid=? WHERE id=?",
                    (str(uuid.uuid4()), r["id"]))

        rows = self.conn.execute("""
            SELECT k.id, t.datum, k.flipper_id
            FROM kunden k JOIN tage t ON k.tage_id = t.id
            WHERE k.event_key IS NULL
        """).fetchall()
        for r in rows:
            if r["flipper_id"]:
                key = f"{r['datum']}:{r['flipper_id']}"
                self.conn.execute(
                    "UPDATE kunden SET event_key=? WHERE id=?", (key, r["id"]))

        self.conn.executescript("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kunden_event_key
                ON kunden(event_key) WHERE event_key IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_merch_event_key
                ON merch_aktionen(event_key) WHERE event_key IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kunden_uuid ON kunden(uuid);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messen_uuid ON messen(uuid);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kategorien_uuid ON kategorien(uuid);
        """)

    # ------------------------------------------------------------------
    def _get_or_create(self, table: str, **kwargs) -> int:
        with self._lock:
            cols = ", ".join(kwargs.keys())
            ph = ", ".join("?" * len(kwargs))
            cur = self.conn.execute(
                f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({ph})",
                list(kwargs.values()))
            if cur.rowcount > 0 and cur.lastrowid:
                return cur.lastrowid
            where = " AND ".join(f"{k}=?" for k in kwargs.keys())
            row = self.conn.execute(
                f"SELECT id FROM {table} WHERE {where}",
                list(kwargs.values())).fetchone()
            return row["id"]

    # ------------------------------------------------------------------
    def get_messen(self, include_deleted: bool = False):
        with self._lock:
            if include_deleted:
                return self.conn.execute(
                    "SELECT * FROM messen ORDER BY name").fetchall()
            return self.conn.execute(
                "SELECT * FROM messen WHERE COALESCE(geloescht,0)=0 ORDER BY name"
            ).fetchall()

    def get_kategorien(self):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM kategorien WHERE COALESCE(geloescht,0)=0 ORDER BY name"
            ).fetchall()

    # ------------------------------------------------------------------
    def get_kunden(self, messe_id: int | None = None):
        with self._lock:
            sql = """
                SELECT k.*, t.datum, m.name AS messe_name, m.id AS messe_id,
                       c.name AS kategorie_name
                FROM kunden k
                JOIN tage t ON k.tage_id = t.id
                JOIN messen m ON t.messe_id = m.id
                LEFT JOIN kategorien c ON k.kategorie_id = c.id
                WHERE COALESCE(m.geloescht,0)=0
            """
            params: list = []
            if messe_id:
                sql += " AND m.id = ?"
                params.append(messe_id)
            sql += " ORDER BY k.zeit DESC"
            return self.conn.execute(sql, params).fetchall()

    def get_merch(self, messe_id: int):
        with self._lock:
            return self.conn.execute("""
                SELECT a.id, a.name,
                  (SELECT wert FROM merch_aktionen m2
                   WHERE m2.artikel_id=a.id
                   ORDER BY zeit DESC, id DESC LIMIT 1) AS bestand,
                  (SELECT ereignis_typ FROM merch_aktionen m2
                   WHERE m2.artikel_id=a.id
                   ORDER BY zeit DESC, id DESC LIMIT 1) AS letzter_typ
                FROM merch_artikel a
                WHERE a.messe_id = ?
            """, (messe_id,)).fetchall()

    # ------------------------------------------------------------------
    def _resolve_kategorie(self, raw: str) -> int:
        try:
            fid = int(raw)
            row = self.conn.execute(
                "SELECT id FROM kategorien WHERE flipper_id=?", (fid,)).fetchone()
            if row:
                return row["id"]
        except ValueError:
            pass
        row = self.conn.execute(
            "SELECT id FROM kategorien WHERE name=?", (raw,)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO kategorien (name, uuid) VALUES (?, ?)",
            (raw, str(uuid.uuid4())))
        return cur.lastrowid

    @staticmethod
    def compute_prioritaet(kategorie_name: str, email: str, telefon: str) -> int:
        kat = (kategorie_name or "").lower()
        if "auftrag" in kat or "anfrage" in kat:
            return 2
        if "interessiert" in kat and (email or telefon):
            return 1
        return 0

    @staticmethod
    def _compute_am_stand(sorted_events, kunde_zeit: str) -> int:
        if not valid_ts(kunde_zeit):
            return 0
        last = None
        for ev in sorted_events:
            if ev["zeit"] <= kunde_zeit:
                last = ev
            else:
                break
        return 1 if last and last["typ"] == "BETRETEN" else 0

    @staticmethod
    def _parse_kunde_line(line: str) -> dict | None:
        p = line.split("|")
        if len(p) < 7:
            return None
        fid = p[1].lstrip("#")
        try:
            zeit = f"{p[2]} {p[3]}:00"
        except Exception:
            return None
        if len(p) >= 10:
            name, firma, email, tel, notiz = p[5], p[6], p[7], p[8], p[9]
        else:
            name, firma, email, tel, notiz = p[5], (p[6] if len(p) > 6 else ""), "", "", ""
        return {
            "flipper_id": fid, "zeit": zeit, "kategorie_raw": p[4],
            "name": name, "firma": firma, "email": email,
            "telefon": tel, "notiz": notiz,
        }

    @staticmethod
    def _parse_merch_line(line: str, date_str: str) -> dict | None:
        p = line.split(" ", 2)
        if len(p) != 3:
            return None
        name, _, val_str = p[2].rpartition(";")
        try:
            wert = int(val_str)
        except ValueError:
            return None
        if wert < 0 or wert > 1_000_000:
            return None
        typ_map = {
            "STARTBESTAND": "STARTBESTAND",
            "BESTAND": "BESTAND",
            "NACHGEFUELLT": "NACHFUELLUNG",
            "NEU": "ANLAGE",
            "UMBENANNT": "UMBENENNUNG",
            "GELOESCHT": "LOESCHUNG",
        }
        h = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
        return {
            "aktion": p[1], "name": name, "wert": wert,
            "zeit": f"{date_str} 12:00:00",
            "ereignis_typ": typ_map.get(p[1], "SONSTIGES"),
            "event_key": f"{date_str}:{h}",
        }

    # ------------------------------------------------------------------
    def import_flipper_data(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("Importdaten sind kein dict")

        for date_str, text in data.get("days", {}).items():
            if not isinstance(text, str):
                raise ValueError(f"Tag {date_str}: Inhalt ist kein String")
            if "MESSE " not in text:
                raise ValueError(f"Tag {date_str}: Keine MESSE-Zeile")

        with self._lock:
            try:
                self._import_config(data.get("config") or "")
                messe_map = self._import_messen(data.get("messen") or {})
                imported = 0
                for date_str, text in data.get("days", {}).items():
                    self._import_day(date_str, text, messe_map)
                    imported += 1
                self.conn.commit()
                print(f"[import] OK: {imported} Tage übernommen")
            except Exception as exc:
                self.conn.rollback()
                print(f"[import] Rollback wegen {exc!r}")
                raise

    def _import_config(self, text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                fid_str, name = line.split("|", 1)
                try:
                    fid = int(fid_str)
                except ValueError:
                    continue
                self.conn.execute(
                    "INSERT INTO kategorien (flipper_id, name, uuid) VALUES (?, ?, ?) "
                    "ON CONFLICT(flipper_id) DO UPDATE SET name=excluded.name",
                    (fid, name, str(uuid.uuid4())))
            else:
                self.conn.execute(
                    "INSERT OR IGNORE INTO kategorien (name, uuid) VALUES (?, ?)",
                    (line, str(uuid.uuid4())))

    def _import_messen(self, files: dict) -> dict[int, int]:
        messe_map: dict[int, int] = {}
        for filename, text in files.items():
            display = filename
            fid = None
            for line in text.splitlines():
                if line.startswith("ID="):
                    try:
                        fid = int(line[3:])
                    except ValueError:
                        pass
                elif line.startswith("NAME="):
                    display = line[5:].strip()
            if fid is None:
                raise ValueError(f"Messe {filename}: keine gültige ID")
            self.conn.execute(
                "INSERT INTO messen (flipper_id, name, uuid) VALUES (?, ?, ?) "
                "ON CONFLICT(flipper_id) DO UPDATE SET name=excluded.name",
                (fid, display, str(uuid.uuid4())))
            row = self.conn.execute(
                "SELECT id FROM messen WHERE flipper_id=?", (fid,)).fetchone()
            if row:
                messe_map[fid] = row["id"]
        return messe_map

    # ------------------------------------------------------------------
    def _import_day(self, date_str: str, text: str, messe_map: dict[int, int]) -> None:
        lines = text.splitlines()
        messe_val = None
        events: list[dict] = []
        kunden: list[dict] = []
        merch: list[dict] = []

        for line in lines:
            if line.startswith("MESSE "):
                messe_val = line[6:].strip()
            elif line.startswith(("BETRETEN ", "VERLASSEN ")):
                parts = line.split(" ", 1)
                if len(parts) == 2 and valid_ts(parts[1].strip()):
                    events.append({"typ": parts[0], "zeit": parts[1].strip()})
            elif line.startswith("KUNDE|"):
                k = self._parse_kunde_line(line)
                if k:
                    kunden.append(k)
            elif line.startswith("MERCH "):
                m = self._parse_merch_line(line, date_str)
                if m:
                    merch.append(m)

        messe_id: int | None = None
        if messe_val is not None:
            try:
                messe_id = messe_map.get(int(messe_val))
            except ValueError:
                row = self.conn.execute(
                    "SELECT id FROM messen WHERE name=? AND COALESCE(geloescht,0)=0",
                    (messe_val,)).fetchone()
                if row:
                    messe_id = row["id"]
        if messe_id is None:
            raise ValueError(
                f"Unbekannte Messe-ID '{messe_val}' in Tagesdatei {date_str}; "
                f"Import wird abgebrochen (keine stille Zuordnung).")

        row = self.conn.execute(
            "SELECT id FROM tage WHERE messe_id=? AND datum=?",
            (messe_id, date_str)).fetchone()
        if row:
            tage_id = row["id"]
        else:
            cur = self.conn.execute(
                "INSERT INTO tage (messe_id, datum) VALUES (?, ?)",
                (messe_id, date_str))
            tage_id = cur.lastrowid

        events.sort(key=lambda e: e["zeit"])
        for ev in events:
            self.conn.execute(
                "INSERT OR IGNORE INTO anwesenheit (tage_id, typ, zeit) "
                "VALUES (?, ?, ?)", (tage_id, ev["typ"], ev["zeit"]))

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for k in kunden:
            event_key = f"{date_str}:{k['flipper_id']}"
            am_stand = self._compute_am_stand(events, k["zeit"])
            cat_id = self._resolve_kategorie(k["kategorie_raw"])
            cat_row = self.conn.execute(
                "SELECT name FROM kategorien WHERE id=?", (cat_id,)).fetchone()
            kat_name = cat_row["name"] if cat_row else ""
            prio = self.compute_prioritaet(kat_name, k["email"], k["telefon"])

            existing = self.conn.execute(
                "SELECT id, herkunft, kategorie_id, uuid FROM kunden WHERE event_key=?",
                (event_key,)).fetchone()

            if existing:
                if existing["herkunft"] == "manuell":
                    self.conn.execute(
                        "INSERT INTO import_konflikte (event_key, feld, alt, neu, zeit) "
                        "VALUES (?, 'all', 'manuell', 'flipper', ?)",
                        (event_key, now))
                    continue
                self.conn.execute("""
                    UPDATE kunden SET tage_id=?, zeit=?, kategorie_id=?, name=?,
                        firma=?, email=?, telefon=?, notiz=?, am_stand=?,
                        prioritaet=?, updated_at=?
                    WHERE event_key=?
                """, (tage_id, k["zeit"], cat_id, k["name"], k["firma"],
                      k["email"], k["telefon"], k["notiz"], am_stand,
                      prio, now, event_key))
                if existing["kategorie_id"] != cat_id:
                    self.conn.execute(
                        "INSERT INTO kunden_status_history "
                        "(kunden_uuid, alter_status, neuer_status, geaendert_am, quelle) "
                        "VALUES (?, ?, ?, ?, 'flipper')",
                        (existing["uuid"],
                         str(existing["kategorie_id"]), str(cat_id), now))
            else:
                self.conn.execute("""
                    INSERT INTO kunden
                        (uuid, event_key, herkunft, tage_id, flipper_id, zeit,
                         kategorie_id, name, firma, email, telefon, notiz,
                         am_stand, prioritaet, updated_at)
                    VALUES (?, ?, 'flipper', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), event_key, tage_id, k["flipper_id"],
                      k["zeit"], cat_id, k["name"], k["firma"], k["email"],
                      k["telefon"], k["notiz"], am_stand, prio, now))

        for m in merch:
            art_id = self._get_or_create(
                "merch_artikel", messe_id=messe_id, name=m["name"])
            self.conn.execute("""
                INSERT OR IGNORE INTO merch_aktionen
                    (uuid, event_key, artikel_id, tage_id, zeit, aktion,
                     ereignis_typ, wert)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), m["event_key"], art_id, tage_id,
                  m["zeit"], m["aktion"], m["ereignis_typ"], m["wert"]))

    # ------------------------------------------------------------------
    def record_kunde_edit(self, kunden_id: int, neue_kat_id: int | None,
                          prioritaet: int | None) -> None:
        with self._lock:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = self.conn.execute(
                "SELECT uuid, kategorie_id FROM kunden WHERE id=?", (kunden_id,)).fetchone()
            if not row:
                return
            sets = ["herkunft='manuell'", "updated_at=?"]
            params: list = [now]
            if neue_kat_id is not None and row["kategorie_id"] != neue_kat_id:
                sets.append("kategorie_id=?")
                params.append(neue_kat_id)
                self.conn.execute(
                    "INSERT INTO kunden_status_history "
                    "(kunden_uuid, alter_status, neuer_status, geaendert_am, quelle) "
                    "VALUES (?, ?, ?, ?, 'manuell')",
                    (row["uuid"], str(row["kategorie_id"]), str(neue_kat_id), now))
            if prioritaet is not None:
                sets.append("prioritaet=?")
                params.append(prioritaet)
            params.append(kunden_id)
            self.conn.execute(
                f"UPDATE kunden SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()

    # ------------------------------------------------------------------
    def soft_delete_messe(self, messe_id: int) -> Path | None:
        bak = self._backup()
        with self._lock:
            self.conn.execute(
                "UPDATE messen SET geloescht=1 WHERE id=?", (messe_id,))
            self.conn.commit()
        return bak

    def restore_messe(self, messe_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE messen SET geloescht=0 WHERE id=?", (messe_id,))
            self.conn.commit()


# =========================================================================
# SyncWorker
# =========================================================================
class SyncWorker(QThread):
    """Worker-Thread. Nutzt `completed` für Daten, das eingebaute
    `finished`-Signal bleibt für Aufräumarbeiten (Button-Freigabe)."""

    completed = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, port, mode, db):
        super().__init__()
        self.port = port
        self.mode = mode
        self.db = db

    def run(self) -> None:
        cli = None
        try:
            port = self.port
            if not port:
                cand = [
                    p.device for p in list_ports.comports()
                    if getattr(p, "vid", 0) == 0x0483
                    or "flipper" in (p.description or "").lower()
                ]
                if not cand:
                    raise RuntimeError("Kein Flipper gefunden.")
                port = cand[0]

            self.log.emit(f"Verbinde mit {port} …")
            cli = FlipperCLI(port, self.log.emit)

            if self.mode == "pull":
                self._pull(cli)
            elif self.mode == "push":
                self._push(cli)
            else:
                raise ValueError(f"Unbekannter Modus: {self.mode}")
        except Exception as exc:
            self.log.emit(f"FEHLER: {exc}")
            self.error.emit(str(exc))
        finally:
            if cli is not None:
                cli.close()

    # ------------------------------------------------------------------
    def _pull(self, cli: FlipperCLI) -> None:
        data = {"days": {}, "messen": {}, "config": ""}

        if self.isInterruptionRequested():
            self.log.emit("Pull abgebrochen (vor Start).")
            return

        self.log.emit("Lese Kategorien …")
        try:
            cfg = cli.read_file(CONFIG_PATH)
            data["config"] = cfg or ""
        except FlipperCLIError as exc:
            self.log.emit(f"WARNUNG config.txt: {exc}")

        if self.isInterruptionRequested():
            self.log.emit("Pull abgebrochen (nach config.txt).")
            return

        self.log.emit("Lese Messen …")
        try:
            for name, is_dir in cli.list_dir(MESSEN_DIR):
                if self.isInterruptionRequested():
                    self.log.emit("Pull abgebrochen (Messen).")
                    return
                if is_dir or not name.endswith(".txt"):
                    continue
                content = cli.read_file(f"{MESSEN_DIR}/{name}")
                if content is not None:
                    data["messen"][name[:-4]] = content
        except FlipperCLIError as exc:
            raise RuntimeError(f"Messen konnten nicht gelesen werden: {exc}") from exc

        if self.isInterruptionRequested():
            self.log.emit("Pull abgebrochen (nach Messen).")
            return

        self.log.emit("Lese Tage …")
        try:
            for name, is_dir in cli.list_dir(DAYS_DIR):
                if self.isInterruptionRequested():
                    self.log.emit("Pull abgebrochen (Tage).")
                    return
                if is_dir or not name.endswith(".txt"):
                    continue
                content = cli.read_file(f"{DAYS_DIR}/{name}")
                if content is None:
                    raise RuntimeError(f"Tag {name} konnte nicht gelesen werden")
                data["days"][name[:-4]] = content
        except FlipperCLIError as exc:
            raise RuntimeError(f"Tage konnten nicht gelesen werden: {exc}") from exc

        self.completed.emit(data)

    # ------------------------------------------------------------------
    def _push(self, cli: FlipperCLI) -> None:
        self.log.emit("--- PUSH ZUM FLIPPER GESTARTET ---")

        kats = self.db.get_kategorien()
        messen = self.db.get_messen()

        pending_kat_ids: list[tuple[int, int]] = []
        pending_messen_ids: list[tuple[int, int]] = []

        lines = []
        for k in kats:
            fid = k["flipper_id"]
            if fid is None:
                fid = k["id"]
                pending_kat_ids.append((k["id"], fid))
            lines.append(f"{fid}|{k['name']}")
        config_content = "\n".join(lines) + "\n"

        if self.isInterruptionRequested():
            self.log.emit("Push abgebrochen (vor config.txt).")
            return

        cli.write_file(CONFIG_PATH, config_content)
        self.log.emit("config.txt verifiziert")

        for m in messen:
            if self.isInterruptionRequested():
                self.log.emit("Push abgebrochen (nach config.txt).")
                return
            fid = m["flipper_id"]
            if fid is None:
                fid = m["id"]
                pending_messen_ids.append((m["id"], fid))
            slug = sanitize_name(m["name"])
            m_lines = [f"ID={fid}", f"NAME={m['name']}"]
            for art in self.db.get_merch(m["id"]):
                m_lines.append(f"PRODUKT {art['name']}")
            cli.write_file(
                f"{MESSEN_DIR}/{slug}.txt", "\n".join(m_lines) + "\n")

        if self.isInterruptionRequested():
            self.log.emit("Push abgebrochen (vor ID-Übernahme).")
            return

        with self.db._lock:
            for kid, fid in pending_kat_ids:
                self.db.conn.execute(
                    "UPDATE kategorien SET flipper_id=? WHERE id=?", (fid, kid))
            for mid, fid in pending_messen_ids:
                self.db.conn.execute(
                    "UPDATE messen SET flipper_id=? WHERE id=?", (fid, mid))
            self.db.conn.commit()

        self.log.emit("--- PUSH ERFOLGREICH VERIFIZIERT ---")
        self.completed.emit({"status": "push_ok"})


# =========================================================================
# Dialoge
# =========================================================================
class MesseDialog(QDialog):
    def __init__(self, name: str = "", ort: str = ""):
        super().__init__()
        self.setWindowTitle("Messe")
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.ort = QLineEdit(ort)
        form.addRow("Name der Messe:", self.name)
        form.addRow("Ort (optional):", self.ort)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)


class CustomerDialog(QDialog):
    def __init__(self, db: Database, customer=None):
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
        for cat in db.get_kategorien():
            self.kategorie.addItem(cat["name"], cat["id"])
        if customer and customer["kategorie_id"]:
            idx = self.kategorie.findData(customer["kategorie_id"])
            if idx >= 0:
                self.kategorie.setCurrentIndex(idx)

        self.prioritaet = QComboBox()
        self.prioritaet.addItem("Niedrig", 0)
        self.prioritaet.addItem("Mittel", 1)
        self.prioritaet.addItem("Hoch", 2)
        if customer:
            idx = self.prioritaet.findData(int(customer["prioritaet"] or 0))
            if idx >= 0:
                self.prioritaet.setCurrentIndex(idx)

        self.am_stand = QCheckBox("Am Stand getroffen")
        if customer:
            self.am_stand.setChecked(bool(customer["am_stand"]))

        form.addRow("Name:", self.name)
        form.addRow("Firma:", self.firma)
        form.addRow("E-Mail:", self.email)
        form.addRow("Telefon:", self.telefon)
        form.addRow("Kategorie:", self.kategorie)
        form.addRow("Priorität:", self.prioritaet)
        form.addRow("Notiz:", self.notiz)
        form.addRow(self.am_stand)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)


# =========================================================================
# Dashboard
# =========================================================================
class DashboardTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker = None
        v = QVBoxLayout(self)

        h = QHBoxLayout()
        self.port_combo = QComboBox()
        self.btn_pull = QPushButton("Pull (Daten empfangen)")
        self.btn_pull.clicked.connect(lambda: self.sync("pull"))
        self.btn_push = QPushButton("Push (Daten senden)")
        self.btn_push.setObjectName("Ghost")
        self.btn_push.clicked.connect(lambda: self.sync("push"))
        h.addWidget(QLabel("Port:"))
        h.addWidget(self.port_combo, 1)
        h.addWidget(self.btn_pull)
        h.addWidget(self.btn_push)
        v.addLayout(h)

        stats = QHBoxLayout()
        self.stat_cards = {}
        for key, label in [
            ("kunden", "Kunden (aktive Messe)"),
            ("tage", "Messetage"),
            ("stand", "Am Stand getroffen"),
            ("quote", "Am-Stand-Quote"),
        ]:
            card = QGroupBox(label)
            lay = QVBoxLayout(card)
            lbl = QLabel("–", objectName="Stat")
            lay.addWidget(lbl)
            self.stat_cards[key] = lbl
            stats.addWidget(card)
        v.addLayout(stats)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background: #050505; font-family: monospace;")
        v.addWidget(QLabel("Synchronisations-Log:"))
        v.addWidget(self.log_view, 1)

    # ------------------------------------------------------------------
    def refresh(self):
        self.port_combo.clear()
        for p in list_ports.comports():
            self.port_combo.addItem(f"{p.device} ({p.description})", p.device)
        fid = self.main.current_fair_id
        if fid:
            kunden = self.main.db.get_kunden(fid)
            tage = self.main.db.conn.execute(
                "SELECT COUNT(*) FROM tage WHERE messe_id=?", (fid,)).fetchone()[0]
            stand = sum(1 for k in kunden if k["am_stand"])
            quote = (stand / len(kunden) * 100) if kunden else 0
        else:
            kunden, tage, stand, quote = [], 0, 0, 0
        self.stat_cards["kunden"].setText(str(len(kunden)))
        self.stat_cards["tage"].setText(str(tage))
        self.stat_cards["stand"].setText(str(stand))
        self.stat_cards["quote"].setText(f"{quote:.1f} %")

    # ------------------------------------------------------------------
    def _reset_buttons(self):
        self.btn_pull.setEnabled(True)
        self.btn_push.setEnabled(True)

    def sync(self, mode: str):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Sync läuft",
                                "Bitte warten, bis der laufende Sync beendet ist.")
            return
        port = self.port_combo.currentData()
        self.btn_pull.setEnabled(False)
        self.btn_push.setEnabled(False)
        self.log_view.clear()

        self.worker = SyncWorker(port, mode, self.main.db)
        self.worker.log.connect(self.log_view.append)
        self.worker.error.connect(self._on_error)
        self.worker.completed.connect(self._on_done)
        # Eingebautes `finished`-Signal: gibt Buttons immer frei,
        # auch wenn der Thread abgebrochen wurde.
        self.worker.finished.connect(self._reset_buttons)
        self.worker.start()

    def _on_error(self, msg: str):
        QMessageBox.critical(self, "Fehler", msg)

    def _on_done(self, data: dict):
        try:
            if data.get("status") == "push_ok":
                self.log_view.append("✅ Push vollständig verifiziert.")
            else:
                self.main.db.import_flipper_data(data)
                self.log_view.append("✅ Pull abgeschlossen, Datenbank aktualisiert.")
                self.main.refresh_all()
        except Exception as exc:
            self.log_view.append(f"❌ Import fehlgeschlagen: {exc}")
            QMessageBox.critical(self, "Import", str(exc))


# =========================================================================
# Settings
# =========================================================================
class SettingsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)

        m_box = QGroupBox("Messen")
        ml = QVBoxLayout(m_box)
        mh = QHBoxLayout()
        for label, slot, ghost in [
            ("+ Messe", self.add_messe, False),
            ("Bearbeiten", self.edit_messe, False),
            ("Löschen (Soft)", self.delete_messe, True),
            ("Wiederherstellen", self.restore_messe, True),
        ]:
            btn = QPushButton(label)
            if ghost:
                btn.setObjectName("Ghost")
            btn.clicked.connect(slot)
            mh.addWidget(btn)
        mh.addStretch(1)
        ml.addLayout(mh)
        self.m_table = QTableWidget(0, 4)
        self.m_table.setHorizontalHeaderLabels(
            ["Name", "Ort", "Flipper-ID", "Gelöscht"])
        self.m_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.m_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.m_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        ml.addWidget(self.m_table)
        v.addWidget(m_box)

        k_box = QGroupBox("Kategorien")
        kl = QVBoxLayout(k_box)
        kh = QHBoxLayout()
        btn_k_add = QPushButton("+ Kategorie")
        btn_k_add.clicked.connect(self.add_kategorie)
        btn_k_del = QPushButton("Löschen")
        btn_k_del.setObjectName("Ghost")
        btn_k_del.clicked.connect(self.delete_kategorie)
        kh.addWidget(btn_k_add)
        kh.addWidget(btn_k_del)
        kh.addStretch(1)
        kl.addLayout(kh)
        self.k_table = QTableWidget(0, 2)
        self.k_table.setHorizontalHeaderLabels(["Name", "Flipper-ID"])
        self.k_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.k_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        kl.addWidget(self.k_table)
        v.addWidget(k_box)

    # ------------------------------------------------------------------
    def refresh(self):
        messen = self.main.db.get_messen(include_deleted=True)
        self.m_table.setRowCount(len(messen))
        for r, m in enumerate(messen):
            self.m_table.setItem(r, 0, QTableWidgetItem(m["name"]))
            self.m_table.setItem(r, 1, QTableWidgetItem(m["ort"] or ""))
            self.m_table.setItem(r, 2, QTableWidgetItem(
                str(m["flipper_id"]) if m["flipper_id"] else "Neu"))
            self.m_table.setItem(r, 3, QTableWidgetItem(
                "Ja" if m["geloescht"] else "Nein"))
            self.m_table.item(r, 0).setData(Qt.UserRole, m["id"])

        kats = self.main.db.get_kategorien()
        self.k_table.setRowCount(len(kats))
        for r, k in enumerate(kats):
            self.k_table.setItem(r, 0, QTableWidgetItem(k["name"]))
            self.k_table.setItem(r, 1, QTableWidgetItem(
                str(k["flipper_id"]) if k["flipper_id"] else "Neu"))
            self.k_table.item(r, 0).setData(Qt.UserRole, k["id"])

    # ------------------------------------------------------------------
    def add_messe(self):
        dlg = MesseDialog()
        if dlg.exec_():
            try:
                self.main.db.conn.execute(
                    "INSERT INTO messen (name, ort, uuid) VALUES (?, ?, ?)",
                    (dlg.name.text(), dlg.ort.text(), str(uuid.uuid4())))
                self.main.db.conn.commit()
                self.main.refresh_all()
            except Exception as exc:
                QMessageBox.critical(self, "Fehler", str(exc))

    def edit_messe(self):
        row = self.m_table.currentRow()
        if row < 0:
            return
        mid = self.m_table.item(row, 0).data(Qt.UserRole)
        dlg = MesseDialog(
            self.m_table.item(row, 0).text(), self.m_table.item(row, 1).text())
        if dlg.exec_():
            self.main.db.conn.execute(
                "UPDATE messen SET name=?, ort=? WHERE id=?",
                (dlg.name.text(), dlg.ort.text(), mid))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete_messe(self):
        row = self.m_table.currentRow()
        if row < 0:
            return
        mid = self.m_table.item(row, 0).data(Qt.UserRole)
        name = self.m_table.item(row, 0).text()
        ans = QMessageBox.question(
            self, "Messe löschen",
            f"Messe '{name}' wirklich löschen?\n\n"
            f"Es wird automatisch ein Backup der Datenbank angelegt. "
            f"Die Messe kann über 'Wiederherstellen' zurückgeholt werden.")
        if ans != QMessageBox.Yes:
            return
        try:
            bak = self.main.db.soft_delete_messe(mid)
            QMessageBox.information(
                self, "Gelöscht",
                f"Messe '{name}' als gelöscht markiert.\n"
                f"Backup: {bak}")
            self.main.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", str(exc))

    def restore_messe(self):
        row = self.m_table.currentRow()
        if row < 0:
            return
        mid = self.m_table.item(row, 0).data(Qt.UserRole)
        self.main.db.restore_messe(mid)
        self.main.refresh_all()

    def add_kategorie(self):
        name, ok = QInputDialog.getText(self, "Kategorie", "Name:")
        if ok and name:
            self.main.db.conn.execute(
                "INSERT OR IGNORE INTO kategorien (name, uuid) VALUES (?, ?)",
                (name, str(uuid.uuid4())))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete_kategorie(self):
        row = self.k_table.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Löschen", "Kategorie löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute(
                "UPDATE kategorien SET geloescht=1 WHERE id=?",
                (self.k_table.item(row, 0).data(Qt.UserRole),))
            self.main.db.conn.commit()
            self.main.refresh_all()


# =========================================================================
# Kunden
# =========================================================================
class CustomersTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        btn_add = QPushButton("+ Kunde")
        btn_add.clicked.connect(self.add)
        btn_edit = QPushButton("Bearbeiten")
        btn_edit.clicked.connect(self.edit)
        btn_del = QPushButton("Löschen")
        btn_del.setObjectName("Ghost")
        btn_del.clicked.connect(self.delete)
        h.addWidget(btn_add)
        h.addWidget(btn_edit)
        h.addWidget(btn_del)
        h.addStretch(1)
        v.addLayout(h)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "ID", "Flipper-ID", "Datum", "Name", "Firma",
            "Kategorie", "Prio", "Stand", "Notiz"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i in (3, 4):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
        v.addWidget(self.table)

    def refresh(self):
        fid = self.main.current_fair_id
        if not fid:
            self.table.setRowCount(0)
            return
        kunden = self.main.db.get_kunden(fid)
        self.table.setRowCount(len(kunden))
        prio_label = {0: "Niedrig", 1: "Mittel", 2: "Hoch"}
        for r, k in enumerate(kunden):
            self.table.setItem(r, 0, QTableWidgetItem(str(k["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(k["flipper_id"] or "-"))
            self.table.setItem(r, 2, QTableWidgetItem((k["zeit"] or "")[:16]))
            self.table.setItem(r, 3, QTableWidgetItem(k["name"] or ""))
            self.table.setItem(r, 4, QTableWidgetItem(k["firma"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(k["kategorie_name"] or ""))
            self.table.setItem(r, 6, QTableWidgetItem(
                prio_label.get(int(k["prioritaet"] or 0), "Niedrig")))
            self.table.setItem(r, 7, QTableWidgetItem("Ja" if k["am_stand"] else "Nein"))
            self.table.setItem(r, 8, QTableWidgetItem(k["notiz"] or ""))
            self.table.item(r, 0).setData(Qt.UserRole, k["id"])

    def _selected_id(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.UserRole) if row >= 0 else None

    def add(self):
        fid = self.main.current_fair_id
        if not fid:
            return QMessageBox.warning(self, "Fehler", "Keine Messe ausgewählt.")
        dlg = CustomerDialog(self.main.db)
        if dlg.exec_():
            datum = datetime.now().strftime("%Y-%m-%d")
            tage_id = self.main.db._get_or_create("tage", messe_id=fid, datum=datum)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.main.db.conn.execute("""
                INSERT INTO kunden (uuid, herkunft, tage_id, zeit,
                    name, firma, email, telefon, kategorie_id, notiz,
                    prioritaet, am_stand, updated_at)
                VALUES (?, 'manuell', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), tage_id, now,
                  dlg.name.text(), dlg.firma.text(), dlg.email.text(),
                  dlg.telefon.text(), dlg.kategorie.currentData(),
                  dlg.notiz.toPlainText(), dlg.prioritaet.currentData(),
                  1 if dlg.am_stand.isChecked() else 0, now))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def edit(self):
        cid = self._selected_id()
        if not cid:
            return
        k = self.main.db.conn.execute(
            "SELECT * FROM kunden WHERE id=?", (cid,)).fetchone()
        dlg = CustomerDialog(self.main.db, k)
        if dlg.exec_():
            self.main.db.conn.execute("""
                UPDATE kunden SET name=?, firma=?, email=?, telefon=?,
                    kategorie_id=?, notiz=?, prioritaet=?, am_stand=?,
                    herkunft='manuell', updated_at=?
                WHERE id=?
            """, (dlg.name.text(), dlg.firma.text(), dlg.email.text(),
                  dlg.telefon.text(), dlg.kategorie.currentData(),
                  dlg.notiz.toPlainText(), dlg.prioritaet.currentData(),
                  1 if dlg.am_stand.isChecked() else 0,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid))
            self.main.db.conn.commit()
            self.main.refresh_all()

    def delete(self):
        cid = self._selected_id()
        if cid and QMessageBox.question(
                self, "Löschen", "Kunde löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute("DELETE FROM kunden WHERE id=?", (cid,))
            self.main.db.conn.commit()
            self.main.refresh_all()


# =========================================================================
# Merch
# =========================================================================
class MerchTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        btn_add = QPushButton("+ Artikel")
        btn_add.clicked.connect(self.add_article)
        btn_del = QPushButton("Löschen")
        btn_del.setObjectName("Ghost")
        btn_del.clicked.connect(self.delete_article)
        btn_count = QPushButton("Bestand aufnehmen")
        btn_count.clicked.connect(self.count_stock)
        h.addWidget(btn_add)
        h.addWidget(btn_del)
        h.addWidget(btn_count)
        h.addStretch(1)
        v.addLayout(h)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Artikel", "Bestand", "Letzter Typ"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        v.addWidget(self.table)

    def refresh(self):
        fid = self.main.current_fair_id
        if not fid:
            self.table.setRowCount(0)
            return
        items = self.main.db.get_merch(fid)
        self.table.setRowCount(len(items))
        for r, item in enumerate(items):
            self.table.setItem(r, 0, QTableWidgetItem(str(item["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(item["name"]))
            self.table.setItem(r, 2, QTableWidgetItem(str(item["bestand"] or 0)))
            self.table.setItem(r, 3, QTableWidgetItem(item["letzter_typ"] or "–"))
            self.table.item(r, 0).setData(Qt.UserRole, item["id"])

    def add_article(self):
        fid = self.main.current_fair_id
        if not fid:
            return
        name, ok = QInputDialog.getText(self, "Neuer Artikel", "Name:")
        if ok and name:
            self.main.db.conn.execute(
                "INSERT OR IGNORE INTO merch_artikel (messe_id, name) VALUES (?, ?)",
                (fid, name))
            self.main.db.conn.commit()
            self.refresh()

    def delete_article(self):
        row = self.table.currentRow()
        if row < 0:
            return
        aid = self.table.item(row, 0).data(Qt.UserRole)
        if QMessageBox.question(self, "Löschen", "Artikel löschen?") == QMessageBox.Yes:
            self.main.db.conn.execute(
                "DELETE FROM merch_artikel WHERE id=?", (aid,))
            self.main.db.conn.commit()
            self.refresh()

    def count_stock(self):
        row = self.table.currentRow()
        if row < 0:
            return
        aid = self.table.item(row, 0).data(Qt.UserRole)
        name = self.table.item(row, 1).text()
        val, ok = QInputDialog.getInt(
            self, f"Bestand: {name}", "Neuer Bestand:", 0, 0, 1_000_000)
        if ok:
            fid = self.main.current_fair_id
            datum = datetime.now().strftime("%Y-%m-%d")
            tage_id = self.main.db._get_or_create("tage", messe_id=fid, datum=datum)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.main.db.conn.execute("""
                INSERT INTO merch_aktionen
                    (uuid, artikel_id, tage_id, zeit, aktion, ereignis_typ, wert)
                VALUES (?, ?, ?, ?, 'BESTAND', 'BESTAND', ?)
            """, (str(uuid.uuid4()), aid, tage_id, now, val))
            self.main.db.conn.commit()
            self.refresh()


# =========================================================================
# Analytics
# =========================================================================
class AnalyticsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Messe:"))
        self.f_messe = QComboBox()
        bar.addWidget(self.f_messe)
        bar.addWidget(QLabel("Tag:"))
        self.f_tag = QComboBox()
        bar.addWidget(self.f_tag)
        bar.addWidget(QLabel("Kategorie:"))
        self.f_kat = QComboBox()
        bar.addWidget(self.f_kat)
        btn = QPushButton("Aktualisieren")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        bar.addStretch(1)
        outer.addLayout(bar)

        self.stats_row = QHBoxLayout()
        self.cards: dict[str, QLabel] = {}
        for key, label in [
            ("kontakte", "Kontakte gesamt"),
            ("tage", "Messetage"),
            ("avg_tag", "Ø Kontakte/Tag"),
            ("avg_h", "Ø Kontakte/h"),
            ("am_stand", "Am Stand"),
            ("quote", "Am-Stand-Quote"),
            ("interessenten", "Interessenten"),
            ("anfragen", "Anfragen"),
            ("auftraege", "Aufträge"),
            ("fehlend", "Fehlende Kontaktdaten"),
        ]:
            card = QGroupBox(label)
            lay = QVBoxLayout(card)
            lbl = QLabel("–", objectName="Stat")
            lay.addWidget(lbl)
            self.cards[key] = lbl
            self.stats_row.addWidget(card)
        outer.addLayout(self.stats_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.canvas_host = QWidget()
        self.canvas_layout = QVBoxLayout(self.canvas_host)
        scroll.setWidget(self.canvas_host)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    def _populate_filters(self):
        cur_m = self.f_messe.currentData()
        self.f_messe.blockSignals(True)
        self.f_messe.clear()
        self.f_messe.addItem("Alle Messen", None)
        for m in self.main.db.get_messen():
            self.f_messe.addItem(m["name"], m["id"])
        if cur_m is not None:
            idx = self.f_messe.findData(cur_m)
            if idx >= 0:
                self.f_messe.setCurrentIndex(idx)
        self.f_messe.blockSignals(False)

        cur_t = self.f_tag.currentData()
        self.f_tag.clear()
        self.f_tag.addItem("Alle Tage", None)
        if self.main.current_fair_id:
            rows = self.main.db.conn.execute(
                "SELECT DISTINCT datum FROM tage WHERE messe_id=? ORDER BY datum",
                (self.main.current_fair_id,)).fetchall()
            for r in rows:
                self.f_tag.addItem(r["datum"], r["datum"])
        if cur_t is not None:
            idx = self.f_tag.findData(cur_t)
            if idx >= 0:
                self.f_tag.setCurrentIndex(idx)

        cur_k = self.f_kat.currentData()
        self.f_kat.clear()
        self.f_kat.addItem("Alle Kategorien", None)
        for k in self.main.db.get_kategorien():
            self.f_kat.addItem(k["name"], k["id"])
        if cur_k is not None:
            idx = self.f_kat.findData(cur_k)
            if idx >= 0:
                self.f_kat.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    def _kunden(self):
        sql = """
            SELECT k.*, t.datum, m.id AS messe_id, m.name AS messe_name,
                   c.name AS kategorie_name
            FROM kunden k
            JOIN tage t ON k.tage_id = t.id
            JOIN messen m ON t.messe_id = m.id
            LEFT JOIN kategorien c ON k.kategorie_id = c.id
            WHERE COALESCE(m.geloescht,0)=0
        """
        params: list = []
        if self.f_messe.currentData():
            sql += " AND m.id = ?"
            params.append(self.f_messe.currentData())
        if self.f_tag.currentData():
            sql += " AND t.datum = ?"
            params.append(self.f_tag.currentData())
        if self.f_kat.currentData():
            sql += " AND k.kategorie_id = ?"
            params.append(self.f_kat.currentData())
        sql += " ORDER BY k.zeit ASC"
        return self.main.db.conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    def refresh(self):
        self._populate_filters()
        kunden = self._kunden()

        n = len(kunden)
        am_stand = sum(1 for k in kunden if k["am_stand"])
        quote = (am_stand / n * 100) if n else 0
        interessenten = sum(1 for k in kunden if "interessiert" in (k["kategorie_name"] or "").lower())
        anfragen = sum(1 for k in kunden if "anfrage" in (k["kategorie_name"] or "").lower())
        auftraege = sum(1 for k in kunden if "auftrag" in (k["kategorie_name"] or "").lower())
        fehlend = sum(1 for k in kunden if not (k["email"] or k["telefon"]))
        tage_set = {k["datum"] for k in kunden if k["datum"]}
        tage = len(tage_set)

        hours_seen = {int(k["zeit"][11:13]) for k in kunden
                      if k["zeit"] and len(k["zeit"]) >= 13 and k["zeit"][11:13].isdigit()}
        hour_span = (max(hours_seen) - min(hours_seen) + 1) if hours_seen else 0
        avg_h = n / hour_span if hour_span else 0
        avg_t = n / tage if tage else 0

        self.cards["kontakte"].setText(str(n))
        self.cards["tage"].setText(str(tage))
        self.cards["avg_tag"].setText(f"{avg_t:.1f}")
        self.cards["avg_h"].setText(f"{avg_h:.1f}")
        self.cards["am_stand"].setText(str(am_stand))
        self.cards["quote"].setText(f"{quote:.1f} %")
        self.cards["interessenten"].setText(str(interessenten))
        self.cards["anfragen"].setText(str(anfragen))
        self.cards["auftraege"].setText(str(auftraege))
        self.cards["fehlend"].setText(str(fehlend))

        for i in reversed(range(self.canvas_layout.count())):
            w = self.canvas_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        if not kunden:
            lbl = QLabel("Keine Daten für die aktuelle Auswahl.")
            self.canvas_layout.addWidget(lbl)
            return

        fig1 = Figure(figsize=(10, 4), facecolor=FLIPPER["bg_panel"])
        canvas1 = FigureCanvas(fig1)
        ax1 = fig1.add_subplot(1, 2, 1)
        ax2 = fig1.add_subplot(1, 2, 2)
        self._style_ax(ax1)
        self._style_ax(ax2)

        hours = []
        quarters = []
        for k in kunden:
            if k["zeit"] and len(k["zeit"]) >= 16 and k["zeit"][11:13].isdigit():
                h = int(k["zeit"][11:13])
                m = int(k["zeit"][14:16]) if k["zeit"][14:16].isdigit() else 0
                hours.append(h)
                quarters.append(h * 4 + m // 15)
        if hours:
            lo, hi = min(hours), max(hours)
            ax1.hist(hours, bins=range(lo, hi + 2), align="left",
                     color=FLIPPER["accent"], edgecolor=FLIPPER["border"])
            ax1.set_title("Kontakte nach Stunde")
            ax1.set_xlabel("Stunde")
            ax1.set_ylabel("Anzahl")
            lo_q, hi_q = min(quarters), max(quarters)
            ax2.hist(quarters, bins=range(lo_q, hi_q + 2), align="left",
                     color=FLIPPER["accent"], edgecolor=FLIPPER["border"])
            ax2.set_title("Kontakte nach 15-Minuten-Intervall")
            ax2.set_xlabel("Viertelstunde (Stunde*4+Quartal)")
            ax2.set_ylabel("Anzahl")
        fig1.tight_layout()
        self.canvas_layout.addWidget(canvas1)

        fig2 = Figure(figsize=(10, 4), facecolor=FLIPPER["bg_panel"])
        canvas2 = FigureCanvas(fig2)
        ax3 = fig2.add_subplot(1, 2, 1)
        ax4 = fig2.add_subplot(1, 2, 2)
        self._style_ax(ax3)
        self._style_ax(ax4)

        cats: dict[str, int] = {}
        for k in kunden:
            c = k["kategorie_name"] or "Leer"
            cats[c] = cats.get(c, 0) + 1
        names = list(cats.keys())
        vals = [cats[n] for n in names]
        ax3.bar(names, vals, color=FLIPPER["accent"])
        ax3.set_title("Kontakte nach Kategorie")
        ax3.tick_params(axis="x", rotation=30)

        ax4.bar(["Am Stand", "Nicht am Stand"], [am_stand, n - am_stand],
                color=[FLIPPER["accent"], "#555"])
        ax4.set_title(f"Am-Stand-Quote: {quote:.1f}%")
        fig2.tight_layout()
        self.canvas_layout.addWidget(canvas2)

        fig3 = Figure(figsize=(10, 4), facecolor=FLIPPER["bg_panel"])
        canvas3 = FigureCanvas(fig3)
        ax5 = fig3.add_subplot(1, 1, 1)
        self._style_ax(ax5)
        per_day: dict[str, int] = {}
        for k in kunden:
            d = k["datum"] or "?"
            per_day[d] = per_day.get(d, 0) + 1
        days = sorted(per_day)
        ax5.bar(days, [per_day[d] for d in days], color=FLIPPER["accent"])
        ax5.set_title("Kontakte pro Messetag")
        ax5.tick_params(axis="x", rotation=30)
        fig3.tight_layout()
        self.canvas_layout.addWidget(canvas3)

    @staticmethod
    def _style_ax(ax):
        ax.set_facecolor(FLIPPER["bg_panel"])
        ax.tick_params(colors=FLIPPER["fg_text"])
        for sp in ax.spines.values():
            sp.set_color(FLIPPER["border"])
        ax.title.set_color(FLIPPER["accent"])
        ax.yaxis.label.set_color(FLIPPER["fg_text"])
        ax.xaxis.label.set_color(FLIPPER["fg_text"])


# =========================================================================
# MainWindow
# =========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Messe Tracker – Master")
        self.resize(1280, 860)
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
        for m in self.db.get_messen():
            self.fair_combo.addItem(m["name"], m["id"])
        if curr is not None:
            idx = self.fair_combo.findData(curr)
            if idx >= 0:
                self.fair_combo.setCurrentIndex(idx)
        self.current_fair_id = self.fair_combo.currentData()
        self.fair_combo.blockSignals(False)
        self.tab_settings.refresh()
        self._on_fair_changed()

    def closeEvent(self, event):
        """Verhindert 0xC0000409: laufenden Sync-Thread sauber beenden."""
        worker = getattr(self.tab_dash, "worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())