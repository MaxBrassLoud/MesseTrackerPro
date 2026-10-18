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
            self._migrate_contacts_if_needed()
            self._drop_flipper_tables()
            self._seed_default_statuses()
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
            cur = self.conn.execute(
                """INSERT INTO contacts
                (fair_id,fair_day_id,employee_id,name,company,position,phone,email,
                 status,notes,source,card_image_path,processing_status,external_id,
                 created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fair_id, fair_day_id, employee_id, name, company, position,
                 phone, email, status, notes, source, card_image_path,
                 processing_status, external_id, ts, ts))
            return cur.lastrowid

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
            self.conn.execute(
                f"UPDATE contacts SET {sets}, updated_at=? WHERE id=?",
                (*vals, now_iso(), contact_id))

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
            return {
                "total_today": total_today, "total_fair": total_fair,
                "companies": companies, "by_status": by_status,
                "pending_cards": pending_cards,
                "present": present, "absent": absent, "merch": merch,
            }