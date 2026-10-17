import csv
from pathlib import Path


EXPORT_COLUMNS = [
    ("id", "Kontakt-ID"),
    ("name", "Name"),
    ("company", "Firma"),
    ("position", "Position"),
    ("phone", "Telefon"),
    ("email", "E-Mail"),
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
    rows = db.search_contacts(fair_id=fair_id, status=status,
                              employee_id=employee_id, text=text)
    # Anreichern
    fairs = {f["id"]: f["name"] for f in db.list_fairs(include_archived=True)}
    emps = {e["id"]: e["name"] for e in db.list_employees()}
    days = {}
    for fd in db.list_fair_days(fair_id):
        days[fd["id"]] = fd["day_date"]
    enriched = []
    for r in rows:
        enriched.append({
            **r,
            "fair_name": fairs.get(r["fair_id"], ""),
            "employee_name": emps.get(r["employee_id"], ""),
            "fair_day_date": days.get(r["fair_day_id"], ""),
        })
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow([label for _, label in EXPORT_COLUMNS])
        for r in enriched:
            w.writerow([r.get(k, "") for k, _ in EXPORT_COLUMNS])
    return len(enriched)