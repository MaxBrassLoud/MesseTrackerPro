# database/db.py
"""SQLite-Datenbankzugriff für Messe Tracker Pro.

Threading: Die Verbindung wird mit ``check_same_thread=False`` geöffnet,
weil sowohl der Qt-UI-Thread als auch der Flask-Webserver darauf zugreifen.
Alle schreibenden und lesenden Operationen werden über ``self._lock``
(RLock) serialisiert.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime

from database.schema import SCHEMA_SQL, SCHEMA_VERSION


class Database:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------
    # Basics
    # ------------------------------------------------------------------
    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def close(self):
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass

    def init_db(self):
        with self._lock:
            self.conn.executescript(SCHEMA_SQL)
            self.conn.commit()
            self._migrate()
            self._seed_defaults()
            self.conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) "
                "VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))
            self.conn.commit()

    def _migrate(self):
        # contacts.company_id
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(contacts)").fetchall()}
        if "company_id" not in cols:
            self.conn.execute(
                "ALTER TABLE contacts ADD COLUMN company_id INTEGER "
                "REFERENCES companies(id) ON DELETE SET NULL")

        # companies.address
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(companies)").fetchall()}
        if "address" not in cols:
            self.conn.execute(
                "ALTER TABLE companies ADD COLUMN address TEXT")

        # employees.user_id
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(employees)").fetchall()}
        if "user_id" not in cols:
            self.conn.execute(
                "ALTER TABLE employees ADD COLUMN user_id INTEGER "
                "REFERENCES users(id) ON DELETE SET NULL")
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_user_id "
                "ON employees(user_id) WHERE user_id IS NOT NULL")

        self.conn.commit()

    def _seed_defaults(self):
        now = self._now()

        # System-Rollen
        self.conn.execute(
            "INSERT OR IGNORE INTO roles "
            "(id, name, description, is_system, created_at) VALUES "
            "(1, 'Administrator', 'Vollzugriff', 1, ?)", (now,))
        self.conn.execute(
            "INSERT OR IGNORE INTO roles "
            "(id, name, description, is_system, created_at) VALUES "
            "(2, 'Benutzer', 'Standard-Benutzer', 1, ?)", (now,))

        # Admin-Rechte
        try:
            from core.permissions import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS
            for perm, _label in ALL_PERMISSIONS:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions "
                    "(role_id, permission) VALUES (1, ?)", (perm,))
            for perm in DEFAULT_USER_PERMISSIONS:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions "
                    "(role_id, permission) VALUES (2, ?)", (perm,))
        except Exception:
            pass

        # Standard-Status
        for i, name in enumerate(
                ("Interessiert", "Anfrage", "Auftrag erteilt")):
            self.conn.execute(
                "INSERT OR IGNORE INTO contact_statuses "
                "(name, color, sort_order, active, created_at) "
                "VALUES (?, '#FF8200', ?, 1, ?)",
                (name, (i + 1) * 10, now))

        # Web-Secret
        if not self.conn.execute(
                "SELECT 1 FROM app_meta WHERE key='web_secret_key'").fetchone():
            self.conn.execute(
                "INSERT INTO app_meta (key, value) VALUES "
                "('web_secret_key', ?)", (secrets.token_hex(32),))

        self.conn.commit()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def get_setting(self, key, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
                (key, "" if value is None else str(value)))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Messen / Messetage
    # ------------------------------------------------------------------
    def list_fairs(self, include_archived=False):
        query = "SELECT * FROM fairs"
        if not include_archived:
            query += " WHERE archived=0"
        query += " ORDER BY name"
        with self._lock:
            rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def create_fair(self, name, location=""):
        now = self._now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO fairs (name, location, archived, created_at) "
                "VALUES (?, ?, 0, ?)", (name, location or None, now))
            fid = cur.lastrowid
            self.conn.commit()
        return fid

    def update_fair(self, fair_id, **fields):
        allowed = {"name", "location", "start_date", "end_date", "archived"}
        updates, values = [], []
        for k, v in fields.items():
            if k in allowed:
                updates.append(f"{k}=?")
                values.append(v)
        if not updates:
            return
        values.append(fair_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE fairs SET {', '.join(updates)} WHERE id=?", values)
            self.conn.commit()

    def get_active_fair_day(self):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM fair_days WHERE is_active=1 "
                "ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def start_fair_day(self, fair_id):
        with self._lock:
            if self.conn.execute(
                    "SELECT 1 FROM fair_days WHERE is_active=1").fetchone():
                raise ValueError("Es läuft bereits ein Messetag.")
            now = self._now()
            today = datetime.now().date().isoformat()
            cur = self.conn.execute(
                "INSERT INTO fair_days (fair_id, day_date, started_at, "
                "is_active) VALUES (?, ?, ?, 1)", (fair_id, today, now))
            day_id = cur.lastrowid
            self.conn.commit()
        return day_id

    def end_fair_day(self, day_id):
        with self._lock:
            self.conn.execute(
                "UPDATE fair_days SET ended_at=?, is_active=0 WHERE id=?",
                (self._now(), day_id))
            self.conn.commit()

    def list_fair_days(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM fair_days WHERE fair_id=? "
                "ORDER BY day_date DESC", (fair_id,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Mitarbeiter (employees)
    # ------------------------------------------------------------------
    def list_employees(self, active_only=False):
        query = "SELECT * FROM employees"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY name"
        with self._lock:
            rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def create_employee(self, name, email=""):
        token = secrets.token_urlsafe(32)
        now = self._now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO employees (name, email, active, token, "
                "created_at) VALUES (?, ?, 1, ?, ?)",
                (name, email or None, token, now))
            emp_id = cur.lastrowid
            self.conn.commit()
        return emp_id, token

    def update_employee(self, emp_id, **fields):
        allowed = {"name", "email", "phone", "active"}
        updates, values = [], []
        for k, v in fields.items():
            if k in allowed:
                updates.append(f"{k}=?")
                values.append(v)
        if not updates:
            return
        values.append(emp_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE employees SET {', '.join(updates)} WHERE id=?",
                values)
            self.conn.commit()

    def regenerate_employee_token(self, emp_id):
        new_token = secrets.token_urlsafe(32)
        with self._lock:
            self.conn.execute(
                "UPDATE employees SET token=? WHERE id=?",
                (new_token, emp_id))
            self.conn.commit()
        return new_token

    def get_employee_by_token(self, token):
        if not token:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM employees WHERE token=?", (token,)
            ).fetchone()
        return dict(row) if row else None

    def get_employee_by_user_id(self, user_id):
        if user_id is None:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM employees WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def ensure_employee_for_user(self, user_id, name, email=""):
        emp = self.get_employee_by_user_id(user_id)
        if emp:
            return emp["id"]
        token = secrets.token_urlsafe(32)
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO employees (name, email, active, token, "
                "user_id, created_at) VALUES (?, ?, 1, ?, ?, ?)",
                (name, email or None, token, user_id, self._now()))
            emp_id = cur.lastrowid
            self.conn.commit()
        return emp_id

    # ------------------------------------------------------------------
    # Kundenstatus
    # ------------------------------------------------------------------
    def list_statuses(self, active_only=True):
        query = "SELECT * FROM contact_statuses"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY sort_order, name"
        with self._lock:
            rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def get_status(self, status_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM contact_statuses WHERE id=?", (status_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_status(self, name, color="#FF8200", sort_order=100):
        with self._lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO contact_statuses "
                    "(name, color, sort_order, active, created_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (name, color, sort_order, self._now()))
                status_id = cur.lastrowid
                self.conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Status „{name}“ existiert bereits.")
        return status_id

    def update_status(self, status_id, **fields):
        with self._lock:
            row = self.conn.execute(
                "SELECT name FROM contact_statuses WHERE id=?",
                (status_id,)).fetchone()
            if not row:
                return
            old_name = row["name"]
            new_name = fields.get("name")
            if new_name and new_name != old_name:
                try:
                    self.conn.execute(
                        "UPDATE contacts SET status=? WHERE status=?",
                        (new_name, old_name))
                except sqlite3.IntegrityError:
                    raise ValueError(
                        f"Status „{new_name}“ ist bereits vergeben.")
            allowed = {"name", "color", "sort_order", "active"}
            updates, values = [], []
            for k, v in fields.items():
                if k in allowed:
                    updates.append(f"{k}=?")
                    values.append(v)
            if updates:
                values.append(status_id)
                self.conn.execute(
                    f"UPDATE contact_statuses SET {', '.join(updates)} "
                    f"WHERE id=?", values)
            self.conn.commit()

    def status_usage_count(self, status_id):
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE status=("
                "SELECT name FROM contact_statuses WHERE id=?)",
                (status_id,)).fetchone()[0]

    def delete_status(self, status_id):
        with self._lock:
            in_use = self.conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE status=("
                "SELECT name FROM contact_statuses WHERE id=?)",
                (status_id,)).fetchone()[0]
            if in_use > 0:
                return in_use, f"Status wird von {in_use} Kontakt(en) verwendet."
            self.conn.execute(
                "DELETE FROM contact_statuses WHERE id=?", (status_id,))
            self.conn.commit()
        return 0, None

    # ------------------------------------------------------------------
    # Firmen (companies)
    # ------------------------------------------------------------------
    def _ensure_company(self, name):
        name = (name or "").strip()
        if not name:
            return None
        now = self._now()
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM companies WHERE name=?", (name,)).fetchone()
            if row:
                return row["id"]
            cur = self.conn.execute(
                "INSERT INTO companies (name, created_at, updated_at) "
                "VALUES (?, ?, ?)", (name, now, now))
            company_id = cur.lastrowid
            self.conn.commit()
        return company_id

    def get_company(self, company_id):
        if not company_id:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM companies WHERE id=?", (company_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_company_address(self, company_id):
        if not company_id:
            return ""
        with self._lock:
            row = self.conn.execute(
                "SELECT address FROM companies WHERE id=?", (company_id,)
            ).fetchone()
        if not row:
            return ""
        return row["address"] or ""

    def set_company_address(self, company_id, address):
        if not company_id:
            return
        with self._lock:
            self.conn.execute(
                "UPDATE companies SET address=?, updated_at=? WHERE id=?",
                (address or None, self._now(), company_id))
            self.conn.commit()

    def company_contacts(self, company_id):
        if not company_id:
            return []
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM contacts WHERE company_id=? ORDER BY name",
                (company_id,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Kontakte
    # ------------------------------------------------------------------
    def create_contact(self, fair_id, source, fair_day_id=None,
                       employee_id=None, name="", company="", position="",
                       phone="", email="", status="Interessiert", notes="",
                       card_image_path=None, processing_status="ok",
                       external_id=None):
        name = (name or "").strip()
        company = (company or "").strip()
        email = (email or "").strip()
        phone = (phone or "").strip()
        position = (position or "").strip()
        notes = (notes or "").strip()

        with self._lock:
            if external_id:
                existing = self.conn.execute(
                    "SELECT id FROM contacts WHERE external_id=?",
                    (external_id,)).fetchone()
                if existing:
                    return existing["id"]

            company_id = self._ensure_company(company) if company else None
            now = self._now()
            cur = self.conn.execute(
                "INSERT INTO contacts (fair_id, fair_day_id, employee_id, "
                "name, company, company_id, position, phone, email, status, "
                "notes, source, card_image_path, processing_status, "
                "external_id, created_at, updated_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fair_id, fair_day_id, employee_id,
                 name or None, company or None, company_id,
                 position or None, phone or None, email or None,
                 status, notes or None, source,
                 card_image_path, processing_status, external_id,
                 now, now))
            contact_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO contact_events "
                "(contact_id, event_type, details, created_at) "
                "VALUES (?, 'created', NULL, ?)", (contact_id, now))
            self.conn.commit()
        return contact_id

    def get_contact(self, contact_id):
        if not contact_id:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM contacts WHERE id=?", (contact_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_contact(self, contact_id, **fields):
        allowed = {"name", "company", "position", "phone", "email", "status",
                   "notes", "card_image_path", "source"}
        updates, values = [], []
        for k, v in fields.items():
            if k in allowed:
                updates.append(f"{k}=?")
                values.append(v)

        if "company" in fields:
            company_name = (fields.get("company") or "").strip()
            company_id = self._ensure_company(company_name) \
                if company_name else None
            updates.append("company_id=?")
            values.append(company_id)

        if not updates:
            return
        updates.append("updated_at=?")
        values.append(self._now())
        values.append(contact_id)

        with self._lock:
            self.conn.execute(
                f"UPDATE contacts SET {', '.join(updates)} WHERE id=?",
                values)
            self.conn.commit()

    def delete_contact(self, contact_id):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contacts WHERE id=?", (contact_id,))
            self.conn.commit()

    def search_contacts(self, fair_id=None, status=None, employee_id=None,
                        text=""):
        query = "SELECT * FROM contacts WHERE 1=1"
        params = []
        if fair_id is not None:
            query += " AND fair_id=?"
            params.append(fair_id)
        if status:
            query += " AND status=?"
            params.append(status)
        if employee_id is not None:
            query += " AND employee_id=?"
            params.append(employee_id)
        if text:
            query += (" AND (name LIKE ? OR company LIKE ? OR email LIKE ?)")
            needle = f"%{text}%"
            params.extend([needle, needle, needle])
        query += " ORDER BY created_at DESC, id DESC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def find_duplicate_candidates(self, contact_id):
        contact = self.get_contact(contact_id)
        if not contact:
            return []
        email = (contact.get("email") or "").strip().lower()
        phone = (contact.get("phone") or "").strip()
        fair_id = contact.get("fair_id")

        conds, params = [], []
        if email:
            conds.append("LOWER(email)=?")
            params.append(email)
        if phone:
            conds.append("phone=?")
            params.append(phone)
        if not conds:
            return []

        query = "SELECT * FROM contacts WHERE id != ?"
        base_params = [contact_id]
        if fair_id is not None:
            query += " AND fair_id=?"
            base_params.append(fair_id)
        query += " AND (" + " OR ".join(conds) + ")"
        with self._lock:
            rows = self.conn.execute(
                query, base_params + params).fetchall()

        result = []
        for r in rows:
            reasons = []
            if email and (r["email"] or "").strip().lower() == email:
                reasons.append("email")
            if phone and (r["phone"] or "").strip() == phone:
                reasons.append("phone")
            result.append({"contact": dict(r), "reasons": reasons})
        return result

    def merge_contacts(self, keep_id, duplicate_id):
        if keep_id == duplicate_id:
            return
        with self._lock:
            keep = self.conn.execute(
                "SELECT * FROM contacts WHERE id=?", (keep_id,)).fetchone()
            dup = self.conn.execute(
                "SELECT * FROM contacts WHERE id=?", (duplicate_id,)
            ).fetchone()
            if not keep or not dup:
                return

            self.conn.execute(
                "UPDATE follow_up_tasks SET contact_id=? WHERE contact_id=?",
                (keep_id, duplicate_id))
            self.conn.execute(
                "UPDATE contact_addresses SET contact_id=? WHERE contact_id=?",
                (keep_id, duplicate_id))
            self.conn.execute(
                "UPDATE contact_channels SET contact_id=? WHERE contact_id=?",
                (keep_id, duplicate_id))

            for col in ("name", "company", "position", "phone", "email",
                        "notes", "card_image_path"):
                if not keep[col] and dup[col]:
                    self.conn.execute(
                        f"UPDATE contacts SET {col}=? WHERE id=?",
                        (dup[col], keep_id))

            self.conn.execute(
                "INSERT INTO contact_events (contact_id, event_type, "
                "details, created_at) VALUES (?, 'merged', ?, ?)",
                (keep_id, f"Duplikat #{duplicate_id} zusammengeführt",
                 self._now()))
            self.conn.execute(
                "DELETE FROM contacts WHERE id=?", (duplicate_id,))
            self.conn.execute(
                "UPDATE contacts SET updated_at=? WHERE id=?",
                (self._now(), keep_id))
            self.conn.commit()

    def score_contact(self, contact_id):
        contact = self.get_contact(contact_id)
        if not contact:
            return {"score": 0, "reasons": []}

        score = 0
        reasons = []
        if contact.get("status"):
            score += 15
            reasons.append("Status erfasst")
        if contact.get("notes"):
            score += 15
            reasons.append("Notizen vorhanden")
        if contact.get("email"):
            score += 10
            reasons.append("E-Mail vorhanden")
        if contact.get("phone"):
            score += 10
            reasons.append("Telefon vorhanden")
        if contact.get("company_id"):
            score += 10
            reasons.append("Firma zugeordnet")

        with self._lock:
            open_tasks = self.conn.execute(
                "SELECT COUNT(*) FROM follow_up_tasks WHERE contact_id=? "
                "AND status IN ('open','in_progress')",
                (contact_id,)).fetchone()[0]
        if open_tasks > 0:
            score += 25
            reasons.append("offener nächster Schritt")

        return {"score": score, "reasons": reasons}

    # ------------------------------------------------------------------
    # Kontakt-Adressen / Kontaktwege
    # ------------------------------------------------------------------
    def list_contact_addresses(self, contact_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM contact_addresses WHERE contact_id=? "
                "ORDER BY is_primary DESC, id", (contact_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_contact_address(self, contact_id, street="", postal_code="",
                             city="", country="", label="Geschäftlich",
                             is_primary=False):
        with self._lock:
            self.conn.execute(
                "INSERT INTO contact_addresses (contact_id, label, street, "
                "postal_code, city, country, is_primary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (contact_id, label, street or None, postal_code or None,
                 city or None, country or None, 1 if is_primary else 0))
            self.conn.commit()

    def delete_contact_address(self, address_id):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contact_addresses WHERE id=?", (address_id,))
            self.conn.commit()

    def list_contact_channels(self, contact_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM contact_channels WHERE contact_id=? "
                "ORDER BY is_primary DESC, id", (contact_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_contact_channel(self, contact_id, channel_type, value,
                             label="", is_primary=False):
        if channel_type not in ("email", "phone", "website"):
            raise ValueError("Ungültiger Kontaktweg-Typ.")
        with self._lock:
            self.conn.execute(
                "INSERT INTO contact_channels (contact_id, channel_type, "
                "value, label, is_primary) VALUES (?, ?, ?, ?, ?)",
                (contact_id, channel_type, value, label or None,
                 1 if is_primary else 0))
            self.conn.commit()

    def delete_contact_channel(self, channel_id):
        with self._lock:
            self.conn.execute(
                "DELETE FROM contact_channels WHERE id=?", (channel_id,))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Kontakt-Historie
    # ------------------------------------------------------------------
    def contact_history(self, contact_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM contact_events WHERE contact_id=? "
                "ORDER BY created_at DESC, id DESC", (contact_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Visitenkarten-Warteschlange
    # ------------------------------------------------------------------
    def list_card_queue(self, status=None):
        if status:
            query = "SELECT * FROM card_queue WHERE status=?"
            params = (status,)
        else:
            query = ("SELECT * FROM card_queue WHERE status IN "
                     "('pending', 'needs_review', 'orphaned')")
            params = ()
        query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_card(self, card_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM card_queue WHERE id=?", (card_id,)
            ).fetchone()
        return dict(row) if row else None

    def enqueue_card(self, fair_id, image_path, fair_day_id=None,
                     employee_id=None, original_filename="", external_id=None):
        with self._lock:
            if external_id:
                existing = self.conn.execute(
                    "SELECT * FROM card_queue WHERE external_id=?",
                    (external_id,)).fetchone()
                if existing:
                    return dict(existing), False
            cur = self.conn.execute(
                "INSERT INTO card_queue (fair_id, fair_day_id, employee_id, "
                "image_path, original_filename, status, external_id, "
                "created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (fair_id, fair_day_id, employee_id, image_path,
                 original_filename or None, external_id, self._now()))
            card_id = cur.lastrowid
            self.conn.commit()
        return self.get_card(card_id), True

    def create_contact_with_card(self, fair_id, source, employee_id,
                                  fair_day_id, name, company, position,
                                  phone, email, status, notes, image_path,
                                  original_filename="", external_id=None):
        """Erstellt Kontakt UND card_queue-Eintrag (bereits processed)."""
        contact_id = self.create_contact(
            fair_id=fair_id, source=source, fair_day_id=fair_day_id,
            employee_id=employee_id, name=name, company=company,
            position=position, phone=phone, email=email, status=status,
            notes=notes, card_image_path=image_path,
            processing_status="ok", external_id=external_id)
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO card_queue (fair_id, fair_day_id, employee_id, "
                "image_path, original_filename, status, contact_id, "
                "external_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'processed', ?, ?, ?)",
                (fair_id, fair_day_id, employee_id, image_path,
                 original_filename or None, contact_id, external_id,
                 self._now()))
            card_id = cur.lastrowid
            self.conn.commit()
        return contact_id, self.get_card(card_id), True

    def update_card_ocr(self, card_id, status=None, ocr_name="",
                         ocr_company="", ocr_position="", ocr_phone="",
                         ocr_email=""):
        with self._lock:
            updates = ["ocr_name=?", "ocr_company=?", "ocr_position=?",
                       "ocr_phone=?", "ocr_email=?"]
            values = [ocr_name or None, ocr_company or None,
                      ocr_position or None, ocr_phone or None,
                      ocr_email or None]
            if status:
                updates.append("status=?")
                values.append(status)
            values.append(card_id)
            self.conn.execute(
                f"UPDATE card_queue SET {', '.join(updates)} WHERE id=?",
                values)
            self.conn.commit()

    # ------------------------------------------------------------------
    # Anwesenheit
    # ------------------------------------------------------------------
    def add_attendance(self, employee_id, fair_id, event_type, source,
                       fair_day_id=None):
        if event_type not in ("enter", "leave"):
            raise ValueError("event_type muss 'enter' oder 'leave' sein.")
        with self._lock:
            last = self.conn.execute(
                "SELECT id, event_type FROM attendance_events "
                "WHERE employee_id=? AND fair_id=? "
                "ORDER BY timestamp DESC, id DESC LIMIT 1",
                (employee_id, fair_id)).fetchone()
            if last and last["event_type"] == event_type:
                return last["id"], False
            cur = self.conn.execute(
                "INSERT INTO attendance_events (employee_id, fair_id, "
                "fair_day_id, event_type, source, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (employee_id, fair_id, fair_day_id, event_type, source,
                 self._now()))
            att_id = cur.lastrowid
            self.conn.commit()
        return att_id, True

    def current_attendance(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT employee_id, event_type, timestamp "
                "FROM attendance_events WHERE fair_id=? "
                "AND id IN (SELECT MAX(id) FROM attendance_events "
                "           WHERE fair_id=? GROUP BY employee_id)",
                (fair_id, fair_id)).fetchall()
        return {r["employee_id"]: {
            "event_type": r["event_type"],
            "timestamp": r["timestamp"],
        } for r in rows}

    def attendance_intervals(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT employee_id, event_type, timestamp "
                "FROM attendance_events WHERE fair_id=? "
                "ORDER BY employee_id, timestamp, id",
                (fair_id,)).fetchall()

        intervals = {}
        open_entries = {}
        now_iso = self._now()
        for r in rows:
            emp = r["employee_id"]
            if r["event_type"] == "enter":
                open_entries[emp] = r["timestamp"]
            elif r["event_type"] == "leave":
                start = open_entries.pop(emp, None)
                if start:
                    intervals.setdefault(emp, []).append(
                        (start, r["timestamp"]))
        for emp, start in open_entries.items():
            intervals.setdefault(emp, []).append((start, now_iso))
        return intervals

    # ------------------------------------------------------------------
    # Merchandise
    # ------------------------------------------------------------------
    def create_merch_item(self, fair_id, name, category=""):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO merch_items (fair_id, name, category, "
                "created_at) VALUES (?, ?, ?, ?)",
                (fair_id, name, category or None, self._now()))
            item_id = cur.lastrowid
            self.conn.commit()
        return item_id

    def list_merch_items(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM merch_items WHERE fair_id=? ORDER BY name",
                (fair_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_merch_count(self, item_id, fair_id, counted_stock,
                        fair_day_id=None, note="", employee_id=None):
        with self._lock:
            prev = self.conn.execute(
                "SELECT counted_stock FROM merch_counts WHERE item_id=? "
                "ORDER BY timestamp DESC, id DESC LIMIT 1",
                (item_id,)).fetchone()
            prev_stock = prev["counted_stock"] if prev else None
            issued = max(0, prev_stock - counted_stock) \
                if prev_stock is not None else 0

            self.conn.execute(
                "INSERT INTO merch_counts (item_id, fair_id, fair_day_id, "
                "counted_stock, previous_stock, issued_since_previous, "
                "timestamp, employee_id, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, fair_id, fair_day_id, counted_stock, prev_stock,
                 issued, self._now(), employee_id, note or None))
            self.conn.commit()

    def merch_summary(self, fair_id):
        with self._lock:
            items = self.conn.execute(
                "SELECT * FROM merch_items WHERE fair_id=? ORDER BY name",
                (fair_id,)).fetchall()
            result = []
            for item in items:
                last = self.conn.execute(
                    "SELECT counted_stock FROM merch_counts WHERE item_id=? "
                    "ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (item["id"],)).fetchone()
                cumulative = self.conn.execute(
                    "SELECT COALESCE(SUM(issued_since_previous), 0) "
                    "FROM merch_counts WHERE item_id=?",
                    (item["id"],)).fetchone()[0]
                result.append({
                    "id": item["id"],
                    "name": item["name"],
                    "category": item["category"],
                    "current_stock": last["counted_stock"] if last else 0,
                    "cumulative_issued": cumulative,
                })
        return result

    def merch_history(self, item_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM merch_counts WHERE item_id=? "
                "ORDER BY timestamp, id", (item_id,)).fetchall()
        return [dict(r) for r in rows]

    def merch_series(self, item_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT timestamp, counted_stock, issued_since_previous "
                "FROM merch_counts WHERE item_id=? "
                "ORDER BY timestamp, id", (item_id,)).fetchall()
        result = []
        cumulative = 0
        for r in rows:
            cumulative += r["issued_since_previous"]
            result.append({
                "timestamp": r["timestamp"],
                "counted_stock": r["counted_stock"],
                "cumulative": cumulative,
            })
        return result

    # ------------------------------------------------------------------
    # Aufgaben / Nachfassaktionen
    # ------------------------------------------------------------------
    def list_tasks(self, fair_id=None, contact_id=None):
        query = "SELECT * FROM follow_up_tasks WHERE 1=1"
        params = []
        if fair_id is not None:
            query += " AND fair_id=?"
            params.append(fair_id)
        if contact_id is not None:
            query += " AND contact_id=?"
            params.append(contact_id)
        query += " ORDER BY (status='done') ASC, due_date IS NULL, " \
                 "due_date, id"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def create_task(self, title, fair_id=None, contact_id=None,
                    company_id=None, description="", due_date=None,
                    priority="normal", assigned_user_id=None):
        now = self._now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO follow_up_tasks (fair_id, contact_id, "
                "company_id, title, description, due_date, priority, "
                "status, assigned_user_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (fair_id, contact_id, company_id, title,
                 description or None, due_date, priority,
                 assigned_user_id, now, now))
            task_id = cur.lastrowid
            if contact_id:
                self.conn.execute(
                    "INSERT INTO contact_events (contact_id, event_type, "
                    "details, created_at) VALUES (?, 'task_created', ?, ?)",
                    (contact_id, title, now))
            self.conn.commit()
        return task_id

    def update_task(self, task_id, status=None, **fields):
        with self._lock:
            updates, values = [], []
            if status:
                updates.append("status=?")
                values.append(status)
                if status == "done":
                    updates.append("completed_at=?")
                    values.append(self._now())
                else:
                    updates.append("completed_at=NULL")
            for k in ("title", "description", "due_date", "priority"):
                if k in fields:
                    updates.append(f"{k}=?")
                    values.append(fields[k])
            if not updates:
                return
            updates.append("updated_at=?")
            values.append(self._now())
            values.append(task_id)
            self.conn.execute(
                f"UPDATE follow_up_tasks SET {', '.join(updates)} "
                f"WHERE id=?", values)
            if status == "done":
                row = self.conn.execute(
                    "SELECT contact_id, title FROM follow_up_tasks "
                    "WHERE id=?", (task_id,)).fetchone()
                if row and row["contact_id"]:
                    self.conn.execute(
                        "INSERT INTO contact_events (contact_id, "
                        "event_type, details, created_at) "
                        "VALUES (?, 'task_done', ?, ?)",
                        (row["contact_id"], row["title"], self._now()))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Checklisten
    # ------------------------------------------------------------------
    def create_checklist_item(self, fair_id, title, phase="preparation",
                              due_date=None, assigned_user_id=None):
        now = self._now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO fair_checklist_items (fair_id, phase, title, "
                "due_date, assigned_user_id, done, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (fair_id, phase, title, due_date, assigned_user_id,
                 now, now))
            item_id = cur.lastrowid
            self.conn.commit()
        return item_id

    def list_checklist_items(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM fair_checklist_items WHERE fair_id=? "
                "ORDER BY phase, done, title", (fair_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_checklist_done(self, item_id, done):
        with self._lock:
            self.conn.execute(
                "UPDATE fair_checklist_items SET done=?, updated_at=? "
                "WHERE id=?",
                (1 if done else 0, self._now(), item_id))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Dashboard / Auswertungen
    # ------------------------------------------------------------------
    def dashboard_stats(self, fair_id, day_id=None):
        today = datetime.now().date().isoformat()
        result = {
            "total_today": 0,
            "total_fair": 0,
            "companies": 0,
            "pending_cards": 0,
            "present": [],
            "absent": [],
            "tasks_open": 0,
            "tasks_overdue": 0,
            "by_status": {},
            "merch": [],
        }
        with self._lock:
            result["total_fair"] = self.conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE fair_id=?",
                (fair_id,)).fetchone()[0]

            if day_id:
                result["total_today"] = self.conn.execute(
                    "SELECT COUNT(*) FROM contacts WHERE fair_id=? "
                    "AND fair_day_id=?", (fair_id, day_id)).fetchone()[0]
            else:
                result["total_today"] = self.conn.execute(
                    "SELECT COUNT(*) FROM contacts WHERE fair_id=? "
                    "AND substr(created_at, 1, 10)=?",
                    (fair_id, today)).fetchone()[0]

            result["companies"] = self.conn.execute(
                "SELECT COUNT(DISTINCT company_id) FROM contacts "
                "WHERE fair_id=? AND company_id IS NOT NULL",
                (fair_id,)).fetchone()[0]

            result["pending_cards"] = self.conn.execute(
                "SELECT COUNT(*) FROM card_queue WHERE fair_id=? "
                "AND status='pending'", (fair_id,)).fetchone()[0]

            result["tasks_open"] = self.conn.execute(
                "SELECT COUNT(*) FROM follow_up_tasks WHERE fair_id=? "
                "AND status IN ('open','in_progress')",
                (fair_id,)).fetchone()[0]

            result["tasks_overdue"] = self.conn.execute(
                "SELECT COUNT(*) FROM follow_up_tasks WHERE fair_id=? "
                "AND status IN ('open','in_progress') "
                "AND due_date IS NOT NULL AND due_date < ?",
                (fair_id, today)).fetchone()[0]

            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM contacts "
                "WHERE fair_id=? GROUP BY status", (fair_id,)).fetchall()
            for r in rows:
                result["by_status"][r["status"]] = r["n"]

        att = self.current_attendance(fair_id)
        result["present"] = [eid for eid, v in att.items()
                             if v["event_type"] == "enter"]
        result["absent"] = [eid for eid, v in att.items()
                            if v["event_type"] == "leave"]
        result["merch"] = self.merch_summary(fair_id)
        return result

    def contacts_by_day(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n "
                "FROM contacts WHERE fair_id=? GROUP BY day ORDER BY day",
                (fair_id,)).fetchall()
        return [(r["day"], r["n"]) for r in rows]

    def contacts_by_hour(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT CAST(substr(created_at, 12, 2) AS INTEGER) AS hour, "
                "COUNT(*) AS n FROM contacts WHERE fair_id=? "
                "GROUP BY hour ORDER BY hour", (fair_id,)).fetchall()
        return [(r["hour"], r["n"]) for r in rows]

    def cumulative_contacts_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT created_at FROM contacts WHERE fair_id=? "
                "ORDER BY created_at, id", (fair_id,)).fetchall()
        return [(r["created_at"], i + 1) for i, r in enumerate(rows)]

    def status_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT created_at, status FROM contacts WHERE fair_id=? "
                "ORDER BY created_at, id", (fair_id,)).fetchall()
        result = {}
        counts = {}
        for r in rows:
            st = r["status"]
            counts[st] = counts.get(st, 0) + 1
            result.setdefault(st, []).append((r["created_at"], counts[st]))
        return result

    def unique_companies_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT MIN(created_at) AS first, company FROM contacts "
                "WHERE fair_id=? AND company IS NOT NULL AND company != '' "
                "GROUP BY company_id, company ORDER BY first",
                (fair_id,)).fetchall()
        return [(r["first"], i + 1) for i, r in enumerate(rows)]

    # ------------------------------------------------------------------
    # Auth: Users / Roles / Sessions / Audit
    # ------------------------------------------------------------------
    def has_any_user(self):
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def list_users(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM users ORDER BY username").fetchall()
        return [dict(r) for r in rows]

    def get_user(self, user_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def create_user(self, username, display_name, email, password_hash,
                    password_salt, password_iter, must_change_password=True,
                    is_admin=False):
        now = self._now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO users (username, display_name, email, "
                "password_hash, password_salt, password_iter, "
                "must_change_password, is_active, is_admin, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (username, display_name, email or None, password_hash,
                 password_salt, password_iter,
                 1 if must_change_password else 0,
                 1 if is_admin else 0, now, now))
            user_id = cur.lastrowid
            self.conn.commit()
        return user_id

    def update_user_password(self, user_id, password_hash, password_salt,
                             password_iter, must_change_password=False):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET password_hash=?, password_salt=?, "
                "password_iter=?, must_change_password=?, updated_at=? "
                "WHERE id=?",
                (password_hash, password_salt, password_iter,
                 1 if must_change_password else 0,
                 self._now(), user_id))
            self.conn.commit()

    def set_user_active(self, user_id, active):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET is_active=?, updated_at=? WHERE id=?",
                (1 if active else 0, self._now(), user_id))
            self.conn.commit()

    def set_user_admin(self, user_id, is_admin):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET is_admin=?, updated_at=? WHERE id=?",
                (1 if is_admin else 0, self._now(), user_id))
            self.conn.commit()

    def count_active_admins(self, exclude_user_id=None):
        with self._lock:
            query = ("SELECT COUNT(*) FROM users WHERE is_admin=1 "
                     "AND is_active=1")
            params = []
            if exclude_user_id is not None:
                query += " AND id != ?"
                params.append(exclude_user_id)
            return self.conn.execute(query, params).fetchone()[0]

    def set_user_role(self, user_id, role_id):
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                "VALUES (?, ?)", (user_id, role_id))
            self.conn.commit()

    def set_user_roles(self, user_id, role_ids):
        with self._lock:
            self.conn.execute(
                "DELETE FROM user_roles WHERE user_id=?", (user_id,))
            for rid in role_ids:
                self.conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (?, ?)", (user_id, rid))
            self.conn.commit()

    def user_role_ids(self, user_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT role_id FROM user_roles WHERE user_id=?",
                (user_id,)).fetchall()
        return [r["role_id"] for r in rows]

    def get_user_permissions(self, user_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT DISTINCT rp.permission FROM user_roles ur "
                "JOIN role_permissions rp ON rp.role_id = ur.role_id "
                "WHERE ur.user_id=?", (user_id,)).fetchall()
        return {r["permission"] for r in rows}

    def create_role(self, name, description, permissions):
        with self._lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO roles (name, description, is_system, "
                    "created_at) VALUES (?, ?, 0, ?)",
                    (name, description or None, self._now()))
                role_id = cur.lastrowid
                for perm in permissions:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO role_permissions "
                        "(role_id, permission) VALUES (?, ?)",
                        (role_id, perm))
                self.conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Rolle „{name}“ existiert bereits.")
        return role_id

    def list_roles(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM roles ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def log_login_attempt(self, username, ip, success):
        with self._lock:
            self.conn.execute(
                "INSERT INTO login_attempts (username, ip, success, "
                "timestamp) VALUES (?, ?, ?, ?)",
                (username, ip or None, 1 if success else 0, self._now()))
            self.conn.commit()

    def increment_failed_login(self, user_id):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET failed_login_count = "
                "failed_login_count + 1 WHERE id=?", (user_id,))
            self.conn.commit()

    def get_failed_login_count(self, user_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT failed_login_count FROM users WHERE id=?",
                (user_id,)).fetchone()
        return row[0] if row else 0

    def reset_failed_login(self, user_id):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET failed_login_count=0, locked_until=NULL "
                "WHERE id=?", (user_id,))
            self.conn.commit()

    def set_user_lockout(self, user_id, until_iso):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET locked_until=? WHERE id=?",
                (until_iso, user_id))
            self.conn.commit()

    def set_user_last_login(self, user_id):
        with self._lock:
            self.conn.execute(
                "UPDATE users SET last_login=? WHERE id=?",
                (self._now(), user_id))
            self.conn.commit()

    def create_session(self, user_id, token, expires_iso, ip="",
                       user_agent=""):
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions (user_id, token, created_at, "
                "expires_at, revoked, ip, user_agent) "
                "VALUES (?, ?, ?, ?, 0, ?, ?)",
                (user_id, token, self._now(), expires_iso,
                 ip or None, user_agent or None))
            self.conn.commit()

    def revoke_session(self, token):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE token=?", (token,))
            self.conn.commit()

    def revoke_user_sessions(self, user_id):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def get_session(self, token):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM sessions WHERE token=? AND revoked=0",
                (token,)).fetchone()
        return dict(row) if row else None

    def audit(self, user_id, action, target_type=None, target_id=None,
              details=None):
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit_log (timestamp, user_id, action, "
                "target_type, target_id, details) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self._now(), user_id, action, target_type, target_id,
                 details))
            self.conn.commit()