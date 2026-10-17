import os
import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from database.db import Database
from core.export import export_contacts_csv
from core import backup as backup_mod
from core.backup import (
    create_backup, restore_backup, BackupError, _validate_zip_member
)


@pytest.fixture
def db():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "test.db"))
    db.init_db()
    yield db
    db.close()


# ------------------------------------------------------------------
# Bestehende Basistests
# ------------------------------------------------------------------
def test_fair_and_day(db):
    fid = db.create_fair("TechExpo")
    did = db.start_fair_day(fid)
    assert db.get_active_fair_day()["id"] == did
    with pytest.raises(ValueError):
        db.start_fair_day(fid)
    db.end_fair_day(did)
    assert db.get_active_fair_day() is None


def test_contact_and_export(db, tmp_path):
    fid = db.create_fair("Messe")
    db.create_contact(fid, "Manuell", name="Max Müller", company="ACME GmbH",
                      email="max@acme.de", status="Anfrage")
    out = tmp_path / "out.csv"
    n = export_contacts_csv(db, fid, str(out))
    assert n == 1
    content = out.read_text(encoding="utf-8-sig")
    assert "Max Müller" in content and "ACME GmbH" in content
    assert "Anfrage" in content


def test_merch_math(db):
    fid = db.create_fair("Messe")
    item = db.create_merch_item(fid, "Sticker")
    db.add_merch_count(item, fid, 100)
    db.add_merch_count(item, fid, 20)
    db.add_merch_count(item, fid, 100)
    db.add_merch_count(item, fid, 60)
    summary = db.merch_summary(fid)[0]
    assert summary["current_stock"] == 60
    assert summary["cumulative_issued"] == 120


def test_attendance_idempotent(db):
    fid = db.create_fair("Messe")
    eid, _ = db.create_employee("Anna")
    db.add_attendance(eid, fid, "enter", "Smartphone")
    db.add_attendance(eid, fid, "enter", "Smartphone")
    att = db.current_attendance(fid)
    assert att[eid]["event_type"] == "enter"


# ------------------------------------------------------------------
# NEU: Token-Regenerierung
# ------------------------------------------------------------------
def test_regenerate_employee_token(db):
    emp_id, token1 = db.create_employee("Anna")
    assert db.get_employee_by_token(token1) is not None

    token2 = db.regenerate_employee_token(emp_id)
    assert token2 != token1
    # Alter Token ist ungültig
    assert db.get_employee_by_token(token1) is None
    # Neuer Token funktioniert
    emp = db.get_employee_by_token(token2)
    assert emp is not None and emp["id"] == emp_id


# ------------------------------------------------------------------
# NEU: Backup-/Restore-Validierung
# ------------------------------------------------------------------
def test_validate_zip_member_rejects_traversal():
    with pytest.raises(BackupError):
        _validate_zip_member("../evil.txt")
    with pytest.raises(BackupError):
        _validate_zip_member("/etc/passwd")
    with pytest.raises(BackupError):
        _validate_zip_member("cards/../../evil.txt")
    # Gültige Pfade dürfen nicht werfen
    _validate_zip_member("messe_tracker.db")
    _validate_zip_member("cards/abc.jpg")


def test_restore_rejects_zip_without_db(tmp_path):
    zpath = tmp_path / "no_db.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("meta.json", json.dumps({"schema": 3}))
    with pytest.raises(BackupError, match="messe_tracker.db"):
        restore_backup(str(zpath), confirm_overwrite=True)


def test_restore_rejects_zip_without_meta(tmp_path):
    zpath = tmp_path / "no_meta.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("messe_tracker.db", b"")
    with pytest.raises(BackupError, match="meta.json"):
        restore_backup(str(zpath), confirm_overwrite=True)


def test_restore_rejects_path_traversal(tmp_path):
    """ZIP mit '../evil.txt' darf nicht entpackt werden."""
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("messe_tracker.db", b"")
        z.writestr("meta.json", json.dumps({"schema": 3}))
        z.writestr("../evil.txt", "hacked")
    with pytest.raises(BackupError, match="Unsicherer Pfad"):
        restore_backup(str(zpath), confirm_overwrite=True)


def test_restore_rejects_corrupt_db(tmp_path, monkeypatch):
    """DB, die kein gültiges SQLite ist, wird abgelehnt."""
    # Backup-Modul auf temporäre Pfade umbiegen
    tmp_db = tmp_path / "app.db"
    tmp_cards = tmp_path / "cards"
    tmp_backups = tmp_path / "backups"
    tmp_cards.mkdir()
    tmp_backups.mkdir()
    monkeypatch.setattr(backup_mod, "DB_PATH", tmp_db)
    monkeypatch.setattr(backup_mod, "CARDS_DIR", tmp_cards)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_backups)

    zpath = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("messe_tracker.db", b"not a sqlite file")
        z.writestr("meta.json", json.dumps({"schema": 3}))
    with pytest.raises(BackupError, match="SQLite"):
        restore_backup(str(zpath), confirm_overwrite=True)


def test_restore_rejects_newer_schema(tmp_path, monkeypatch):
    """Backup mit höherer Schema-Version als die App wird abgelehnt."""
    tmp_db = tmp_path / "app.db"
    tmp_cards = tmp_path / "cards"
    tmp_backups = tmp_path / "backups"
    tmp_cards.mkdir()
    tmp_backups.mkdir()
    monkeypatch.setattr(backup_mod, "DB_PATH", tmp_db)
    monkeypatch.setattr(backup_mod, "CARDS_DIR", tmp_cards)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_backups)

    # Gültige SQLite-DB mit alter Schema-Version bauen
    import sqlite3
    src = tmp_path / "src.db"
    conn = sqlite3.connect(str(src))
    conn.executescript("""
        CREATE TABLE app_meta(key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO app_meta VALUES('schema_version', '99');
    """)
    conn.commit()
    conn.close()

    zpath = tmp_path / "newer.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(src, "messe_tracker.db")
        z.writestr("meta.json", json.dumps({"schema": 99}))
    with pytest.raises(BackupError, match="neuer"):
        restore_backup(str(zpath), confirm_overwrite=True)


def test_restore_rejects_missing_confirmation(tmp_path):
    zpath = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("messe_tracker.db", b"")
    with pytest.raises(BackupError, match="Bestätigung"):
        restore_backup(str(zpath), confirm_overwrite=False)


# ------------------------------------------------------------------
# NEU: CSRF-Schutz im Webserver
# ------------------------------------------------------------------
def test_csrf_blocks_post_without_token(db):
    from web.server import create_app
    app = create_app(db)
    app.config["TESTING"] = True
    client = app.test_client()
    # POST ohne CSRF-Token → 400
    resp = client.post("/api/irgendwas/submit", data={})
    assert resp.status_code == 400
    assert b"CSRF" in resp.data


def test_csrf_blocks_wrong_token(db):
    from web.server import create_app
    app = create_app(db)
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.post(
        "/api/irgendwas/submit",
        data={"csrf_token": "falsch"},
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------
# NEU: Upload-Validierung
# ------------------------------------------------------------------
def test_validate_image_accepts_real_png():
    from web.server import _validate_image
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, format="PNG")
    buf.seek(0)

    class FakeFile:
        def __init__(self, stream):
            self.stream = stream
        def seek(self, pos):
            self.stream.seek(pos)

    ok, err = _validate_image(FakeFile(buf))
    assert ok is True
    assert err is None


def test_validate_image_rejects_non_image():
    from web.server import _validate_image
    import io

    buf = io.BytesIO(b"das ist kein bild")
    buf.seek(0)

    class FakeFile:
        def __init__(self, stream):
            self.stream = stream
        def seek(self, pos):
            self.stream.seek(pos)

    ok, err = _validate_image(FakeFile(buf))
    assert ok is False
    assert err