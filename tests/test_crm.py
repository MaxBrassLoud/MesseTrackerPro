import os
import tempfile

import pytest

from database.db import Database


@pytest.fixture
def db():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    result = Database(path)
    result.init_db()
    yield result
    result.close()


def test_contact_creates_company_and_history(db):
    fair = db.create_fair("Messe")
    contact = db.create_contact(fair, "Manuell", name="Ada", company="Example GmbH")
    record = db.get_contact(contact)
    assert record["company_id"]
    assert db.company_contacts(record["company_id"])[0]["id"] == contact
    assert db.contact_history(contact)[0]["event_type"] == "created"


def test_task_lifecycle_and_history(db):
    fair = db.create_fair("Messe")
    contact = db.create_contact(fair, "Manuell", name="Ada")
    task = db.create_task("Anrufen", fair_id=fair, contact_id=contact, priority="high")
    assert db.list_tasks(fair)[0]["status"] == "open"
    db.update_task(task, status="done")
    assert db.list_tasks(fair)[0]["completed_at"]
    assert any(e["event_type"] == "task_done" for e in db.contact_history(contact))


def test_duplicates_require_email_or_phone_match(db):
    fair = db.create_fair("Messe")
    first = db.create_contact(fair, "Manuell", name="Alex", email="A@Example.test")
    same_name = db.create_contact(fair, "Manuell", name="Alex", email="other@example.test")
    matching = db.create_contact(fair, "Manuell", name="Different", email="a@example.test")
    candidates = db.find_duplicate_candidates(first)
    assert [item["contact"]["id"] for item in candidates] == [matching]
    assert same_name not in [item["contact"]["id"] for item in candidates]


def test_merge_moves_tasks_and_keeps_missing_values(db):
    fair = db.create_fair("Messe")
    keep = db.create_contact(fair, "Manuell", name="Ada", email="a@example.test")
    duplicate = db.create_contact(fair, "Manuell", phone="+49 123")
    task = db.create_task("Folgen", fair_id=fair, contact_id=duplicate)
    db.merge_contacts(keep, duplicate)
    assert db.get_contact(duplicate) is None
    assert db.get_contact(keep)["phone"] == "+49 123"
    assert db.list_tasks(fair)[0]["id"] == task and db.list_tasks(fair)[0]["contact_id"] == keep


def test_checklist_is_scoped_to_fair(db):
    fair = db.create_fair("Messe")
    item = db.create_checklist_item(fair, "Stand aufbauen", "preparation")
    assert db.list_checklist_items(fair)[0]["id"] == item
    db.set_checklist_done(item, True)
    assert db.list_checklist_items(fair)[0]["done"] == 1


def test_score_is_based_on_documented_data(db):
    fair = db.create_fair("Messe")
    contact = db.create_contact(fair, "Manuell", name="Ada", status="Interessiert", notes="Bitte Angebot senden")
    db.create_task("Angebot", fair_id=fair, contact_id=contact)
    result = db.score_contact(contact)
    assert result["score"] == 55
    assert "offener nächster Schritt" in result["reasons"]
