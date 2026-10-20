import csv
from pathlib import Path

from core.contact_extras import get_contact_address, get_contact_website


EXPORT_COLUMNS = [
    ("id", "Kontakt-ID"),
    ("name", "Name"),
    ("company", "Firma"),
    ("position", "Position"),
    ("phone", "Telefon"),
    ("email", "E-Mail"),
    ("website", "Webseite"),
    ("address", "Adresse"),
    ("status", "Kundenstatus"),
    ("notes", "Notizen"),
    ("employee_name", "Mitarbeiter"),
    ("fair_name", "Messe"),
    ("fair_day_date", "Messetag"),
    ("created_at", "Erfassungszeitpunkt"),
    ("source", "Datenquelle"),
    ("card_image_path", "Visitenkartenbild"),
]


def export_contacts_csv(db, fair_id, path, status=None, employee_id=None, text=""):
    from core import custom_fields as cf

    rows = db.search_contacts(fair_id=fair_id, status=status,
                              employee_id=employee_id, text=text)
    fairs = {f["id"]: f["name"] for f in db.list_fairs(include_archived=True)}
    emps = {e["id"]: e["name"] for e in db.list_employees()}
    days = {}
    for fd in db.list_fair_days(fair_id):
        days[fd["id"]] = fd["day_date"]

    fields = cf.list_fields(db, fair_id=fair_id,
                            entity_type="contact", active_only=True)
    extra_cols = [("cf_" + str(f["id"]), f["label"]) for f in fields]
    all_cols = EXPORT_COLUMNS + extra_cols

    enriched = []
    for r in rows:
        base = {
            **r,
            "fair_name": fairs.get(r["fair_id"], ""),
            "employee_name": emps.get(r["employee_id"], ""),
            "fair_day_date": days.get(r["fair_day_id"], ""),
            "website": get_contact_website(db, r),
            "address": get_contact_address(db, r),
        }
        vals = cf.get_values(db, contact_id=r["id"])
        for f in fields:
            base["cf_" + str(f["id"])] = vals.get(f["id"], "")
        enriched.append(base)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow([label for _, label in all_cols])
        for r in enriched:
            w.writerow([r.get(k, "") for k, _ in all_cols])
    return len(enriched)