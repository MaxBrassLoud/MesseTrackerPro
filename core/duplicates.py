"""Dubletten-Erkennung und Merge für Kontakte und Firmen."""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _norm_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _norm_text(value: str) -> str:
    return " ".join(t for t in re.split(r"\s+", (value or "").strip().lower()) if t)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _iter_contacts(db):
    with db._lock:
        rows = db.conn.execute("SELECT * FROM contacts ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _dismissed_pairs(db):
    with db._lock:
        rows = db.conn.execute(
            "SELECT contact_a, contact_b FROM duplicate_dismissals").fetchall()
    return {tuple(sorted((r["contact_a"], r["contact_b"]))) for r in rows}


def find_similar_contacts(db, contact: dict, min_score: float = 0.0):
    """Liefert [(other_contact, reasons:set[str], score:float), …].

    reasons enthält: 'email', 'email_local_part', 'phone', 'phone_suffix',
                    'name', 'company'
    """
    cid = contact.get("id", -1)
    dismissed = _dismissed_pairs(db)
    contact_email = _norm_email(contact.get("email"))
    contact_phone = _norm_phone(contact.get("phone"))
    contact_name = _norm_text(contact.get("name"))
    contact_company = _norm_text(contact.get("company"))
    contact_external = contact.get("external_id")

    results = []
    for other in _iter_contacts(db):
        if other["id"] == cid:
            continue
        if cid != -1 and tuple(sorted((cid, other["id"]))) in dismissed:
            continue
        if contact_external and other.get("external_id") == contact_external:
            continue

        reasons: set[str] = set()
        max_sim = 0.0

        o_email = _norm_email(other.get("email"))
        if contact_email and o_email:
            if contact_email == o_email:
                reasons.add("email")
                max_sim = max(max_sim, 1.0)
            else:
                lp1, _, dom1 = contact_email.partition("@")
                lp2, _, dom2 = o_email.partition("@")
                if lp1 and lp1 == lp2 and dom1 and dom2 and dom1 != dom2:
                    reasons.add("email_local_part")
                    max_sim = max(max_sim, 0.8)

        o_phone = _norm_phone(other.get("phone"))
        if contact_phone and o_phone:
            if contact_phone == o_phone:
                reasons.add("phone")
                max_sim = max(max_sim, 1.0)
            elif (len(contact_phone) >= 8 and len(o_phone) >= 8 and
                  (contact_phone.endswith(o_phone[-8:]) or
                   o_phone.endswith(contact_phone[-8:]))):
                reasons.add("phone_suffix")
                max_sim = max(max_sim, 0.7)

        o_name = _norm_text(other.get("name"))
        if contact_name and o_name:
            sim = _similarity(contact_name, o_name)
            if sim >= 0.85:
                reasons.add("name")
                max_sim = max(max_sim, sim)

        o_company = _norm_text(other.get("company"))
        if contact_company and o_company:
            sim = _similarity(contact_company, o_company)
            if sim >= 0.85:
                reasons.add("company")
                max_sim = max(max_sim, sim)

        if reasons and max_sim >= min_score:
            results.append((other, reasons, max_sim))

    results.sort(key=lambda r: -r[2])
    return results


def dismiss_duplicate_pair(db, contact_a: int, contact_b: int,
                           dismissed_by: int | None = None):
    a, b = sorted((int(contact_a), int(contact_b)))
    now = datetime.now().isoformat(timespec="seconds")
    with db._lock:
        db.conn.execute(
            """INSERT OR IGNORE INTO duplicate_dismissals
               (contact_a, contact_b, dismissed_by, dismissed_at)
               VALUES (?,?,?,?)""", (a, b, dismissed_by, now))
        db.conn.commit()


def merge_contacts_keep_richer(db, keep_id: int, duplicate_id: int) -> dict:
    """Führt duplicate_id in keep_id zusammen – ohne Datenverlust."""
    keep = db.get_contact(keep_id)
    dup = db.get_contact(duplicate_id)
    if not keep or not dup:
        raise ValueError("Beide Kontakte müssen existieren.")
    if keep_id == duplicate_id:
        raise ValueError("Kontakte sind identisch.")

    merged: dict[str, str] = {}
    for field in ("name", "company", "position", "phone", "email", "notes"):
        cur = (keep.get(field) or "").strip()
        new = (dup.get(field) or "").strip()
        if not cur and new:
            merged[field] = new

    if merged:
        db.update_contact(keep_id, **merged)

    if not keep.get("company_id") and dup.get("company_id"):
        with db._lock:
            db.conn.execute(
                "UPDATE contacts SET company_id=? WHERE id=?",
                (dup["company_id"], keep_id))
            db.conn.commit()

    with db._lock:
        for table in ("follow_up_tasks", "contact_events",
                      "contact_addresses", "contact_channels"):
            try:
                db.conn.execute(
                    f"UPDATE {table} SET contact_id=? WHERE contact_id=?",
                    (keep_id, duplicate_id))
            except Exception:
                pass
        db.conn.execute(
            """DELETE FROM custom_field_values
               WHERE contact_id=? AND field_id IN (
                   SELECT field_id FROM custom_field_values
                   WHERE contact_id=?)""", (duplicate_id, keep_id))
        db.conn.execute(
            "UPDATE custom_field_values SET contact_id=? WHERE contact_id=?",
            (keep_id, duplicate_id))
        db.conn.execute(
            """DELETE FROM duplicate_dismissals
               WHERE contact_a=? OR contact_b=?""",
            (duplicate_id, duplicate_id))
        db.conn.execute(
            """INSERT INTO contact_events
               (contact_id, event_type, details, created_at)
               VALUES (?,?,?,?)""",
            (keep_id, "merged",
             f"Zusammengeführt mit Kontakt #{duplicate_id}"
             + (f" (übernommen: {', '.join(merged)})" if merged else ""),
             datetime.now().isoformat(timespec="seconds")))
        db.conn.commit()

    db.delete_contact(duplicate_id)
    return merged


def company_similarity_warning(db, contact: dict) -> list[dict]:
    """Prüft Firma gegen bestehende Unternehmen und liefert Hinweise."""
    company = _norm_text(contact.get("company"))
    if not company:
        return []
    hints = []
    with db._lock:
        rows = db.conn.execute(
            "SELECT id, name FROM companies").fetchall()
    for row in rows:
        sim = _similarity(company, _norm_text(row["name"]))
        if sim >= 0.85:
            hints.append({"company_id": row["id"],
                          "name": row["name"],
                          "similarity": round(sim, 3)})
    hints.sort(key=lambda h: -h["similarity"])
    return hints