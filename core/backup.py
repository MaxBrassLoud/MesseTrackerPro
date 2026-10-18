# core/backup.py
import json
import logging
import shutil
import sqlite3
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path

from config import (
    DB_PATH, CARDS_DIR, BACKUP_DIR, DATA_DIR, BACKUP_ROTATION_COUNT,
    ALLOWED_IMAGE_EXTENSIONS
)

from database.schema import SCHEMA_VERSION

# Sicherheitslimit beim Entpacken (Defense-in-Depth gegen ZIP-Bombs)
MAX_RESTORE_BYTES = 500 * 1024 * 1024  # 500 MB

# Wenn beim Startup eine Wiederherstellung ansteht, liegt das ZIP hier.
PENDING_RESTORE_FILE = DATA_DIR / "restore_pending.zip"


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


def validate_backup_for_restore(source_zip: str) -> dict:
    """Validiert das Backup, ohne es anzuwenden. Gibt die Meta zurück.

    Raises BackupError bei jedem Problem. Wird von der UI genutzt, um
    Fehler *vor* dem Staging anzuzeigen.
    """
    src = Path(source_zip)
    if not src.exists():
        raise FileNotFoundError(src)

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
                    if total_size > MAX_RESTORE_BYTES:
                        raise BackupError("Backup ist zu groß.")

                z.extractall(tmp_path)
        except zipfile.BadZipFile as e:
            raise BackupError(f"Beschädigtes ZIP-Archiv: {e}")

        extracted_db = tmp_path / "messe_tracker.db"
        if not extracted_db.exists():
            raise BackupError("Datenbank nicht im Backup gefunden.")

        _validate_sqlite(extracted_db)

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

        return meta


def stage_restore(source_zip: str) -> Path:
    """Validiert das Backup und legt es als ausstehende Wiederherstellung ab.

    Der eigentliche Restore passiert beim nächsten Start von `apply_pending_restore`,
    *bevor* die Datenbank geöffnet wird.
    """
    validate_backup_for_restore(source_zip)
    PENDING_RESTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_zip, PENDING_RESTORE_FILE)
    return PENDING_RESTORE_FILE


def apply_pending_restore() -> bool:
    """Wird beim Startup *vor* dem Öffnen der DB aufgerufen.

    Returns True, wenn eine Wiederherstellung durchgeführt wurde.
    Wirft bei Fehlern eine Exception – die Datei bleibt dann liegen,
    damit der nächste Start es erneut versuchen kann.
    """
    if not PENDING_RESTORE_FILE.exists():
        return False

    logging.info("Wiederherstellung ausstehend: %s", PENDING_RESTORE_FILE)
    try:
        restore_backup(str(PENDING_RESTORE_FILE), confirm_overwrite=True)
    except Exception:
        logging.exception("Wiederherstellung fehlgeschlagen – Datei bleibt für Retry liegen.")
        raise

    try:
        PENDING_RESTORE_FILE.unlink()
    except OSError:
        pass
    logging.info("Wiederherstellung erfolgreich abgeschlossen.")
    return True


def restore_backup(source_zip: str, confirm_overwrite: bool = False):
    """Validiert das ZIP und stellt es wieder her.

    Sollte nur aufgerufen werden, wenn die DB-Verbindung geschlossen ist
    (Startup, CLI). Von der UI nur via `stage_restore` + Neustart!
    """
    if not confirm_overwrite:
        raise BackupError(
            "Wiederherstellung erfordert ausdrückliche Bestätigung.")

    src = Path(source_zip)
    if not src.exists():
        raise FileNotFoundError(src)

    # 1. Automatisches Backup vor der Wiederherstellung (nur wenn DB existiert)
    if DB_PATH.exists():
        try:
            auto_backup_path = BACKUP_DIR / (
                f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            )
            create_backup(str(auto_backup_path))
            logging.info("Pre-Restore-Backup: %s", auto_backup_path)
        except Exception as e:
            logging.warning("Pre-Restore-Backup fehlgeschlagen: %s", e)

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
                    if total_size > MAX_RESTORE_BYTES:
                        raise BackupError("Backup ist zu groß.")

                z.extractall(tmp_path)

        except zipfile.BadZipFile as e:
            raise BackupError(f"Beschädigtes ZIP-Archiv: {e}")

        extracted_db = tmp_path / "messe_tracker.db"
        if not extracted_db.exists():
            raise BackupError("Datenbank nicht im Backup gefunden.")

        _validate_sqlite(extracted_db)

        # 3. Metadaten prüfen
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

        # 4. Atomar ersetzen (Reihenfolge: Karten zuerst, DB zuletzt –
        #    so bleibt der wichtigste Teil bei Teil-Fehlern intakt)
        staging_db = DB_PATH.with_suffix(".restore.tmp")
        shutil.copy2(extracted_db, staging_db)

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

        try:
            staging_db.replace(DB_PATH)
        except Exception:
            logging.exception("DB-Austausch fehlgeschlagen – Karten-Rollback")
            staging_db.unlink(missing_ok=True)
            raise

        if old_cards and old_cards.exists():
            shutil.rmtree(old_cards, ignore_errors=True)

    return True
