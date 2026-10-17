SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT,
    start_date TEXT,
    end_date TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fair_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fair_id INTEGER NOT NULL REFERENCES fairs(id),
    day_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_fair_days_fair ON fair_days(fair_id);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    token TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#FF8200',
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
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
CREATE INDEX IF NOT EXISTS idx_contacts_fair ON contacts(fair_id);
CREATE INDEX IF NOT EXISTS idx_contacts_emp ON contacts(employee_id);

CREATE TABLE IF NOT EXISTS card_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fair_id INTEGER NOT NULL REFERENCES fairs(id),
    fair_day_id INTEGER REFERENCES fair_days(id),
    employee_id INTEGER REFERENCES employees(id),
    image_path TEXT NOT NULL,
    original_filename TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    ocr_name TEXT,
    ocr_company TEXT,
    ocr_position TEXT,
    ocr_phone TEXT,
    ocr_email TEXT,
    contact_id INTEGER REFERENCES contacts(id),
    external_id TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    fair_id INTEGER NOT NULL REFERENCES fairs(id),
    fair_day_id INTEGER REFERENCES fair_days(id),
    event_type TEXT NOT NULL CHECK(event_type IN ('enter','leave')),
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    external_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_att_emp ON attendance_events(employee_id);
CREATE INDEX IF NOT EXISTS idx_att_fair ON attendance_events(fair_id);

CREATE TABLE IF NOT EXISTS merch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fair_id INTEGER NOT NULL REFERENCES fairs(id),
    name TEXT NOT NULL,
    category TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merch_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES merch_items(id),
    fair_id INTEGER NOT NULL REFERENCES fairs(id),
    fair_day_id INTEGER REFERENCES fair_days(id),
    counted_stock INTEGER NOT NULL,
    previous_stock INTEGER,
    issued_since_previous INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    employee_id INTEGER REFERENCES employees(id),
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_merch_item ON merch_counts(item_id);
"""