import os, tempfile
import pytest
from database.db import Database
from core.export import export_contacts_csv


@pytest.fixture
def db():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "test.db"))
    db.init_db()
    yield db
    db.close()


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
    db.add_merch_count(item, fid, 100)  # initial
    db.add_merch_count(item, fid, 20)   # issued 80
    db.add_merch_count(item, fid, 100)  # refill, issued 0
    db.add_merch_count(item, fid, 60)   # issued 40
    summary = db.merch_summary(fid)[0]
    assert summary["current_stock"] == 60
    assert summary["cumulative_issued"] == 120


def test_attendance_idempotent(db):
    fid = db.create_fair("Messe")
    eid, _ = db.create_employee("Anna")
    db.add_attendance(eid, fid, "enter", "Smartphone")
    db.add_attendance(eid, fid, "enter", "Smartphone")  # idempotent
    rows = db.search_contacts(fair_id=fid)
    att = db.current_attendance(fid)
    assert att[eid]["event_type"] == "enter"