# core/backup.py
import json
import shutil
import sqlite3
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path

from config import (
    DB_PATH, CARDS_DIR, BACKUP_DIR, BACKUP_ROTATION_COUNT,
    ALLOWED_IMAGE_EXTENSIONS
)

SCHEMA_VERSION = 3  # Muss mit database.schema.SCHEMA_VERSION übereinstimmen

class BackupError(Exception):
    pass

def _validate_zip_member(name: str):
    """Verhindert Path-Traversal und absolute Pfade."""
    if name.startswith("/") or ".." in Path(name).parts:
        raise BackupError(f"Unsicherer Pfad im ZIP: {name}")

def _validate_sqlite(db_file: Path):
    """Prüft Integrität und Schema-Version der SQLite-Datei."""
    try:
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"SQLite-Integritätsfehler: {integrity}")
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key='schema_version'"
        ).fetchone()
        if not row:
            raise BackupError("Keine Schema-Version in der Datenbank gefunden.")
        version = int(row["value"])
        if version > SCHEMA_VERSION:
            raise BackupError(
                f"Datenbank-Schema {version} ist neuer als die Anwendung "
                f"({SCHEMA_VERSION}). Bitte Anwendung aktualisieren."
            )
        conn.close()
    except sqlite3.Error as e:
        raise BackupError(f"SQLite-Datei ungültig: {e}")

def create_backup(target_zip: str, auto_rotate: bool = False):
    """Konsistentes Backup via SQLite-Backup-API + Bilder als ZIP."""
    target = Path(target_zip)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = target.with_suffix(".sqlite.tmp")
    if tmp_db.exists():
        tmp_db.unlink()

    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(tmp_db))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "schema": SCHEMA_VERSION,
        "app": "Messe Tracker Pro",
    }

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "messe_tracker.db")
        z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        if CARDS_DIR.exists():
            for p in CARDS_DIR.rglob("*"):
                if p.is_file():
                    if p.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                        continue
                    z.write(p, f"cards/{p.relative_to(CARDS_DIR)}")

    tmp_db.unlink(missing_ok=True)

    if auto_rotate:
        _rotate_backups()

    return target

def _rotate_backups():
    """Löscht die ältesten automatischen Backups."""
    backups = sorted(BACKUP_DIR.glob("auto_backup_*.zip"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[BACKUP_ROTATION_COUNT:]:
        try:
            old.unlink()
        except OSError:
            pass

def restore_backup(source_zip: str, confirm_overwrite: bool = False):
    """Validiert das ZIP und stellt es atomar wieder her."""
    if not confirm_overwrite:
        raise BackupError(
            "Wiederherstellung erfordert ausdrückliche Bestätigung.")

    src = Path(source_zip)
    if not src.exists():
        raise FileNotFoundError(src)

    # 1. Automatisches Backup vor der Wiederherstellung
    auto_backup_path = BACKUP_DIR / (
        f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    )
    create_backup(str(auto_backup_path))

    # 2. ZIP validieren und in temporäres Verzeichnis entpacken
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            with zipfile.ZipFile(src, "r") as z:
                names = z.namelist()
                if "messe_tracker.db" not in names:
                    raise BackupError("Backup enthält keine messe_tracker.db")
                if "meta.json" not in names:
                    raise BackupError("Backup enthält keine meta.json")

                total_size = 0
                for info in z.infolist():
                    _validate_zip_member(info.filename)
                    total_size += info.file_size
                    if total_size > 500 * 1024 * 1024:  # 500 MB Limit
                        raise BackupError("Backup ist zu groß.")

                z.extractall(tmp_path)

        except zipfile.BadZipFile as e:
            raise BackupError(f"Beschädigtes ZIP-Archiv: {e}")

        extracted_db = tmp_path / "messe_tracker.db"
        if not extracted_db.exists():
            raise BackupError("Datenbank nicht im Backup gefunden.")

        _validate_sqlite(extracted_db)

        # 3. Metadaten prüfen (Schema-Version)
        meta_file = tmp_path / "meta.json"
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if int(meta.get("schema", 0)) > SCHEMA_VERSION:
                raise BackupError(
                    f"Backup-Schema {meta['schema']} ist neuer als die "
                    f"Anwendung ({SCHEMA_VERSION})."
                )
        except (json.JSONDecodeError, ValueError) as e:
            raise BackupError(f"Ungültige meta.json: {e}")

        # 4. Atomar ersetzen
        #    - Datenbank: tmp -> DB_PATH
        #    - Bilder: altes CARDS_DIR umbenennen, neues aus tmp kopieren
        backup_db = DB_PATH.with_suffix(".restore.tmp")
        shutil.copy2(extracted_db, backup_db)

        old_cards = None
        if CARDS_DIR.exists():
            old_cards = CARDS_DIR.with_name(
                f"cards_old_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            CARDS_DIR.rename(old_cards)

        CARDS_DIR.mkdir(parents=True, exist_ok=True)
        src_cards = tmp_path / "cards"
        if src_cards.exists():
            for p in src_cards.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(src_cards)
                    dest = CARDS_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)

        backup_db.replace(DB_PATH)

        if old_cards and old_cards.exists():
            shutil.rmtree(old_cards, ignore_errors=True)

    return True