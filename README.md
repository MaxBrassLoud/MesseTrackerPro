<div align="center">

# Messe Tracker Pro

**A local-first desktop CRM for trade fairs, contacts, and follow-ups.**

Capture leads. Organize relationships. Turn conversations into next steps.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-Desktop%20App-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="PyQt5" src="https://img.shields.io/badge/GUI-PyQt5-41CD52?style=for-the-badge&logo=qt&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Database-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Local%20Capture-Flask-000000?style=for-the-badge&logo=flask&logoColor=white">
</p>

**Desktop application** · **Local SQLite storage** · **Optional LAN-based capture**

</div>

---

## Table of Contents

- Quick Start
- Overview
- Highlights
- Features
- Tech Stack
- Requirements
- Installation
- Running the App
- Mobile Capture (LAN)
- Data Storage & Config
- Security & Privacy
- Backups & Recovery
- Running Tests
- Project Layout
- Troubleshooting
- Contributing
- License

---

## ⚡ Quick Start

```bash
# 1. Clone and enter the project
git clone https://github.com/MaxBrassLoud/MesseTrackerPro && cd messetrackerpro

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
````

On first launch, the setup wizard helps you create the first administrator account.

---

## ✨ Overview

**Messe Tracker Pro** is a Python desktop application for managing contacts collected at trade fairs and turning them into actionable follow-ups. It combines:

- a **PyQt5 desktop interface**,
- a **local SQLite database**,
- and an optional **Flask web server** for mobile capture on the local network.

Use it to organize companies and contacts, review business-card scans, manage trade fairs and team members, detect duplicates, and generate reports from your collected data.

> **Project status:** This README documents capabilities and defaults visible in the source code. It does not guarantee that every workflow has been independently tested on every operating system.

---

## 🚀 Highlights

- **👥 Contact management** — Organize people, companies, contact channels, custom fields, activities, and follow-up tasks in one place.
- **🪪 Business-card workflow** — Queue card images, extract text via OCR, review recognized fields, and edit before saving.
- **🧹 Data quality** — Detect likely duplicates, review matches, and merge records while preserving related data where supported.
- **📊 Reporting** — Dashboard metrics, CSV exports, PDF trade-fair reports, and charts.
- **🔐 Accounts & permissions** — Administrator setup, role- and permission-based access checks, and an audit log for security-relevant actions.
- **💾 Backup support** — Scheduled local backups with validation and prepared restore.

---

## 🧩 Features

### Contacts & Companies
- Manage contacts and company profiles.
- Store names, roles, phone numbers, emails, notes, statuses, addresses, websites, and other channels.
- Custom fields for contacts and companies: text, number, date, selection, checkbox, and multiline text.
- Track activities, tasks, and follow-up reminders per contact.

### Business-Card Capture & OCR
- Manage business-card images in a processing queue.
- Extract text using **Tesseract OCR** via pytesseract.
- Review recognized fields, confidence info, and raw OCR text before saving.
- Language support (with the matching Tesseract packs installed): **DE, EN, FR, ES, IT**.
- File-size, image-dimension, and processing limits apply to uploads.
- **OCR is optional.** Install the Tesseract engine and language packs separately — the Python package alone is not sufficient.

### Duplicate Detection & Merging
- Find candidates using email, phone, name, and company signals.
- Review similarity suggestions before deciding.
- Mark reviewed pairs as non-duplicates.
- Merge contacts and carry over tasks, events, addresses, channels, and custom-field values.

### Trade Fairs & Team Members
- Create, manage, and archive trade fairs.
- Record individual fair days.
- Manage team members and their active status.
- Generate QR codes and capture links per team member; renew access tokens.
- Use attendance events in supported reports.

### Dashboard, Reports & Exports
- Key figures and summaries on the dashboard.
- Reports covering contacts, activity over time, companies, merchandise counts, and attendance.
- Charts rendered with **Matplotlib**.
- CSV export for contacts (fair, team member, status, address, website, custom fields).
- PDF trade-fair reports.

### Merchandise Tracking
- Manage merchandise items.
- Record counts and inspect count history.

### User Accounts & Access Control
- First admin created through the setup flow.
- Password authentication with **PBKDF2-HMAC-SHA256** and per-user salt.
- Database-backed sessions with expiry and server-side revocation.
- Account lock for **15 minutes** after **5** failed logins.
- Role- and permission-based checks on supported features.
- Audit log for selected security-relevant actions.
- Password changes revoke sessions; automatic logout after inactivity.
- A CSRF-protection flag is enabled — *review the route implementation before treating it as a complete control.*

### Interface & Diagnostics
- PyQt5 desktop UI.
- Theme selection (default: Flipper).
- Rotating application log file.
- Error dialogs with details for unhandled exceptions.

---

## 🛠️ Tech Stack

| Component            | Technology                                  |
| -------------------- | ------------------------------------------- |
| Language             | Python                                      |
| Desktop UI           | PyQt5                                       |
| Local database       | SQLite                                      |
| Local capture server | Flask                                       |
| QR codes             | qrcode, Pillow                              |
| OCR                  | pytesseract + external Tesseract engine     |
| Charts               | Matplotlib                                  |
| Tests                | pytest                                      |

---

## 📋 Requirements

- Python on your PATH, with a version compatible with requirements.txt.
- pip.
- Project files, including requirements.txt.
- *(Optional)* Tesseract OCR + language data.
- *(Optional)* Computer and mobile devices on the same local network.

> No verified Python version matrix is specified in the source. Use a version compatible with the pinned dependencies.

---

## 📦 Installation

### 1. Get the project
Download or clone the repository, then open a terminal in the project directory.

### 2. Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. *(Optional)* Set up OCR

1. Install the **Tesseract OCR engine** for your OS.
2. Install the language packs you need.
3. If Tesseract is not on PATH, configure the executable path.

---

## ▶️ Running the App

From the project directory:

```bash
python main.py
```

**On first launch:** the setup wizard guides you through creating the first administrator. You can then log in through the login dialog.

**At startup**, the application may:
- create its data directory,
- initialize or update the database schema,
- process a previously prepared restore,
- create a daily backup (if due).

---

## 📱 Mobile Capture (LAN)

The Flask capture server binds to 0.0.0.0:8765 by default, so it is reachable from other devices on the same local network. The app prints a URL in the form:

```text
http://<computer-LAN-IP>:8765
```

Team members can use the provided QR codes or capture links for supported workflows.

### Network Safety Checklist
- [ ] Both devices are on the same reachable network.
- [ ] Firewall allows port 8765.
- [ ] You're using the computer's **LAN IP** — not localhost — on the phone.
- [ ] Server is **not** exposed to the public internet.

> ⚠️ **Before using the capture server with real contact data:** review web routes, authentication, session handling, CSRF behavior, and deployment configuration. This server is designed as a local tool — *not* a hardened public-facing deployment.

---

## 🗃️ Data Storage & Config

By default, data is stored inside the project directory:

| Path                        | Purpose                     |
| --------------------------- | --------------------------- |
| data/messe_tracker.db       | SQLite database             |
| data/cards/                 | Business-card images        |
| data/backups/               | Backup archives             |
| data/messe_tracker.log      | Application log             |

### Defaults in config.py

| Setting                                | Default                          |
| -------------------------------------- | -------------------------------- |
| Local web server port                  | 8765                             |
| Automatic backup                       | At startup, at most once/day     |
| Automatic backup retention             | 10 newest backups                |
| Maximum upload size                    | 20 MB                            |
| Maximum image pixel count              | 50,000,000 px                    |
| Maximum processed image edge           | 2,400 px                         |
| Processed JPEG quality                 | 88                               |
| Automatic logout after inactivity      | 5 minutes                        |
| Configurable logout interval           | 0–240 min (0 disables)           |

> These are **source-code defaults** — local edits or future versions may change them.

---

## 🔐 Security & Privacy

Messe Tracker Pro can store **names, contact details, notes, activity history, and business-card images** — potentially personal or commercially sensitive data.

### Do
- Store the project directory on a device protected by appropriate account and disk security.
- Restrict access to the computer, database, backups, and image directory to authorized people.
- Keep backups in a secure location — they may contain the same sensitive data as the live database.
- Test restore workflows on a copy of your data.

### Don't
- Do **not** assume local-network traffic is encrypted — the documented default URL is HTTP.
- Do **not** forward port 8765 to the internet.
- Do **not** deploy the server publicly without a separate security review.
- Do **not** treat any feature here as a compliance guarantee without independent review.

> This README is technical documentation — **not** a security audit or a regulatory compliance guarantee.

---

## 💾 Backups & Recovery

The source implements a local backup workflow with:

- **Startup backup** — created at most once per day.
- **Contents** — SQLite database, metadata, and supported business-card images.
- **Rotation** — keeps the ten newest automatic backups by default.
- **Validation before restore** — SQLite integrity check and schema-version check.
- **Prepared restore** — applied on the next application startup, so the database can be replaced safely.
- **Safety net** — current data is backed up before restoration where possible.

> **Best practice:** periodically copy a backup to a separate secure location and test the restore process on a copy of your data.

---

## 🧪 Running Tests

With the virtual environment active:

```bash
pytest -q
```

Tests live under tests/ and cover authentication, core functionality, and CRM behavior.

> A passing test run is useful evidence — **not** a substitute for manual checks of backup restoration, access control, and OCR on your target system.

---

## 🗂️ Project Layout

```text
maxbrassloud-messetrackerpro/
├── main.py                  # Entry point: login, server, backup startup
├── config.py                # Settings and data paths
├── requirements.txt         # Python dependencies
├── core/
│   ├── auth.py              # Authentication and user management
│   ├── backup.py            # Backup and restore workflow
│   ├── contact_extras.py    # Addresses and websites
│   ├── custom_fields.py     # Custom field definitions
│   ├── duplicates.py        # Duplicate detection and merging
│   ├── export.py            # CSV export
│   ├── net.py               # Local IP helper
│   ├── ocr.py               # OCR and field extraction
│   ├── pdf_report.py        # PDF reports
│   └── permissions.py       # Roles and permissions
├── database/
│   └── schema.py            # Schema and migrations
├── ui/
│   ├── main_window.py       # Main window and navigation
│   ├── login_dialog.py      # Login dialog
│   ├── setup_wizard.py      # First-run setup
│   ├── dialogs/             # Merge, password, and other dialogs
│   └── pages/               # Dashboard, contacts, fairs, reports, …
├── web/
│   └── server.py            # Capture and upload server
├── tests/
│   ├── test_auth.py
│   ├── test_core.py
│   └── test_crm.py
└── data/                    # Runtime data (created on demand)
    ├── messe_tracker.db
    ├── cards/
    ├── backups/
    └── messe_tracker.log
```

---

## 🧯 Troubleshooting

<details>
<summary><strong>The application does not start</strong></summary>

1. Activate the virtual environment.
2. Reinstall dependencies: pip install -r requirements.txt.
3. Run python main.py from the project root, so relative paths resolve.
4. Check data/messe_tracker.log for details.

</details>

<details>
<summary><strong>OCR returns no text</strong></summary>

1. Confirm the **Tesseract OCR engine** is installed — pytesseract is only a wrapper.
2. Confirm the required **language data** is installed.
3. If Tesseract is not on PATH, configure its executable path.
4. Use a clear, well-lit image and review the OCR result manually before saving.

</details>

<details>
<summary><strong>A phone cannot open the capture page</strong></summary>

1. Confirm both devices can communicate on the same local network.
2. Open the computer's **LAN IP** address — not localhost — on the phone.
3. Check firewall rules for port 8765.
4. Confirm the server started successfully and listens on the configured port.

</details>

<details>
<summary><strong>I need to restore a backup</strong></summary>

1. Keep an extra copy of the current data/ directory first.
2. Use the application's supported restore workflow and follow its prompts.
3. Do **not** manually replace the live database while the app is running.

</details>

---

## 🤝 Contributing

Contributions and issue reports are welcome. Before submitting a change:

- Keep existing data and user workflows compatible where possible.
- Add or update automated tests for behavior changes.
- Check database migrations and backup/restore compatibility when changing the schema.
- Run pytest -q and describe any tests you could not run.
- **Never** include real contact records, credentials, tokens, or private business-card images in issues or test fixtures.

---

## 📄 License

No license information could be identified from the supplied project source. Until a license is added to the repository, **do not** assume the code is open-source or that reuse, redistribution, or modification is permitted.

---

<div align="center">

**Messe Tracker Pro**  
Keep every trade-fair conversation connected to the next step.

</div>