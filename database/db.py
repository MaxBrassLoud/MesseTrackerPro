import sqlite3
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime

from database.schema import SCHEMA_SQL, SCHEMA_VERSION


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            path, check_same_thread=False, timeout=30
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=30000")

    @contextmanager
    def transaction(self):
        """Explizite Transaktion. Bei Exception Rollback."""
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    # ---------- Setup / Migration ----------
    def init_db(self):
        with self._lock, self.conn:
            self.conn.executescript(SCHEMA_SQL)
            self._migrate_v5()
            self._migrate_contacts_if_needed()
            self._drop_flipper_tables()
            self._seed_default_statuses()
            self._seed_default_roles()
            row = self.conn.execute(
                "SELECT value FROM app_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO app_meta(key,value) VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),))
            else:
                self.conn.execute(
                    "UPDATE app_meta SET value=? WHERE key='schema_version'",
                    (str(SCHEMA_VERSION),))
            self.conn.execute(
                "INSERT OR IGNORE INTO app_meta(key,value) "
                "VALUES('theme','Flipper')")
            self.conn.execute(
                "INSERT OR IGNORE INTO app_meta(key,value) "
                "VALUES('web_secret_key', ?)",
                (uuid.uuid4().hex,))

    def _migrate_v5(self):
        """Ergänzt v5-Felder ohne bestehende Kontakte umzubauen."""
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(contacts)")}
        for name, definition in (
            ("company_id", "INTEGER REFERENCES companies(id) ON DELETE SET NULL"),
            ("lead_score", "INTEGER"),
            ("lead_score_reason", "TEXT"),
        ):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE contacts ADD COLUMN {name} {definition}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone)")
        emp_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(employees)")}
        if "user_id" not in emp_columns:
            self.conn.execute("ALTER TABLE employees ADD COLUMN user_id INTEGER REFERENCES users(id)")
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_user ON employees(user_id) WHERE user_id IS NOT NULL")
        # Bestehende Zugänge werden einmalig als Mitarbeiter sichtbar gemacht.
        for user in self.conn.execute("SELECT id,display_name,email FROM users WHERE id NOT IN (SELECT user_id FROM employees WHERE user_id IS NOT NULL)").fetchall():
            self.conn.execute("INSERT INTO employees(name,email,active,token,created_at,user_id) VALUES(?,?,1,?,?,?)", (user["display_name"] or f"Benutzer {user['id']}", user["email"] or "", uuid.uuid4().hex, now_iso(), user["id"]))

    def _migrate_contacts_if_needed(self):
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='contacts'"
        ).fetchone()
        if not row or not row["sql"] or "CHECK(status IN" not in row["sql"]:
            return
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self.conn.executescript("""
            CREATE TABLE contacts_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fair_id INTEGER NOT NULL REFERENCES fairs(id),
                fair_day_id INTEGER REFERENCES fair_days(id),
                employee_id INTEGER REFERENCES employees(id),
                name TEXT,
                company TEXT,
                position TEXT,
                phone TEXT,
                email TEXT,
                status TEXT NOT NULL DEFAULT 'Interessiert',
                notes TEXT,
                source TEXT NOT NULL,
                card_image_path TEXT,
                processing_status TEXT NOT NULL DEFAULT 'ok',
                sync_status TEXT NOT NULL DEFAULT 'synced',
                external_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO contacts_new SELECT * FROM contacts;
            DROP TABLE contacts;
            ALTER TABLE contacts_new RENAME TO contacts;
            CREATE INDEX IF NOT EXISTS idx_contacts_fair ON contacts(fair_id);
            CREATE INDEX IF NOT EXISTS idx_contacts_emp ON contacts(employee_id);
            """)
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _drop_flipper_tables(self):
        for tbl in ("flipper_assignments", "flipper_devices", "sync_log"):
            try:
                self.conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception:
                pass

    def _seed_default_statuses(self):
        count = self.conn.execute(
            "SELECT COUNT(*) FROM contact_statuses").fetchone()[0]
        if count > 0:
            return
        from config import DEFAULT_STATUSES
        for i, name in enumerate(DEFAULT_STATUSES):
            self.conn.execute(
                "INSERT INTO contact_statuses(name,color,sort_order,active,created_at)"
                " VALUES(?,?,?,1,?)",
                (name, "#FF8200", (i + 1) * 10, now_iso()))

    def close(self):
        with self._lock:
            self.conn.close()

    # ---------- Settings ----------
    def get_setting(self, key, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key, value):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO app_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))

    # ---------- Contact statuses ----------
    def list_statuses(self, active_only=False):
        q = "SELECT * FROM contact_statuses"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY sort_order, name"
        with self._lock:
            return [dict(r) for r in self.conn.execute(q).fetchall()]

    def get_status(self, status_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM contact_statuses WHERE id=?", (status_id,)).fetchone()
            return dict(row) if row else None

    def create_status(self, name, color="#FF8200", sort_order=None):
        name = name.strip()
        if not name:
            raise ValueError("Name erforderlich.")
        with self._lock, self.conn:
            exists = self.conn.execute(
                "SELECT 1 FROM contact_statuses WHERE name=?", (name,)).fetchone()
            if exists:
                raise ValueError(f"Status '{name}' existiert bereits.")
            if sort_order is None:
                max_order = self.conn.execute(
                    "SELECT COALESCE(MAX(sort_order),0) FROM contact_statuses"
                ).fetchone()[0]
                sort_order = max_order + 10
            cur = self.conn.execute(
                "INSERT INTO contact_statuses(name,color,sort_order,active,created_at)"
                " VALUES(?,?,?,1,?)",
                (name, color, sort_order, now_iso()))
            return cur.lastrowid

    def update_status(self, status_id, **fields):
        allowed = {"name", "color", "sort_order", "active"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._lock, self.conn:
            if "name" in fields:
                old = self.conn.execute(
                    "SELECT name FROM contact_statuses WHERE id=?", (status_id,)
                ).fetchone()
                new_name = fields["name"].strip()
                if not new_name:
                    raise ValueError("Name darf nicht leer sein.")
                if old and old["name"] != new_name:
                    dup = self.conn.execute(
                        "SELECT 1 FROM contact_statuses WHERE name=? AND id<>?",
                        (new_name, status_id)).fetchone()
                    if dup:
                        raise ValueError(f"Status '{new_name}' existiert bereits.")
                    self.conn.execute(
                        "UPDATE contacts SET status=? WHERE status=?",
                        (new_name, old["name"]))
                    fields["name"] = new_name
            self.conn.execute(
                f"UPDATE contact_statuses SET {sets} WHERE id=?",
                (*vals, status_id))

    def status_usage_count(self, status_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT name FROM contact_statuses WHERE id=?", (status_id,)
            ).fetchone()
            if not row:
                return 0
            return self.conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE status=?",
                (row["name"],)).fetchone()[0]

    def delete_status(self, status_id):
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT name FROM contact_statuses WHERE id=?", (status_id,)
            ).fetchone()
            if not row:
                return 0, "Status nicht gefunden."
            name = row["name"]
            in_use = self.conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE status=?", (name,)
            ).fetchone()[0]
            if in_use > 0:
                return in_use, (
                    f"Status '{name}' wird von {in_use} Kontakt(en) verwendet "
                    f"und kann nicht gelöscht werden. Bitte zuerst die Kontakte "
                    f"umstellen oder den Status deaktivieren.")
            self.conn.execute("DELETE FROM contact_statuses WHERE id=?", (status_id,))
            return 0, None

    # ---------- Fairs ----------
    def create_fair(self, name, location="", start_date="", end_date=""):
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO fairs(name,location,start_date,end_date,created_at)"
                " VALUES(?,?,?,?,?)",
                (name, location, start_date, end_date, now_iso()))
            return cur.lastrowid

    def list_fairs(self, include_archived=False):
        q = "SELECT * FROM fairs"
        if not include_archived:
            q += " WHERE archived=0"
        q += " ORDER BY id DESC"
        with self._lock:
            return [dict(r) for r in self.conn.execute(q).fetchall()]

    def update_fair(self, fair_id, **fields):
        allowed = {"name", "location", "start_date", "end_date", "archived"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._lock, self.conn:
            self.conn.execute(f"UPDATE fairs SET {sets} WHERE id=?", (*vals, fair_id))

    # ---------- Fair days ----------
    def start_fair_day(self, fair_id: int) -> int:
        # FIX #6: global prüfen, damit nie zwei aktive Messetage existieren.
        with self._lock, self.conn:
            active = self.conn.execute(
                "SELECT id, fair_id FROM fair_days WHERE is_active=1"
            ).fetchone()
            if active:
                if active["fair_id"] == fair_id:
                    raise ValueError(
                        "Für diese Messe läuft bereits ein aktiver Messetag.")
                raise ValueError(
                    "Für eine andere Messe läuft bereits ein aktiver Messetag. "
                    "Bitte diesen zuerst beenden.")
            today = datetime.now().date().isoformat()
            cur = self.conn.execute(
                "INSERT INTO fair_days(fair_id,day_date,started_at,is_active)"
                " VALUES(?,?,?,1)",
                (fair_id, today, now_iso()))
            return cur.lastrowid

    def end_fair_day(self, fair_day_id: int):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE fair_days SET ended_at=?, is_active=0 WHERE id=?",
                (now_iso(), fair_day_id))

    def get_active_fair_day(self):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM fair_days WHERE is_active=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def list_fair_days(self, fair_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM fair_days WHERE fair_id=? ORDER BY id DESC",
                (fair_id,)).fetchall()]

    # ---------- Employees ----------
    def create_employee(self, name, email="", phone=""):
        token = uuid.uuid4().hex
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO employees(name,email,phone,active,token,created_at)"
                " VALUES(?,?,?,1,?,?)",
                (name, email, phone, token, now_iso()))
            return cur.lastrowid, token

    def ensure_employee_for_user(self, user_id, name, email=""):
        with self._lock, self.conn:
            existing = self.conn.execute("SELECT id FROM employees WHERE user_id=?", (user_id,)).fetchone()
            if existing: return existing["id"]
            return self.conn.execute("INSERT INTO employees(name,email,active,token,created_at,user_id) VALUES(?,?,1,?,?,?)", (name, email, uuid.uuid4().hex, now_iso(), user_id)).lastrowid

    def list_employees(self, active_only=False):
        q = "SELECT * FROM employees"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY name"
        with self._lock:
            return [dict(r) for r in self.conn.execute(q).fetchall()]

    def update_employee(self, emp_id, **fields):
        allowed = {"name", "email", "phone", "active"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._lock, self.conn:
            self.conn.execute(
                f"UPDATE employees SET {sets} WHERE id=?", (*vals, emp_id))

    def get_employee_by_token(self, token):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM employees WHERE token=?", (token,)).fetchone()
            return dict(row) if row else None

    def get_employee_by_user_id(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT * FROM employees WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def regenerate_employee_token(self, emp_id: int) -> str:
        new_token = uuid.uuid4().hex
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE employees SET token=? WHERE id=?",
                (new_token, emp_id))
            if cur.rowcount == 0:
                raise ValueError(f"Mitarbeiter-ID {emp_id} existiert nicht.")
        return new_token

    # ---------- Contacts ----------
    def create_contact(self, fair_id, source, employee_id=None, fair_day_id=None,
                       name="", company="", position="", phone="", email="",
                       status="Interessiert", notes="", card_image_path=None,
                       processing_status="ok", external_id=None):
        ts = now_iso()
        with self._lock, self.conn:
            company_id = None
            if (company or "").strip():
                company_id = self.upsert_company(company)
            cur = self.conn.execute(
                """INSERT INTO contacts
                (fair_id,fair_day_id,employee_id,name,company,position,phone,email,
                 status,notes,source,card_image_path,processing_status,external_id,
                 created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fair_id, fair_day_id, employee_id, name, company, position,
                 phone, email, status, notes, source, card_image_path,
                 processing_status, external_id, ts, ts))
            contact_id = cur.lastrowid
            if company_id:
                self.conn.execute("UPDATE contacts SET company_id=? WHERE id=?", (company_id, contact_id))
            self._contact_event(contact_id, "created", "Kontakt erfasst")
            return contact_id

    # FIX #3: Atomare Erstellung Kontakt + Karte.
    def create_contact_with_card(
        self, *, fair_id, fair_day_id, employee_id, source,
        name, company, position, phone, email, status, notes,
        image_path, original_filename, external_id,
    ):
        """Erzeugt Kontakt und ordnet die zugehörige Karte atomar zu.

        Idempotent über external_id: mehrfaches Senden führt nicht zu
        Duplikaten, sondern liefert den bestehenden Kontakt zurück.

        Returns (contact_id, card_dict|None, created_card:bool).
        """
        ts = now_iso()
        with self._lock:
            try:
                existing = self.conn.execute(
                    "SELECT id FROM contacts WHERE external_id=?",
                    (external_id,)).fetchone()
                if existing:
                    card_row = self.conn.execute(
                        "SELECT * FROM card_queue WHERE external_id=?",
                        (external_id,)).fetchone()
                    self.conn.rollback()
                    return (existing["id"],
                            dict(card_row) if card_row else None,
                            False)

                cur = self.conn.execute(
                    """INSERT INTO contacts
                    (fair_id,fair_day_id,employee_id,name,company,position,
                     phone,email,status,notes,source,card_image_path,
                     processing_status,external_id,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fair_id, fair_day_id, employee_id, name, company, position,
                     phone, email, status, notes, source, image_path,
                     "ok", external_id, ts, ts))
                contact_id = cur.lastrowid

                card_row = self.conn.execute(
                    "SELECT * FROM card_queue WHERE external_id=?",
                    (external_id,)).fetchone()
                if card_row:
                    self.conn.execute(
                        "UPDATE card_queue SET status='processed', contact_id=?, "
                        "ocr_name=?, ocr_company=?, ocr_position=?, "
                        "ocr_phone=?, ocr_email=? WHERE id=?",
                        (contact_id, name, company, position, phone, email,
                         card_row["id"]))
                    card = dict(card_row)
                    created = False
                else:
                    cur2 = self.conn.execute(
                        """INSERT INTO card_queue
                        (fair_id,fair_day_id,employee_id,image_path,
                         original_filename,status,ocr_name,ocr_company,
                         ocr_position,ocr_phone,ocr_email,contact_id,
                         external_id,created_at)
                        VALUES(?,?,?,?,?,'processed',?,?,?,?,?,?,?,?)""",
                        (fair_id, fair_day_id, employee_id, image_path,
                         original_filename, name, company, position, phone,
                         email, contact_id, external_id, ts))
                    card = {"id": cur2.lastrowid, "image_path": image_path}
                    created = True

                self.conn.commit()
                return contact_id, card, created
            except Exception:
                self.conn.rollback()
                raise

    def update_contact(self, contact_id, **fields):
        allowed = {"name", "company", "position", "phone", "email", "status",
                   "notes", "processing_status", "sync_status", "card_image_path"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._lock, self.conn:
            if "company" in fields and (fields["company"] or "").strip():
                company_id = self.upsert_company(fields["company"])
                self.conn.execute("UPDATE contacts SET company_id=? WHERE id=?", (company_id, contact_id))
            self.conn.execute(
                f"UPDATE contacts SET {sets}, updated_at=? WHERE id=?",
                (*vals, now_iso(), contact_id))
            self._contact_event(contact_id, "updated", ", ".join(sorted(k for k in fields if k in allowed)))

    def delete_contact(self, contact_id):
        """Löscht den Kontakt. Verknüpfte Karten werden als 'orphaned'
        markiert, damit sie in der Queue sichtbar bleiben (kein stiller
        Bild-Müll)."""
        # FIX #7
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE card_queue SET contact_id=NULL, status='orphaned' "
                "WHERE contact_id=?",
                (contact_id,))
            self.conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))

    # ---------- CRM v5 ----------
    def _contact_event(self, contact_id, event_type, details="", actor_user_id=None):
        self.conn.execute(
            "INSERT INTO contact_events(contact_id,actor_user_id,event_type,details,created_at) VALUES(?,?,?,?,?)",
            (contact_id, actor_user_id, event_type, details, now_iso()))

    def contact_history(self, contact_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                """SELECT e.*, u.username AS actor_name FROM contact_events e
                   LEFT JOIN users u ON u.id=e.actor_user_id WHERE e.contact_id=?
                   ORDER BY e.created_at DESC, e.id DESC""", (contact_id,)).fetchall()]

    def list_contact_channels(self, contact_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM contact_channels WHERE contact_id=? ORDER BY channel_type, is_primary DESC, id", (contact_id,)).fetchall()]

    def add_contact_channel(self, contact_id, channel_type, value, label="", is_primary=False):
        if channel_type not in {"email", "phone", "website"} or not (value or "").strip():
            raise ValueError("Kontaktweg und Wert erforderlich.")
        with self._lock, self.conn:
            if is_primary: self.conn.execute("UPDATE contact_channels SET is_primary=0 WHERE contact_id=? AND channel_type=?", (contact_id, channel_type))
            return self.conn.execute("INSERT INTO contact_channels(contact_id,channel_type,value,label,is_primary) VALUES(?,?,?,?,?)", (contact_id, channel_type, value.strip(), label.strip(), int(is_primary))).lastrowid

    def delete_contact_channel(self, channel_id):
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM contact_channels WHERE id=?", (channel_id,))

    def list_contact_addresses(self, contact_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM contact_addresses WHERE contact_id=? ORDER BY is_primary DESC,id", (contact_id,)).fetchall()]

    def add_contact_address(self, contact_id, street="", postal_code="", city="", country="", label="Geschäftlich", is_primary=True):
        with self._lock, self.conn:
            if is_primary: self.conn.execute("UPDATE contact_addresses SET is_primary=0 WHERE contact_id=?", (contact_id,))
            return self.conn.execute("INSERT INTO contact_addresses(contact_id,label,street,postal_code,city,country,is_primary) VALUES(?,?,?,?,?,?,?)", (contact_id, label, street, postal_code, city, country, int(is_primary))).lastrowid

    def delete_contact_address(self, address_id):
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM contact_addresses WHERE id=?", (address_id,))

    def upsert_company(self, name, website="", phone="", notes=""):
        name = (name or "").strip()
        if not name:
            raise ValueError("Firmenname erforderlich.")
        with self._lock, self.conn:
            row = self.conn.execute("SELECT id FROM companies WHERE name=? COLLATE NOCASE", (name,)).fetchone()
            if row:
                self.conn.execute("UPDATE companies SET website=COALESCE(NULLIF(?,''),website), phone=COALESCE(NULLIF(?,''),phone), notes=COALESCE(NULLIF(?,''),notes), updated_at=? WHERE id=?", (website, phone, notes, now_iso(), row["id"]))
                return row["id"]
            return self.conn.execute("INSERT INTO companies(name,website,phone,notes,created_at,updated_at) VALUES(?,?,?,?,?,?)", (name, website, phone, notes, now_iso(), now_iso())).lastrowid

    def company_contacts(self, company_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM contacts WHERE company_id=? ORDER BY name, id", (company_id,)).fetchall()]

    def create_task(self, title, *, fair_id=None, contact_id=None, company_id=None, description="", due_date=None, priority="normal", assigned_user_id=None):
        if not (title or "").strip():
            raise ValueError("Aufgabentitel erforderlich.")
        if priority not in {"low", "normal", "high"}:
            raise ValueError("Ungültige Priorität.")
        with self._lock, self.conn:
            task_id = self.conn.execute("""INSERT INTO follow_up_tasks(fair_id,contact_id,company_id,title,description,due_date,priority,assigned_user_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (fair_id, contact_id, company_id, title.strip(), description, due_date or None, priority, assigned_user_id, now_iso(), now_iso())).lastrowid
            if contact_id:
                self._contact_event(contact_id, "task_created", title.strip(), assigned_user_id)
            return task_id

    def list_tasks(self, fair_id=None, contact_id=None, status=None):
        q = """SELECT t.*, c.name AS contact_name, c.company AS contact_company, u.username AS assigned_name
               FROM follow_up_tasks t LEFT JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assigned_user_id WHERE 1=1"""
        args = []
        if fair_id is not None: q += " AND t.fair_id=?"; args.append(fair_id)
        if contact_id is not None: q += " AND t.contact_id=?"; args.append(contact_id)
        if status: q += " AND t.status=?"; args.append(status)
        q += " ORDER BY CASE t.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, CASE t.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, COALESCE(t.due_date,'9999-12-31'), t.id DESC"
        with self._lock: return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def update_task(self, task_id, **fields):
        allowed = {"title", "description", "due_date", "priority", "status", "assigned_user_id"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if clean.get("status") not in (None, "open", "in_progress", "done"): raise ValueError("Ungültiger Status.")
        if not clean: return
        if clean.get("status") == "done": clean["completed_at"] = now_iso()
        elif "status" in clean: clean["completed_at"] = None
        sets = ", ".join(f"{k}=?" for k in clean) + ", updated_at=?"
        with self._lock, self.conn:
            task = self.conn.execute("SELECT contact_id,title FROM follow_up_tasks WHERE id=?", (task_id,)).fetchone()
            self.conn.execute(f"UPDATE follow_up_tasks SET {sets} WHERE id=?", (*clean.values(), now_iso(), task_id))
            if task and task["contact_id"] and "status" in clean:
                self._contact_event(task["contact_id"], "task_" + clean["status"], task["title"])

    def find_duplicate_candidates(self, contact_id):
        c = self.get_contact(contact_id)
        if not c: return []
        def norm(value): return "".join(ch.lower() for ch in (value or "") if ch.isalnum())
        email, phone = norm(c.get("email")), norm(c.get("phone"))
        if not email and not phone: return []
        candidates = []
        for other in self.search_contacts():
            if other["id"] == contact_id: continue
            oe, op = norm(other.get("email")), norm(other.get("phone"))
            reasons = []
            if email and email == oe: reasons.append("gleiche E-Mail")
            if phone and phone == op: reasons.append("gleiche Telefonnummer")
            if reasons: candidates.append({"contact": other, "reasons": reasons})
        return candidates

    def merge_contacts(self, keep_id, duplicate_id, actor_user_id=None):
        if keep_id == duplicate_id: raise ValueError("Ein Kontakt kann nicht mit sich selbst zusammengeführt werden.")
        with self.transaction():
            keep, duplicate = self.get_contact(keep_id), self.get_contact(duplicate_id)
            if not keep or not duplicate: raise ValueError("Kontakt nicht gefunden.")
            for field in ("name", "company", "position", "phone", "email", "notes", "card_image_path", "company_id", "lead_score", "lead_score_reason"):
                if not keep.get(field) and duplicate.get(field):
                    self.conn.execute(f"UPDATE contacts SET {field}=?, updated_at=? WHERE id=?", (duplicate[field], now_iso(), keep_id))
            self.conn.execute("UPDATE follow_up_tasks SET contact_id=? WHERE contact_id=?", (keep_id, duplicate_id))
            self.conn.execute("UPDATE card_queue SET contact_id=? WHERE contact_id=?", (keep_id, duplicate_id))
            self._contact_event(keep_id, "duplicate_merged", f"Mit Kontakt #{duplicate_id} zusammengeführt", actor_user_id)
            self.conn.execute("DELETE FROM contacts WHERE id=?", (duplicate_id,))

    def score_contact(self, contact_id, manual_score=None, actor_user_id=None):
        """Liefert eine nachvollziehbare Lead-Einstufung (0–100).

        Es werden ausschließlich gespeicherte Angaben ausgewertet. Ein manuell
        gesetzter Wert wird nicht durch die automatische Bewertung überschrieben.
        """
        contact = self.get_contact(contact_id)
        if not contact:
            raise ValueError("Kontakt nicht gefunden.")
        if manual_score is not None:
            if not isinstance(manual_score, int) or not 0 <= manual_score <= 100:
                raise ValueError("Lead-Bewertung muss zwischen 0 und 100 liegen.")
            score, reasons = manual_score, ["manuell festgelegt"]
        else:
            score, reasons = 0, []
            status = (contact.get("status") or "").casefold()
            if status in {"auftrag erteilt", "auftrag"}: score += 50; reasons.append("Auftrag dokumentiert")
            elif status in {"anfrage", "interessiert"}: score += 25; reasons.append(f"Status: {contact.get('status')}")
            if contact.get("notes"):
                score += 15; reasons.append("Gesprächsnotiz vorhanden")
            if self.conn.execute("SELECT 1 FROM follow_up_tasks WHERE contact_id=? AND status<>'done'", (contact_id,)).fetchone():
                score += 15; reasons.append("offener nächster Schritt")
            if contact.get("company"):
                score += 5; reasons.append("Unternehmen angegeben")
            score = min(score, 100)
        with self._lock, self.conn:
            self.conn.execute("UPDATE contacts SET lead_score=?, lead_score_reason=?, updated_at=? WHERE id=?", (score, "; ".join(reasons) or "keine ausreichenden Angaben", now_iso(), contact_id))
            self._contact_event(contact_id, "lead_scored", f"{score}/100: {'; '.join(reasons) or 'keine ausreichenden Angaben'}", actor_user_id)
        return {"score": score, "reasons": reasons}

    def create_checklist_item(self, fair_id, title, phase="preparation", due_date=None, assigned_user_id=None):
        if phase not in {"preparation", "during", "followup"}: raise ValueError("Ungültige Checklistenphase.")
        with self._lock, self.conn:
            return self.conn.execute("INSERT INTO fair_checklist_items(fair_id,phase,title,due_date,assigned_user_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (fair_id, phase, title, due_date, assigned_user_id, now_iso(), now_iso())).lastrowid

    def list_checklist_items(self, fair_id):
        with self._lock: return [dict(r) for r in self.conn.execute("SELECT * FROM fair_checklist_items WHERE fair_id=? ORDER BY done, phase, due_date, id", (fair_id,)).fetchall()]

    def set_checklist_done(self, item_id, done):
        with self._lock, self.conn: self.conn.execute("UPDATE fair_checklist_items SET done=?, updated_at=? WHERE id=?", (int(done), now_iso(), item_id))

    def get_contact(self, contact_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
            return dict(row) if row else None

    def search_contacts(self, fair_id=None, status=None, employee_id=None,
                        fair_day_id=None, text=""):
        q = "SELECT * FROM contacts WHERE 1=1"
        args = []
        if fair_id is not None:
            q += " AND fair_id=?"; args.append(fair_id)
        if status:
            q += " AND status=?"; args.append(status)
        if employee_id is not None:
            q += " AND employee_id=?"; args.append(employee_id)
        if fair_day_id is not None:
            q += " AND fair_day_id=?"; args.append(fair_day_id)
        if text:
            q += " AND (name LIKE ? OR company LIKE ? OR email LIKE ?)"
            like = f"%{text}%"; args.extend([like, like, like])
        q += " ORDER BY id DESC"
        with self._lock:
            return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    # ---------- Card queue ----------
    def enqueue_card(self, fair_id, image_path, fair_day_id=None, employee_id=None,
                     original_filename="", external_id=None):
        with self._lock, self.conn:
            if external_id:
                row = self.conn.execute(
                    "SELECT * FROM card_queue WHERE external_id=?",
                    (external_id,)).fetchone()
                if row:
                    return dict(row), False
            cur = self.conn.execute(
                """INSERT INTO card_queue
                (fair_id,fair_day_id,employee_id,image_path,original_filename,
                 status,external_id,created_at)
                VALUES(?,?,?,?,?,'pending',?,?)""",
                (fair_id, fair_day_id, employee_id, image_path,
                 original_filename, external_id, now_iso()))
            return {"id": cur.lastrowid, "image_path": image_path}, True

    def list_card_queue(self, status=None):
        q = "SELECT * FROM card_queue"
        if status:
            q += " WHERE status=?"
        q += " ORDER BY id ASC"
        with self._lock:
            args = (status,) if status else ()
            return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def get_card(self, card_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM card_queue WHERE id=?", (card_id,)).fetchone()
            return dict(row) if row else None

    def update_card_ocr(self, card_id, **fields):
        allowed = {"status", "ocr_name", "ocr_company", "ocr_position",
                   "ocr_phone", "ocr_email", "contact_id"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._lock, self.conn:
            self.conn.execute(
                f"UPDATE card_queue SET {sets} WHERE id=?", (*vals, card_id))

    # ---------- Attendance ----------
    def add_attendance(self, employee_id, fair_id, event_type, source,
                       fair_day_id=None, external_id=None):
        if event_type not in ("enter", "leave"):
            raise ValueError("Ungültiger Ereignistyp")
        with self._lock, self.conn:
            if external_id:
                row = self.conn.execute(
                    "SELECT id FROM attendance_events WHERE external_id=?",
                    (external_id,)).fetchone()
                if row:
                    return row["id"], False
            last = self.conn.execute(
                "SELECT event_type FROM attendance_events "
                "WHERE employee_id=? ORDER BY id DESC LIMIT 1",
                (employee_id,)).fetchone()
            if last and last["event_type"] == event_type:
                return None, False
            cur = self.conn.execute(
                """INSERT INTO attendance_events
                (employee_id,fair_id,fair_day_id,event_type,source,timestamp,external_id)
                VALUES(?,?,?,?,?,?,?)""",
                (employee_id, fair_id, fair_day_id, event_type, source,
                 now_iso(), external_id))
            return cur.lastrowid, True

    def current_attendance(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT e.employee_id, e.event_type, e.timestamp
                   FROM attendance_events e
                   JOIN (SELECT employee_id, MAX(id) AS mid
                         FROM attendance_events WHERE fair_id=?
                         GROUP BY employee_id) m ON m.mid=e.id""",
                (fair_id,)).fetchall()
            return {r["employee_id"]: {"event_type": r["event_type"],
                                       "timestamp": r["timestamp"]}
                    for r in rows}

    # ---------- Merch ----------
    def create_merch_item(self, fair_id, name, category=""):
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO merch_items(fair_id,name,category,created_at)"
                " VALUES(?,?,?,?)",
                (fair_id, name, category, now_iso()))
            return cur.lastrowid

    def list_merch_items(self, fair_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM merch_items WHERE fair_id=? ORDER BY name",
                (fair_id,)).fetchall()]

    def add_merch_count(self, item_id, fair_id, counted_stock, fair_day_id=None,
                        employee_id=None, note=""):
        with self._lock, self.conn:
            last = self.conn.execute(
                "SELECT counted_stock FROM merch_counts WHERE item_id=? "
                "ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
            prev = last["counted_stock"] if last else None
            if prev is None:
                issued = 0
            else:
                diff = prev - counted_stock
                issued = diff if diff > 0 else 0
                if diff < 0 and not note:
                    note = f"Nachfüllung/Korrektur erkannt (+{-diff})"
            cur = self.conn.execute(
                """INSERT INTO merch_counts
                (item_id,fair_id,fair_day_id,counted_stock,previous_stock,
                 issued_since_previous,timestamp,employee_id,note)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (item_id, fair_id, fair_day_id, counted_stock, prev, issued,
                 now_iso(), employee_id, note))
            return cur.lastrowid

    def merch_history(self, item_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM merch_counts WHERE item_id=? ORDER BY id ASC",
                (item_id,)).fetchall()]

    def merch_summary(self, fair_id):
        with self._lock:
            items = self.list_merch_items(fair_id)
            result = []
            for it in items:
                hist = self.merch_history(it["id"])
                current = hist[-1]["counted_stock"] if hist else 0
                cumulative = sum(c["issued_since_previous"] for c in hist)
                result.append({**it, "current_stock": current,
                               "cumulative_issued": cumulative,
                               "counts": len(hist)})
            return result

    # ---------- Analytics ----------
    def contacts_by_day(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT substr(created_at,1,10) AS day, COUNT(*) AS cnt
                   FROM contacts WHERE fair_id=? GROUP BY day ORDER BY day""",
                (fair_id,)).fetchall()
            return [(r["day"], r["cnt"]) for r in rows]

    def contacts_by_hour(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT substr(created_at,12,2) AS hour, COUNT(*) AS cnt
                   FROM contacts WHERE fair_id=? GROUP BY hour ORDER BY hour""",
                (fair_id,)).fetchall()
            return [(r["hour"], r["cnt"]) for r in rows]

    def cumulative_contacts_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT created_at FROM contacts WHERE fair_id=? "
                "ORDER BY created_at, id", (fair_id,)).fetchall()
            return [(r["created_at"], i) for i, r in enumerate(rows, 1)]

    def unique_companies_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT MIN(created_at) AS first_seen, company
                   FROM contacts WHERE fair_id=? AND company<>''
                   GROUP BY company ORDER BY first_seen""",
                (fair_id,)).fetchall()
            return [(r["first_seen"], r["company"]) for r in rows]

    def status_timeline(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT created_at, status FROM contacts WHERE fair_id=? "
                "ORDER BY created_at, id", (fair_id,)).fetchall()
            counters = defaultdict(int)
            timeline = defaultdict(list)
            for r in rows:
                counters[r["status"]] += 1
                timeline[r["status"]].append(
                    (r["created_at"], counters[r["status"]]))
            return dict(timeline)

    def attendance_intervals(self, fair_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT employee_id, event_type, timestamp
                   FROM attendance_events WHERE fair_id=?
                   ORDER BY timestamp, id""", (fair_id,)).fetchall()
            open_iv = {}
            intervals = defaultdict(list)
            for r in rows:
                emp = r["employee_id"]
                if r["event_type"] == "enter":
                    open_iv[emp] = r["timestamp"]
                elif r["event_type"] == "leave" and emp in open_iv:
                    intervals[emp].append((open_iv[emp], r["timestamp"]))
                    del open_iv[emp]
            now = now_iso()
            for emp, start in open_iv.items():
                intervals[emp].append((start, now))
            return dict(intervals)

    def merch_series(self, item_id):
        with self._lock:
            rows = self.conn.execute(
                """SELECT timestamp, counted_stock, issued_since_previous, note
                   FROM merch_counts WHERE item_id=?
                   ORDER BY timestamp, id""", (item_id,)).fetchall()
            result = []
            cumulative = 0
            for r in rows:
                cumulative += r["issued_since_previous"]
                result.append({
                    "timestamp": r["timestamp"],
                    "counted_stock": r["counted_stock"],
                    "issued": r["issued_since_previous"],
                    "cumulative": cumulative,
                    "note": r["note"] or "",
                })
            return result

    def fair_period(self, fair_id):
        with self._lock:
            row = self.conn.execute(
                """SELECT MIN(started_at) AS start,
                          COALESCE(MAX(ended_at), MAX(started_at)) AS end
                   FROM fair_days WHERE fair_id=?""", (fair_id,)).fetchone()
            return (row["start"], row["end"]) if row and row["start"] else (None, None)

    # ---------- Dashboard ----------
    def dashboard_stats(self, fair_id, fair_day_id=None):
        with self._lock:
            def one(q, *a):
                return self.conn.execute(q, a).fetchone()[0]
            total_today = (one("SELECT COUNT(*) FROM contacts "
                               "WHERE fair_id=? AND fair_day_id=?",
                               fair_id, fair_day_id) if fair_day_id else 0)
            total_fair = one("SELECT COUNT(*) FROM contacts WHERE fair_id=?", fair_id)
            companies = one(
                "SELECT COUNT(DISTINCT company) FROM contacts "
                "WHERE fair_id=? AND company<>''", fair_id)
            statuses = [s["name"] for s in self.list_statuses()]
            by_status = {
                s: one("SELECT COUNT(*) FROM contacts WHERE fair_id=? AND status=?",
                       fair_id, s) for s in statuses
            }
            pending_cards = one(
                "SELECT COUNT(*) FROM card_queue WHERE status<>'processed'")
            att = self.current_attendance(fair_id)
            present = [eid for eid, v in att.items() if v["event_type"] == "enter"]
            absent = [eid for eid, v in att.items() if v["event_type"] == "leave"]
            merch = self.merch_summary(fair_id)
            tasks_open = one("SELECT COUNT(*) FROM follow_up_tasks WHERE fair_id=? AND status<>'done'", fair_id)
            tasks_overdue = one("SELECT COUNT(*) FROM follow_up_tasks WHERE fair_id=? AND status<>'done' AND due_date IS NOT NULL AND due_date<?", fair_id, datetime.now().date().isoformat())
            return {
                "total_today": total_today, "total_fair": total_fair,
                "companies": companies, "by_status": by_status,
                "pending_cards": pending_cards,
                "present": present, "absent": absent, "merch": merch,
                "tasks_open": tasks_open, "tasks_overdue": tasks_overdue,
            }

    # ================== Auth v4 ==================

    def _seed_default_roles(self):
        from core.permissions import (
            ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS,
            SYSTEM_ROLE_ADMIN_ID, SYSTEM_ROLE_USER_ID,
        )
        now = now_iso()
        self.conn.execute(
            "INSERT OR IGNORE INTO roles(id,name,description,is_system,created_at) "
            "VALUES(?,?,?,1,?)",
            (SYSTEM_ROLE_ADMIN_ID, "Administrator",
             "Vollzugriff auf alle Funktionen", now))
        self.conn.execute(
            "INSERT OR IGNORE INTO roles(id,name,description,is_system,created_at) "
            "VALUES(?,?,?,1,?)",
            (SYSTEM_ROLE_USER_ID, "Benutzer",
             "Standardzugriff (Lesen, Erstellen, Bearbeiten)", now))
        for p, _ in ALL_PERMISSIONS:
            self.conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id,permission) "
                "VALUES(?,?)", (SYSTEM_ROLE_ADMIN_ID, p))
        for p in DEFAULT_USER_PERMISSIONS:
            self.conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id,permission) "
                "VALUES(?,?)", (SYSTEM_ROLE_USER_ID, p))

    # ---- Users ----
    def has_any_user(self) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def create_user(self, *, username, display_name, email, password_hash,
                    password_salt, password_iter, must_change_password,
                    is_admin) -> int:
        ts = now_iso()
        with self._lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO users
                (username,display_name,email,password_hash,password_salt,
                 password_iter,must_change_password,is_active,is_admin,
                 created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,1,?,?,?)""",
                (username, display_name, email, password_hash, password_salt,
                 password_iter, int(must_change_password), int(is_admin),
                 ts, ts))
            return cur.lastrowid

    def get_user(self, user_id):
        with self._lock:
            r = self.conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(r) if r else None

    def get_user_by_username(self, username):
        with self._lock:
            r = self.conn.execute(
                "SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(r) if r else None

    def list_users(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM users ORDER BY username").fetchall()]

    def update_user_password(self, user_id, pw_hash, salt, iters,
                             must_change_password):
        ts = now_iso()
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET password_hash=?, password_salt=?, "
                "password_iter=?, must_change_password=?, updated_at=? "
                "WHERE id=?",
                (pw_hash, salt, iters, int(must_change_password), ts, user_id))

    def set_user_active(self, user_id, active):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET is_active=?, updated_at=? WHERE id=?",
                (int(active), now_iso(), user_id))

    def set_user_admin(self, user_id, is_admin):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin=?, updated_at=? WHERE id=?",
                (int(is_admin), now_iso(), user_id))

    def set_user_last_login(self, user_id):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET last_login=? WHERE id=?",
                (now_iso(), user_id))

    def increment_failed_login(self, user_id):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET failed_login_count=failed_login_count+1 "
                "WHERE id=?", (user_id,))

    def get_failed_login_count(self, user_id):
        with self._lock:
            r = self.conn.execute(
                "SELECT failed_login_count FROM users WHERE id=?",
                (user_id,)).fetchone()
            return r["failed_login_count"] if r else 0

    def reset_failed_login(self, user_id):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET failed_login_count=0, locked_until=NULL "
                "WHERE id=?", (user_id,))

    def set_user_lockout(self, user_id, until_iso):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE users SET locked_until=? WHERE id=?",
                (until_iso, user_id))

    def count_active_admins(self, exclude_user_id=None) -> int:
        q = "SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1"
        args = []
        if exclude_user_id is not None:
            q += " AND id<>?"; args.append(exclude_user_id)
        with self._lock:
            return self.conn.execute(q, args).fetchone()[0]

    # ---- Roles / Permissions ----
    def set_user_role(self, user_id, role_id):
        with self._lock, self.conn:
            self.conn.execute(
                "DELETE FROM user_roles WHERE user_id=?", (user_id,))
            self.conn.execute(
                "INSERT INTO user_roles(user_id,role_id) VALUES(?,?)",
                (user_id, role_id))

    def set_user_roles(self, user_id, role_ids):
        """Ersetzt die frei wählbaren Rollen eines Benutzers atomar."""
        role_ids = {int(role_id) for role_id in role_ids}
        with self._lock, self.conn:
            valid = {r["id"] for r in self.conn.execute("SELECT id FROM roles WHERE id IN (%s)" % ",".join("?" * len(role_ids)), tuple(role_ids)).fetchall()} if role_ids else set()
            if valid != role_ids: raise ValueError("Mindestens eine Rolle existiert nicht.")
            self.conn.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
            self.conn.executemany("INSERT INTO user_roles(user_id,role_id) VALUES(?,?)", [(user_id, role_id) for role_id in role_ids])

    def user_role_ids(self, user_id):
        with self._lock:
            return {r["role_id"] for r in self.conn.execute("SELECT role_id FROM user_roles WHERE user_id=?", (user_id,)).fetchall()}

    def get_user_permissions(self, user_id) -> set:
        with self._lock:
            rows = self.conn.execute(
                """SELECT DISTINCT rp.permission
                   FROM user_roles ur
                   JOIN role_permissions rp ON rp.role_id=ur.role_id
                   WHERE ur.user_id=?""", (user_id,)).fetchall()
            return {r["permission"] for r in rows}

    def list_roles(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM roles ORDER BY id").fetchall()]

    def get_role_permissions(self, role_id) -> set:
        with self._lock:
            rows = self.conn.execute(
                "SELECT permission FROM role_permissions WHERE role_id=?",
                (role_id,)).fetchall()
            return {r["permission"] for r in rows}

    def create_role(self, name, description="", permissions=()) -> int:
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO roles(name,description,is_system,created_at) "
                "VALUES(?,?,0,?)", (name, description, now_iso()))
            rid = cur.lastrowid
            for p in permissions:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_id,permission) "
                    "VALUES(?,?)", (rid, p))
            return rid

    def set_role_permissions(self, role_id, permissions):
        from core.permissions import SYSTEM_ROLE_ADMIN_ID
        with self._lock, self.conn:
            if role_id == SYSTEM_ROLE_ADMIN_ID:
                raise ValueError(
                    "Admin-Rolle darf nicht eingeschränkt werden.")
            self.conn.execute(
                "DELETE FROM role_permissions WHERE role_id=?", (role_id,))
            for p in permissions:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_id,permission) "
                    "VALUES(?,?)", (role_id, p))

    # ---- Sessions ----
    def create_session(self, user_id, token, expires_at, ip="", user_agent=""):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO sessions(user_id,token,created_at,expires_at,"
                "ip,user_agent) VALUES(?,?,?,?,?,?)",
                (user_id, token, now_iso(), expires_at, ip, user_agent))

    def get_session(self, token):
        with self._lock:
            r = self.conn.execute(
                "SELECT * FROM sessions WHERE token=? AND revoked=0",
                (token,)).fetchone()
            return dict(r) if r else None

    def revoke_session(self, token):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE token=?", (token,))

    def revoke_user_sessions(self, user_id):
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))

    # ---- Login-Attempts / Audit ----
    def log_login_attempt(self, username, ip, success):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO login_attempts(username,ip,success,timestamp) "
                "VALUES(?,?,?,?)",
                (username, ip, int(success), now_iso()))

    def audit(self, user_id, action, target_type=None, target_id=None,
              details=None):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO audit_log(timestamp,user_id,action,target_type,"
                "target_id,details) VALUES(?,?,?,?,?,?)",
                (now_iso(), user_id, action, target_type, target_id, details))
