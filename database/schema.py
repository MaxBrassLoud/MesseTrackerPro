SCHEMA_VERSION = 8

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

-- ================== NEU v4: Auth-Tabellen ==================

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    email TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iter INTEGER NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ip TEXT,
    success INTEGER NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);

-- v5: CRM, Nachfassaktionen und Messe-Checklisten.  Die zusätzlichen
-- Kontaktspalten werden für bestehende Datenbanken in Database.init_db ergänzt.
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    website TEXT,
    phone TEXT,
    address TEXT,                -- NEU v8: Firmenadresse (einzeilig)
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS follow_up_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fair_id INTEGER REFERENCES fairs(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    due_date TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low','normal','high')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','done')),
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON follow_up_tasks(status, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_contact ON follow_up_tasks(contact_id);

CREATE TABLE IF NOT EXISTS contact_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_contact ON contact_events(contact_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fair_checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fair_id INTEGER NOT NULL REFERENCES fairs(id) ON DELETE CASCADE,
    phase TEXT NOT NULL DEFAULT 'preparation' CHECK(phase IN ('preparation','during','followup')),
    title TEXT NOT NULL,
    due_date TEXT,
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checklist_fair ON fair_checklist_items(fair_id, done);

CREATE TABLE IF NOT EXISTS contact_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT 'Geschäftlich', street TEXT, postal_code TEXT,
    city TEXT, country TEXT, is_primary INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contact_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel_type TEXT NOT NULL CHECK(channel_type IN ('email','phone','website')),
    value TEXT NOT NULL, label TEXT, is_primary INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_contact_channels_contact ON contact_channels(contact_id);
"""