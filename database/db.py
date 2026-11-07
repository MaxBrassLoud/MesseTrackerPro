"""Datenbank-Zugriffsschicht für Messe Tracker Pro.

Ersetzt die zuvor fehlende Datei database/db.py. Migriert bestehende
Datenbanken auf das in database/schema.py definierte Schema (Version 9).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Optional

from database.schema import SCHEMA_SQL, SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row) -> Optional[dict]:
    return dict(row) if row else None


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


class Database:
    def __init__(self, path: str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.path, check_same_thread=False, timeout=10.0
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    def close(self):
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Schema-Initialisierung und Migrationen
    # ------------------------------------------------------------------
    def _column_exists(self, table: str, column: str) -> bool:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def _table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _migrate(self):
        """Ergänzt fehlende Spalten in bestehenden Datenbanken."""
        # contacts.company_id (neu v5)
        if not self._column_exists("contacts", "company_id"):
            try:
                self.conn.execute(
                    "ALTER TABLE contacts ADD COLUMN company_id INTEGER "
                    "REFERENCES companies(id)"
                )
                logger.info("Migration: contacts.company_id ergänzt.")
            except sqlite3.OperationalError as e:
                logger.warning("Migration contacts.company_id: %s", e)
        # companies.address (neu v8)
        if not self._column_exists("companies", "address"):
            try:
                self.conn.execute(
                    "ALTER TABLE companies ADD COLUMN address TEXT"
                )
            except sqlite3.OperationalError:
                pass
        # contact_ocr_details – durch SCHEMA_SQL erzeugt, ID existiert
        # Fallback für ältere DBs, die noch keine v9-Tabellen haben
        if not self._table_exists("contact_ocr_details"):
            try:
                self.conn.executescript("""
                CREATE TABLE contact_ocr_details (
                    contact_id INTEGER PRIMARY KEY
                        REFERENCES contacts(id) ON DELETE CASCADE,
                    field_confidence_json TEXT,
                    detected_language TEXT,
                    raw_text TEXT,
                    ocr_engine TEXT,
                    processed_at TEXT NOT NULL
                );
                """)
            except sqlite3.OperationalError:
                pass
        self.conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) "
            "VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def init_db(self):
        with self._lock:
            self.conn.executescript(SCHEMA_SQL)
            self.conn.commit()
            self._migrate()
            self._seed_defaults()

    def _seed_defaults(self):
        """Sichert Standard-Statuswerte und -Rollen."""
        existing = {
            r["name"] for r in
            self.conn.execute("SELECT name FROM contact_statuses").fetchall()
        }
        for name in ("Interessiert", "Anfrage", "Auftrag erteilt"):
            if name not in existing:
                self.conn.execute(
                    "INSERT INTO contact_statuses "
                    "(name, color, sort_order, active, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (name, "#FF8200", 10, 1, _now()),
                )
        if not self._table_exists("roles") or self.conn.execute(
            "SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
            self.conn.execute(
                "INSERT OR IGNORE INTO roles (id, name, description, "
                "is_system, created_at) VALUES (?,?,?,?,?)",
                (1, "Administrator", "Vollzugriff", 1, _now()),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO roles (id, name, description, "
                "is_system, created_at) VALUES (?,?,?,?,?)",
                (2, "Benutzer", "Standardzugriff", 1, _now()),
            )
            # Standardrechte für Systemrolle „Benutzer"
            for perm in ("data.view", "data.create", "data.edit",
                         "tasks.manage"):
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions "
                    "(role_id, permission) VALUES (2, ?)", (perm,),
                )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Einstellungen
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO app_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit(self, user_id: Optional[int], action: str,
              target_type: str = "", target_id: Optional[int] = None,
              details: str = ""):
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit_log "
                "(timestamp, user_id, action, target_type, target_id, details) "
                "VALUES (?,?,?,?,?,?)",
                (_now(), user_id, action, target_type, target_id, details),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Benutzer / Auth
    # ------------------------------------------------------------------
    def has_any_user(self) -> bool:
        return self.conn.execute(
            "SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def get_user(self, user_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone())

    def get_user_by_username(self, username: str) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone())

    def list_users(self) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM users ORDER BY username").fetchall())

    def create_user(self, username: str, display_name: str, email: str,
                    password_hash: str, password_salt: str,
                    password_iter: int, must_change_password: bool,
                    is_admin: bool) -> int:
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO users (username, display_name, email, "
                "password_hash, password_salt, password_iter, "
                "must_change_password, is_active, is_admin, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (username, display_name, email, password_hash,
                 password_salt, password_iter,
                 int(must_change_password), 1, int(is_admin), now, now),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_user_password(self, user_id: int, pw_hash: str,
                             salt: str, iters: int,
                             must_change_password: bool):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET password_hash=?, password_salt=?, "
                "password_iter=?, must_change_password=?, updated_at=? "
                "WHERE id=?",
                (pw_hash, salt, iters, int(must_change_password),
                 _now(), user_id),
            )
            self.conn.commit()

    def set_user_active(self, user_id: int, active: bool):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET is_active=?, updated_at=? WHERE id=?",
                (int(active), _now(), user_id),
            )
            self.conn.commit()

    def set_user_admin(self, user_id: int, is_admin: bool):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET is_admin=?, updated_at=? WHERE id=?",
                (int(is_admin), _now(), user_id),
            )
            self.conn.commit()

    def count_active_admins(self, exclude_user_id: Optional[int] = None) -> int:
        sql = ("SELECT COUNT(*) FROM users WHERE is_active=1 AND is_admin=1")
        params = []
        if exclude_user_id is not None:
            sql += " AND id<>?"
            params.append(exclude_user_id)
        return self.conn.execute(sql, params).fetchone()[0]

    def set_user_last_login(self, user_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET last_login=?, updated_at=? WHERE id=?",
                (_now(), _now(), user_id),
            )
            self.conn.commit()

    def increment_failed_login(self, user_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET failed_login_count=failed_login_count+1 "
                "WHERE id=?", (user_id,),
            )
            self.conn.commit()

    def get_failed_login_count(self, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT failed_login_count FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return int(row["failed_login_count"]) if row else 0

    def reset_failed_login(self, user_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET failed_login_count=0, locked_until=NULL "
                "WHERE id=?", (user_id,),
            )
            self.conn.commit()

    def set_user_lockout(self, user_id: int, until_iso: str):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET locked_until=? WHERE id=?",
                (until_iso, user_id),
            )
            self.conn.commit()

    def log_login_attempt(self, username: str, ip: str, success: bool):
        with self._lock:
            self.conn.execute(
                "INSERT INTO login_attempts "
                "(username, ip, success, timestamp) VALUES (?,?,?,?)",
                (username, ip, int(success), _now()),
            )
            self.conn.commit()

    # ----- Sessions -----
    def create_session(self, user_id: int, token: str, expires_at: str,
                       ip: str, user_agent: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions "
                "(user_id, token, created_at, expires_at, revoked, ip, "
                "user_agent) VALUES (?,?,?,?,0,?,?)",
                (user_id, token, _now(), expires_at, ip, user_agent),
            )
            self.conn.commit()

    def get_session(self, token: str) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM sessions WHERE token=? AND revoked=0", (token,)
        ).fetchone())

    def revoke_session(self, token: str):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE token=?", (token,),
            )
            self.conn.commit()

    def revoke_user_sessions(self, user_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,),
            )
            self.conn.commit()

    # ----- Rollen / Berechtigungen -----
    def list_roles(self) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM roles ORDER BY id").fetchall())

    def get_role(self, role_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM roles WHERE id=?", (role_id,)).fetchone())

    def create_role(self, name: str, description: str,
                    permissions) -> int:
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO roles (name, description, is_system, "
                "created_at) VALUES (?,?,0,?)",
                (name, description, now),
            )
            role_id = cur.lastrowid
            for p in permissions:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions "
                    "(role_id, permission) VALUES (?, ?)",
                    (role_id, p),
                )
            self.conn.commit()
            return role_id

    def set_user_role(self, user_id: int, role_id: int):
        with self._lock:
            self.conn.execute(
                "DELETE FROM user_roles WHERE user_id=?", (user_id,))
            self.conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                "VALUES (?, ?)", (user_id, role_id),
            )
            self.conn.commit()

    def set_user_roles(self, user_id: int, role_ids):
        with self._lock:
            self.conn.execute(
                "DELETE FROM user_roles WHERE user_id=?", (user_id,))
            for rid in role_ids:
                self.conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (?, ?)", (user_id, rid),
                )
            self.conn.commit()

    def user_role_ids(self, user_id: int) -> set[int]:
        rows = self.conn.execute(
            "SELECT role_id FROM user_roles WHERE user_id=?", (user_id,)
        ).fetchall()
        return {r["role_id"] for r in rows}

    def get_user_permissions(self, user_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT rp.permission FROM role_permissions rp "
            "JOIN user_roles ur ON ur.role_id = rp.role_id "
            "WHERE ur.user_id=?", (user_id,),
        ).fetchall()
        return {r["permission"] for r in rows}

    # ------------------------------------------------------------------
    # Messe / Messetage
    # ------------------------------------------------------------------
    def create_fair(self, name: str, location: str = "",
                    start_date: str = "", end_date: str = "") -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO fairs (name, location, start_date, end_date, "
                "archived, created_at) VALUES (?,?,?,?,0,?)",
                (name, location, start_date, end_date, _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_fairs(self, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM fairs"
        if not include_archived:
            sql += " WHERE archived=0"
        sql += " ORDER BY created_at DESC, id DESC"
        return _rows_to_dicts(self.conn.execute(sql).fetchall())

    def get_fair(self, fair_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM fairs WHERE id=?", (fair_id,)).fetchone())

    def update_fair(self, fair_id: int, **kw):
        allowed = {"name", "location", "start_date", "end_date", "archived"}
        sets, params = [], []
        for k, v in kw.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        params.append(fair_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE fairs SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()

    def start_fair_day(self, fair_id: int, day_date: str = "") -> int:
        with self._lock:
            active = self.conn.execute(
                "SELECT id FROM fair_days WHERE fair_id=? AND is_active=1",
                (fair_id,),
            ).fetchone()
            if active:
                raise ValueError("Es läuft bereits ein Messetag.")
            day = day_date or datetime.now().date().isoformat()
            cur = self.conn.execute(
                "INSERT INTO fair_days (fair_id, day_date, started_at, "
                "is_active) VALUES (?,?,?,1)",
                (fair_id, day, _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def end_fair_day(self, fair_day_id: int):
        with self._lock:
            self.conn.execute(
                "UPDATE fair_days SET ended_at=?, is_active=0 WHERE id=?",
                (_now(), fair_day_id),
            )
            self.conn.commit()

    def get_active_fair_day(self) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM fair_days WHERE is_active=1 "
            "ORDER BY id DESC LIMIT 1").fetchone())

    def list_fair_days(self, fair_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM fair_days WHERE fair_id=? ORDER BY day_date",
            (fair_id,),
        ).fetchall())

    # ------------------------------------------------------------------
    # Mitarbeiter
    # ------------------------------------------------------------------
    def create_employee(self, name: str, email: str = "") -> tuple[int, str]:
        token = uuid.uuid4().hex
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO employees (name, email, phone, active, token, "
                "created_at) VALUES (?,?,?,1,?,?)",
                (name, email, "", token, _now()),
            )
            self.conn.commit()
            return cur.lastrowid, token

    def list_employees(self, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM employees"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name"
        return _rows_to_dicts(self.conn.execute(sql).fetchall())

    def get_employee(self, emp_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone())

    def get_employee_by_token(self, token: str) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM employees WHERE token=?", (token,)).fetchone())

    def get_employee_by_user_id(self, user_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM employees WHERE user_id=?", (user_id,)
        ).fetchone()) if self._column_exists("employees", "user_id") else None

    def ensure_employee_for_user(self, user_id: int, name: str,
                                 email: str = ""):
        """Verknüpft Benutzer mit Mitarbeiterprofil (neu v9)."""
        if not self._column_exists("employees", "user_id"):
            try:
                self.conn.execute(
                    "ALTER TABLE employees ADD COLUMN user_id INTEGER "
                    "REFERENCES users(id)"
                )
            except sqlite3.OperationalError:
                pass
        existing = self.conn.execute(
            "SELECT id FROM employees WHERE user_id=?", (user_id,)
        ).fetchone()
        if existing:
            return existing["id"]
        token = uuid.uuid4().hex
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO employees (name, email, phone, active, token, "
                "created_at, user_id) VALUES (?,?,?,1,?,?,?)",
                (name, email, "", token, _now(), user_id),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_employee(self, emp_id: int, **kw):
        allowed = {"name", "email", "phone", "active"}
        sets, params = [], []
        for k, v in kw.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        params.append(emp_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE employees SET {', '.join(sets)} WHERE id=?",
                params,
            )
            self.conn.commit()

    def regenerate_employee_token(self, emp_id: int) -> str:
        token = uuid.uuid4().hex
        with self._lock:
            self.conn.execute(
                "UPDATE employees SET token=? WHERE id=?", (token, emp_id),
            )
            self.conn.commit()
        return token

    # ------------------------------------------------------------------
    # Anwesenheit
    # ------------------------------------------------------------------
    def add_attendance(self, emp_id: int, fair_id: int, event_type: str,
                       source: str, fair_day_id: Optional[int] = None
                       ) -> tuple[int, bool]:
        if event_type not in ("enter", "leave"):
            raise ValueError("event_type muss 'enter' oder 'leave' sein.")
        with self._lock:
            current = self.conn.execute(
                "SELECT event_type FROM attendance_events "
                "WHERE employee_id=? AND fair_id=? "
                "ORDER BY timestamp DESC, id DESC LIMIT 1",
                (emp_id, fair_id),
            ).fetchone()
            if current and current["event_type"] == event_type:
                return 0, False
            cur = self.conn.execute(
                "INSERT INTO attendance_events "
                "(employee_id, fair_id, fair_day_id, event_type, source, "
                "timestamp) VALUES (?,?,?,?,?,?)",
                (emp_id, fair_id, fair_day_id, event_type, source, _now()),
            )
            self.conn.commit()
            return cur.lastrowid, True

    def current_attendance(self, fair_id: int) -> dict[int, dict]:
        rows = self.conn.execute(
            """SELECT ae.employee_id, ae.event_type, ae.timestamp
               FROM attendance_events ae
               WHERE ae.fair_id=?
                 AND ae.id = (
                   SELECT id FROM attendance_events
                   WHERE employee_id=ae.employee_id AND fair_id=ae.fair_id
                   ORDER BY timestamp DESC, id DESC LIMIT 1
                 )""",
            (fair_id,),
        ).fetchall()
        return {r["employee_id"]: dict(r) for r in rows}

    def attendance_intervals(self, fair_id: int) -> dict[int, list[tuple]]:
        rows = self.conn.execute(
            "SELECT employee_id, event_type, timestamp FROM attendance_events "
            "WHERE fair_id=? ORDER BY employee_id, timestamp, id",
            (fair_id,),
        ).fetchall()
        result: dict[int, list[tuple]] = {}
        opened: dict[int, str] = {}
        for r in rows:
            eid = r["employee_id"]
            if r["event_type"] == "enter":
                opened[eid] = r["timestamp"]
            elif r["event_type"] == "leave" and eid in opened:
                result.setdefault(eid, []).append(
                    (opened.pop(eid), r["timestamp"]))
        # Offene Intervalle bis jetzt laufen lassen
        for eid, start in opened.items():
            result.setdefault(eid, []).append((start, _now()))
        return result

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def list_statuses(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM contact_statuses"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY sort_order, name"
        return _rows_to_dicts(self.conn.execute(sql).fetchall())

    def get_status(self, status_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM contact_statuses WHERE id=?", (status_id,)
        ).fetchone())

    def create_status(self, name: str, color: str = "#FF8200",
                      sort_order: int = 100) -> int:
        if self.conn.execute(
            "SELECT 1 FROM contact_statuses WHERE name=?", (name,)
        ).fetchone():
            raise ValueError(f"Status „{name}“ existiert bereits.")
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO contact_statuses "
                "(name, color, sort_order, active, created_at) "
                "VALUES (?,?,?,1,?)",
                (name, color, sort_order, _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_status(self, status_id: int, **kw):
        allowed = {"name", "color", "sort_order", "active"}
        with self._lock:
            old = self.get_status(status_id)
            if not old:
                return
            sets, params = [], []
            for k, v in kw.items():
                if k in allowed:
                    sets.append(f"{k}=?")
                    params.append(v)
            if not sets:
                return
            params.append(status_id)
            self.conn.execute(
                f"UPDATE contact_statuses SET {', '.join(sets)} WHERE id=?",
                params,
            )
            new_name = kw.get("name")
            if new_name and new_name != old["name"]:
                self.conn.execute(
                    "UPDATE contacts SET status=? WHERE status=?",
                    (new_name, old["name"]),
                )
            self.conn.commit()

    def delete_status(self, status_id: int) -> tuple[int, Optional[str]]:
        s = self.get_status(status_id)
        if not s:
            return 0, "Status nicht gefunden."
        if self.status_usage_count(status_id) > 0:
            return 0, "Status wird noch verwendet."
        with self._lock:
            self.conn.execute(
                "DELETE FROM contact_statuses WHERE id=?", (status_id,),
            )
            self.conn.commit()
        return 1, None

    def status_usage_count(self, status_id: int) -> int:
        s = self.get_status(status_id)
        if not s:
            return 0
        return self.conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE status=?", (s["name"],)
        ).fetchone()[0]

    # ------------------------------------------------------------------
    # Kontakte
    # ------------------------------------------------------------------
    def _ensure_company(self, name: str) -> Optional[int]:
        name = (name or "").strip()
        if not name:
            return None
        row = self.conn.execute(
            "SELECT id FROM companies WHERE name=?", (name,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO companies (name, created_at, updated_at) "
            "VALUES (?,?,?)",
            (name, _now(), _now()),
        )
        return cur.lastrowid

    def create_contact(self, fair_id: int, source: str,
                       fair_day_id: Optional[int] = None,
                       employee_id: Optional[int] = None,
                       name: str = "", company: str = "",
                       position: str = "", phone: str = "",
                       email: str = "", status: str = "Interessiert",
                       notes: str = "", card_image_path: Optional[str] = None,
                       processing_status: str = "ok",
                       external_id: Optional[str] = None,
                       **_) -> int:
        now = _now()
        with self._lock:
            company_id = self._ensure_company(company)
            cur = self.conn.execute(
                """INSERT INTO contacts
                   (fair_id, fair_day_id, employee_id, name, company,
                    position, phone, email, status, notes, source,
                    card_image_path, processing_status, sync_status,
                    external_id, company_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fair_id, fair_day_id, employee_id, name, company,
                 position, phone, email, status, notes, source,
                 card_image_path, processing_status, "synced",
                 external_id, company_id, now, now),
            )
            contact_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO contact_events "
                "(contact_id, event_type, details, created_at) "
                "VALUES (?,?,?,?)",
                (contact_id, "created", f"Quelle: {source}", now),
            )
            self.conn.commit()
            return contact_id

    def create_contact_with_card(self, fair_id: int, source: str,
                                 employee_id: Optional[int],
                                 fair_day_id: Optional[int],
                                 name: str, company: str, position: str,
                                 phone: str, email: str, status: str,
                                 notes: str, image_path: str,
                                 original_filename: str,
                                 external_id: str) -> tuple[int, dict, bool]:
        with self._lock:
            existing = self.conn.execute(
                "SELECT * FROM card_queue WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if existing:
                return 0, dict(existing), False
            cid = self.create_contact(
                fair_id=fair_id, source=source, fair_day_id=fair_day_id,
                employee_id=employee_id, name=name, company=company,
                position=position, phone=phone, email=email, status=status,
                notes=notes, card_image_path=image_path,
                processing_status="ok", external_id=external_id,
            )
            cur = self.conn.execute(
                "INSERT INTO card_queue "
                "(fair_id, fair_day_id, employee_id, image_path, "
                "original_filename, status, contact_id, external_id, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (fair_id, fair_day_id, employee_id, image_path,
                 original_filename, "processed", cid, external_id, _now()),
            )
            self.conn.commit()
            return cid, {"id": cur.lastrowid}, True

    def update_contact(self, contact_id: int, **kw):
        allowed = {"name", "company", "position", "phone", "email",
                   "status", "notes", "card_image_path", "employee_id",
                   "fair_day_id", "processing_status", "company_id"}
        company_val = kw.get("company")
        with self._lock:
            if company_val is not None:
                kw["company_id"] = self._ensure_company(company_val)
            sets, params = [], []
            for k, v in kw.items():
                if k in allowed:
                    sets.append(f"{k}=?")
                    params.append(v)
            if not sets:
                return
            sets.append("updated_at=?")
            params.append(_now())
            params.append(contact_id)
            self.conn.execute(
                f"UPDATE contacts SET {', '.join(sets)} WHERE id=?", params)
            self.conn.execute(
                "INSERT INTO contact_events "
                "(contact_id, event_type, details, created_at) "
                "VALUES (?,?,?,?)",
                (contact_id, "edited", f"Felder: {', '.join(kw.keys())}",
                 _now()),
            )
            self.conn.commit()

    def get_contact(self, contact_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM contacts WHERE id=?", (contact_id,)
        ).fetchone())

    def delete_contact(self, contact_id: int):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contacts WHERE id=?", (contact_id,),
            )
            self.conn.commit()

    def search_contacts(self, fair_id: Optional[int] = None,
                        status: Optional[str] = None,
                        employee_id: Optional[int] = None,
                        text: str = "") -> list[dict]:
        sql = "SELECT * FROM contacts WHERE 1=1"
        params: list = []
        if fair_id:
            sql += " AND fair_id=?"
            params.append(fair_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        if employee_id:
            sql += " AND employee_id=?"
            params.append(employee_id)
        if text:
            t = f"%{text}%"
            sql += (" AND (name LIKE ? OR company LIKE ? OR email LIKE ? "
                    "OR phone LIKE ? OR position LIKE ? OR notes LIKE ?)")
            params.extend([t] * 6)
        sql += " ORDER BY created_at DESC, id DESC"
        return _rows_to_dicts(self.conn.execute(sql, params).fetchall())

    def contact_history(self, contact_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM contact_events WHERE contact_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT 200",
            (contact_id,),
        ).fetchall())

    def add_contact_event(self, contact_id: int, event_type: str,
                          details: str = "",
                          actor_user_id: Optional[int] = None):
        with self._lock:
            self.conn.execute(
                "INSERT INTO contact_events "
                "(contact_id, actor_user_id, event_type, details, "
                "created_at) VALUES (?,?,?,?,?)",
                (contact_id, actor_user_id, event_type, details, _now()),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Firmen
    # ------------------------------------------------------------------
    def get_company(self, company_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM companies WHERE id=?", (company_id,)
        ).fetchone())

    def company_contacts(self, company_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM contacts WHERE company_id=? ORDER BY name",
            (company_id,),
        ).fetchall())

    def set_company_address(self, company_id: int, address: str):
        with self._lock:
            self.conn.execute(
                "UPDATE companies SET address=?, updated_at=? WHERE id=?",
                (address, _now(), company_id),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Kontaktkanäle / -adressen
    # ------------------------------------------------------------------
    def list_contact_channels(self, contact_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM contact_channels WHERE contact_id=? "
            "ORDER BY is_primary DESC, id",
            (contact_id,),
        ).fetchall())

    def add_contact_channel(self, contact_id: int, channel_type: str,
                            value: str, label: str = "",
                            is_primary: bool = False) -> int:
        if channel_type not in ("email", "phone", "website"):
            raise ValueError("Ungültiger Kontaktweg-Typ.")
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO contact_channels "
                "(contact_id, channel_type, value, label, is_primary) "
                "VALUES (?,?,?,?,?)",
                (contact_id, channel_type, value, label, int(is_primary)),
            )
            self.conn.commit()
            return cur.lastrowid

    def delete_contact_channel(self, channel_id: int):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contact_channels WHERE id=?", (channel_id,),
            )
            self.conn.commit()

    def list_contact_addresses(self, contact_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM contact_addresses WHERE contact_id=? "
            "ORDER BY is_primary DESC, id",
            (contact_id,),
        ).fetchall())

    def add_contact_address(self, contact_id: int, street: str = "",
                            postal_code: str = "", city: str = "",
                            country: str = "",
                            label: str = "Geschäftlich",
                            is_primary: bool = False) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO contact_addresses "
                "(contact_id, label, street, postal_code, city, country, "
                "is_primary) VALUES (?,?,?,?,?,?,?)",
                (contact_id, label, street, postal_code, city, country,
                 int(is_primary)),
            )
            self.conn.commit()
            return cur.lastrowid

    def delete_contact_address(self, address_id: int):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contact_addresses WHERE id=?", (address_id,),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Visitenkarten-Warteschlange
    # ------------------------------------------------------------------
    def list_card_queue(self, status: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM card_queue"
        params = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC"
        return _rows_to_dicts(self.conn.execute(sql, params).fetchall())

    def get_card(self, card_id: int) -> Optional[dict]:
        return _row_to_dict(self.conn.execute(
            "SELECT * FROM card_queue WHERE id=?", (card_id,)
        ).fetchone())

    def enqueue_card(self, fair_id: int, image_path: str,
                     fair_day_id: Optional[int], employee_id: Optional[int],
                     original_filename: str,
                     external_id: str) -> tuple[dict, bool]:
        with self._lock:
            existing = self.conn.execute(
                "SELECT * FROM card_queue WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if existing:
                return dict(existing), False
            cur = self.conn.execute(
                "INSERT INTO card_queue "
                "(fair_id, fair_day_id, employee_id, image_path, "
                "original_filename, status, external_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (fair_id, fair_day_id, employee_id, image_path,
                 original_filename, "pending", external_id, _now()),
            )
            self.conn.commit()
            return {"id": cur.lastrowid}, True

    def update_card_ocr(self, card_id: int, status: str = "",
                        ocr_name: str = "", ocr_company: str = "",
                        ocr_position: str = "", ocr_phone: str = "",
                        ocr_email: str = ""):
        sets, params = [], []
        for k, v in (("status", status), ("ocr_name", ocr_name),
                     ("ocr_company", ocr_company),
                     ("ocr_position", ocr_position),
                     ("ocr_phone", ocr_phone),
                     ("ocr_email", ocr_email)):
            if v is not None and v != "":
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        params.append(card_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE card_queue SET {', '.join(sets)} WHERE id=?",
                params,
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Merch
    # ------------------------------------------------------------------
    def create_merch_item(self, fair_id: int, name: str,
                          category: str = "") -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO merch_items (fair_id, name, category, "
                "created_at) VALUES (?,?,?,?)",
                (fair_id, name, category, _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_merch_items(self, fair_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM merch_items WHERE fair_id=? ORDER BY name",
            (fair_id,),
        ).fetchall())

    def add_merch_count(self, item_id: int, fair_id: int,
                        counted_stock: int,
                        fair_day_id: Optional[int] = None,
                        employee_id: Optional[int] = None,
                        note: str = "") -> int:
        with self._lock:
            prev = self.conn.execute(
                "SELECT counted_stock FROM merch_counts WHERE item_id=? "
                "ORDER BY timestamp DESC, id DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            prev_stock = prev["counted_stock"] if prev else None
            issued = 0
            if prev_stock is not None:
                issued = max(0, prev_stock - counted_stock)
            cur = self.conn.execute(
                "INSERT INTO merch_counts "
                "(item_id, fair_id, fair_day_id, counted_stock, "
                "previous_stock, issued_since_previous, timestamp, "
                "employee_id, note) VALUES (?,?,?,?,?,?,?,?,?)",
                (item_id, fair_id, fair_day_id, counted_stock, prev_stock,
                 issued, _now(), employee_id, note),
            )
            self.conn.commit()
            return cur.lastrowid

    def merch_summary(self, fair_id: int) -> list[dict]:
        items = self.list_merch_items(fair_id)
        result = []
        for item in items:
            rows = self.conn.execute(
                "SELECT counted_stock, issued_since_previous "
                "FROM merch_counts WHERE item_id=? "
                "ORDER BY timestamp DESC, id DESC",
                (item["id"],),
            ).fetchall()
            current = rows[0]["counted_stock"] if rows else 0
            cumulative = sum(r["issued_since_previous"] for r in rows)
            result.append({
                "id": item["id"],
                "name": item["name"],
                "category": item["category"],
                "current_stock": current,
                "cumulative_issued": cumulative,
            })
        return result

    def merch_history(self, item_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM merch_counts WHERE item_id=? "
            "ORDER BY timestamp, id",
            (item_id,),
        ).fetchall())

    def merch_series(self, item_id: int) -> list[dict]:
        rows = self.merch_history(item_id)
        result = []
        cum = 0
        for r in rows:
            cum += int(r["issued_since_previous"] or 0)
            result.append({
                "timestamp": r["timestamp"],
                "counted_stock": r["counted_stock"],
                "cumulative": cum,
            })
        return result

    # ------------------------------------------------------------------
    # Aufgaben / Checklisten
    # ------------------------------------------------------------------
    def create_task(self, title: str, fair_id: Optional[int] = None,
                    contact_id: Optional[int] = None,
                    company_id: Optional[int] = None,
                    description: str = "", due_date: Optional[str] = None,
                    priority: str = "normal") -> int:
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO follow_up_tasks "
                "(fair_id, contact_id, company_id, title, description, "
                "due_date, priority, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fair_id, contact_id, company_id, title, description,
                 due_date, priority, "open", now, now),
            )
            task_id = cur.lastrowid
            if contact_id:
                self.conn.execute(
                    "INSERT INTO contact_events "
                    "(contact_id, event_type, details, created_at) "
                    "VALUES (?,?,?,?)",
                    (contact_id, "task_created", title, now),
                )
            self.conn.commit()
            return task_id

    def list_tasks(self, fair_id: Optional[int] = None,
                   contact_id: Optional[int] = None) -> list[dict]:
        sql = "SELECT * FROM follow_up_tasks WHERE 1=1"
        params = []
        if fair_id:
            sql += " AND fair_id=?"
            params.append(fair_id)
        if contact_id:
            sql += " AND contact_id=?"
            params.append(contact_id)
        sql += " ORDER BY status, due_date, id"
        return _rows_to_dicts(self.conn.execute(sql, params).fetchall())

    def update_task(self, task_id: int, status: Optional[str] = None,
                    **kw):
        allowed = {"title", "description", "due_date", "priority",
                   "status", "completed_at"}
        sets, params = [], []
        if status:
            kw["status"] = status
            if status == "done":
                kw["completed_at"] = _now()
            else:
                kw["completed_at"] = None
        for k, v in kw.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(_now())
        params.append(task_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE follow_up_tasks SET {', '.join(sets)} WHERE id=?",
                params,
            )
            if status == "done":
                task = self.conn.execute(
                    "SELECT contact_id, title FROM follow_up_tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
                if task and task["contact_id"]:
                    self.conn.execute(
                        "INSERT INTO contact_events "
                        "(contact_id, event_type, details, created_at) "
                        "VALUES (?,?,?,?)",
                        (task["contact_id"], "task_done", task["title"],
                         _now()),
                    )
            self.conn.commit()

    def create_checklist_item(self, fair_id: int, title: str,
                              phase: str = "preparation") -> int:
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO fair_checklist_items "
                "(fair_id, phase, title, done, created_at, updated_at) "
                "VALUES (?,?,?,0,?,?)",
                (fair_id, phase, title, now, now),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_checklist_items(self, fair_id: int) -> list[dict]:
        return _rows_to_dicts(self.conn.execute(
            "SELECT * FROM fair_checklist_items WHERE fair_id=? "
            "ORDER BY done, phase, id",
            (fair_id,),
        ).fetchall())

    def set_checklist_done(self, item_id: int, done: bool):
        with self._lock:
            self.conn.execute(
                "UPDATE fair_checklist_items SET done=?, updated_at=? "
                "WHERE id=?", (int(done), _now(), item_id),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Dashboard und Statistiken
    # ------------------------------------------------------------------
    def dashboard_stats(self, fair_id: int,
                        day_id: Optional[int] = None) -> dict:
        stats: dict = {}
        sql = "SELECT COUNT(*) FROM contacts WHERE fair_id=?"
        params = [fair_id]
        if day_id:
            sql += " AND fair_day_id=?"
            params.append(day_id)
        stats["total_today"] = self.conn.execute(sql, params).fetchone()[0]

        stats["total_fair"] = self.conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE fair_id=?", (fair_id,)
        ).fetchone()[0]

        stats["companies"] = self.conn.execute(
            "SELECT COUNT(DISTINCT company) FROM contacts "
            "WHERE fair_id=? AND company IS NOT NULL AND company<>''",
            (fair_id,),
        ).fetchone()[0]

        stats["pending_cards"] = self.conn.execute(
            "SELECT COUNT(*) FROM card_queue "
            "WHERE fair_id=? AND status<>'processed'", (fair_id,)
        ).fetchone()[0]

        stats["tasks_open"] = self.conn.execute(
            "SELECT COUNT(*) FROM follow_up_tasks "
            "WHERE fair_id=? AND status IN ('open','in_progress')",
            (fair_id,),
        ).fetchone()[0]

        today = datetime.now().date().isoformat()
        stats["tasks_overdue"] = self.conn.execute(
            "SELECT COUNT(*) FROM follow_up_tasks "
            "WHERE fair_id=? AND status IN ('open','in_progress') "
            "AND due_date IS NOT NULL AND due_date < ?",
            (fair_id, today),
        ).fetchone()[0]

        by_status = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM contacts WHERE fair_id=? "
            "GROUP BY status", (fair_id,),
        ).fetchall()
        stats["by_status"] = {r["status"]: r["n"] for r in by_status}

        att = self.current_attendance(fair_id)
        stats["present"] = [
            eid for eid, v in att.items() if v["event_type"] == "enter"]
        stats["absent"] = [
            eid for eid, v in att.items() if v["event_type"] == "leave"]
        stats["merch"] = self.merch_summary(fair_id)
        return stats

    def contacts_by_day(self, fair_id: int) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n "
            "FROM contacts WHERE fair_id=? GROUP BY day ORDER BY day",
            (fair_id,),
        ).fetchall()
        return [(r["day"], r["n"]) for r in rows]

    def contacts_by_hour(self, fair_id: int) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT CAST(substr(created_at, 12, 2) AS INTEGER) AS hour, "
            "COUNT(*) AS n FROM contacts WHERE fair_id=? "
            "GROUP BY hour ORDER BY hour", (fair_id,),
        ).fetchall()
        return [(r["hour"], r["n"]) for r in rows]

    def cumulative_contacts_timeline(self, fair_id: int) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT created_at FROM contacts WHERE fair_id=? "
            "ORDER BY created_at, id", (fair_id,),
        ).fetchall()
        return [(r["created_at"], i + 1) for i, r in enumerate(rows)]

    def status_timeline(self, fair_id: int) -> dict[str, list[tuple]]:
        rows = self.conn.execute(
            "SELECT created_at, status FROM contacts WHERE fair_id=? "
            "ORDER BY created_at, id", (fair_id,),
        ).fetchall()
        result: dict[str, list[tuple]] = {}
        counters: dict[str, int] = {}
        for r in rows:
            counters[r["status"]] = counters.get(r["status"], 0) + 1
            result.setdefault(r["status"], []).append(
                (r["created_at"], counters[r["status"]]))
        return result

    def unique_companies_timeline(self, fair_id: int) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT created_at, company FROM contacts "
            "WHERE fair_id=? AND company IS NOT NULL AND company<>'' "
            "ORDER BY created_at, id", (fair_id,),
        ).fetchall()
        seen = set()
        result = []
        for r in rows:
            name = r["company"]
            if name not in seen:
                seen.add(name)
                result.append((r["created_at"], name))
        return result

    # ------------------------------------------------------------------
    # Duplikate und Merge (kompatibel zu core.duplicates und Tests)
    # ------------------------------------------------------------------
    def find_duplicate_candidates(self, contact_id: int,
                                  min_score: float = 0.7) -> list[dict]:
        """Liefert Kandidaten, die über E-Mail/Telefon übereinstimmen."""
        from core.duplicates import find_similar_contacts
        contact = self.get_contact(contact_id)
        if not contact:
            return []
        matches = find_similar_contacts(self, contact)
        filtered = []
        for other, reasons, score in matches:
            if reasons & {"email", "phone", "phone_suffix",
                          "email_local_part"}:
                filtered.append({
                    "contact": other,
                    "reasons": reasons,
                    "score": score,
                })
        return filtered

    def merge_contacts(self, keep_id: int, duplicate_id: int) -> dict:
        from core.duplicates import merge_contacts_keep_richer
        return merge_contacts_keep_richer(self, keep_id, duplicate_id)

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------
    def score_contact(self, contact_id: int) -> dict:
        contact = self.get_contact(contact_id)
        if not contact:
            return {"score": 0, "reasons": []}
        score = 10
        reasons = []
        notes = (contact.get("notes") or "").strip()
        if notes:
            score += 10
        if contact.get("status") == "Interessiert":
            score += 5
        tasks = self.list_tasks(contact_id=contact_id)
        if any(t["status"] in ("open", "in_progress") for t in tasks):
            score += 20
            reasons.append("offener nächster Schritt")
        if any(k in notes.lower() for k in ("angebot", "auftrag", "kauf")):
            score += 10
        return {"score": score, "reasons": reasons}