"""CRUD für benutzerdefinierte Felder (pro Messe oder global)."""
from __future__ import annotations

import json
import re
from datetime import datetime


def list_fields(db, fair_id=None, entity_type="contact", active_only=True):
    sql = "SELECT * FROM custom_fields WHERE entity_type=?"
    params = [entity_type]
    if fair_id is not None:
        sql += " AND (fair_id IS NULL OR fair_id=?)"
        params.append(fair_id)
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY sort_order, label"
    with db._lock:
        rows = db.conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d["options_json"]) if d.get("options_json") else []
        result.append(d)
    return result


def create_field(db, label: str, field_type: str = "text",
                 entity_type: str = "contact", fair_id: int | None = None,
                 options: list[str] | None = None,
                 required: bool = False, sort_order: int = 100,
                 field_key: str | None = None) -> int:
    label = (label or "").strip()
    if not label:
        raise ValueError("Bezeichnung erforderlich.")
    if field_type not in ("text", "number", "date", "select",
                          "checkbox", "multiline"):
        raise ValueError("Ungültiger Feldtyp.")
    key = field_key or re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    key = key[:64] or "field"

    # Schutz vor doppelten Feldern (SQLite erlaubt mehrere NULL in UNIQUE)
    with db._lock:
        if fair_id is None:
            existing = db.conn.execute(
                "SELECT id FROM custom_fields "
                "WHERE fair_id IS NULL AND entity_type=? AND field_key=?",
                (entity_type, key)).fetchone()
        else:
            existing = db.conn.execute(
                "SELECT id FROM custom_fields "
                "WHERE fair_id=? AND entity_type=? AND field_key=?",
                (fair_id, entity_type, key)).fetchone()
    if existing:
        raise ValueError(f"Ein Feld mit Schlüssel „{key}“ existiert bereits.")

    options_json = json.dumps(options or [], ensure_ascii=False)
    now = datetime.now().isoformat(timespec="seconds")
    with db._lock:
        cur = db.conn.execute(
            """INSERT INTO custom_fields
               (fair_id, entity_type, field_key, label, field_type,
                options_json, required, sort_order, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (fair_id, entity_type, key, label, field_type, options_json,
             int(required), int(sort_order), now))
        db.conn.commit()
        return cur.lastrowid


def update_field(db, field_id: int, **kw):
    allowed = {"label", "field_type", "options", "required",
               "sort_order", "active"}
    sets, params = [], []
    for k, v in kw.items():
        if k not in allowed:
            continue
        if k == "options":
            sets.append("options_json=?")
            params.append(json.dumps(v, ensure_ascii=False))
        elif k in ("required", "active"):
            sets.append(f"{k}=?")
            params.append(int(v))
        else:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return
    params.append(field_id)
    with db._lock:
        db.conn.execute(
            f"UPDATE custom_fields SET {', '.join(sets)} WHERE id=?", params)
        db.conn.commit()


def delete_field(db, field_id: int):
    with db._lock:
        db.conn.execute("DELETE FROM custom_fields WHERE id=?", (field_id,))
        db.conn.commit()


def get_values(db, contact_id: int | None = None,
               company_id: int | None = None) -> dict[int, str]:
    if contact_id is None and company_id is None:
        return {}
    where = "contact_id=?" if contact_id is not None else "company_id=?"
    arg = contact_id if contact_id is not None else company_id
    with db._lock:
        rows = db.conn.execute(
            f"SELECT field_id, value FROM custom_field_values WHERE {where}",
            (arg,)).fetchall()
    return {r["field_id"]: r["value"] for r in rows}


def set_values(db, values: dict[int, str],
               contact_id: int | None = None,
               company_id: int | None = None):
    now = datetime.now().isoformat(timespec="seconds")
    with db._lock:
        for field_id, value in values.items():
            if contact_id is not None:
                db.conn.execute(
                    """INSERT INTO custom_field_values
                       (field_id, contact_id, value, updated_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(field_id, contact_id) DO UPDATE SET
                         value=excluded.value, updated_at=excluded.updated_at""",
                    (field_id, contact_id, value, now))
            elif company_id is not None:
                db.conn.execute(
                    """INSERT INTO custom_field_values
                       (field_id, company_id, value, updated_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(field_id, company_id) DO UPDATE SET
                         value=excluded.value, updated_at=excluded.updated_at""",
                    (field_id, company_id, value, now))
        db.conn.commit()


def validate_values(fields: list[dict], values: dict[int, str]) -> list[str]:
    """Prüft Pflichtfelder und Auswahlwerte; liefert Fehlermeldungen."""
    errors = []
    for field in fields:
        if field["required"] and not (values.get(field["id"]) or "").strip():
            errors.append(f"Pflichtfeld fehlt: {field['label']}")
        if (field["field_type"] == "select" and field["options"]
                and values.get(field["id"])):
            if values[field["id"]] not in field["options"]:
                errors.append(
                    f"„{field['label']}“: Wert nicht in Auswahl.")
        if field["field_type"] == "number" and values.get(field["id"]):
            try:
                float(values[field["id"]])
            except ValueError:
                errors.append(f"„{field['label']}“: keine Zahl.")
    return errors