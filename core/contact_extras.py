"""Helfer zum Speichern/Lesen von Adresse und Webseite eines Kontakts.

Diese Felder liegen nicht als Spalten in `contacts`, sondern werden in
`companies.address`/`companies.website` (bevorzugt, wenn eine Firma
zugeordnet ist) bzw. in `contact_addresses`/`contact_channels`
(Fallback, wenn keine Firma existiert) abgelegt.
"""
from __future__ import annotations

from datetime import datetime


def get_contact_address(db, contact: dict) -> str:
    """Liefert die beste verfügbare Adresse als einzeiligen String."""
    if not contact:
        return ""
    company_id = contact.get("company_id")
    if company_id:
        try:
            company = db.get_company(company_id)
            if company and company.get("address"):
                return company["address"]
        except Exception:
            pass
    try:
        addresses = db.list_contact_addresses(contact["id"])
    except Exception:
        addresses = []
    if addresses:
        a = addresses[0]
        return ", ".join(part for part in (
            a.get("street"),
            " ".join(p for p in (a.get("postal_code"), a.get("city")) if p),
            a.get("country"),
        ) if part)
    return ""


def get_contact_website(db, contact: dict) -> str:
    """Liefert die bevorzugte Webseite (Firma zuerst, dann Kanal)."""
    if not contact:
        return ""
    company_id = contact.get("company_id")
    if company_id:
        try:
            company = db.get_company(company_id)
            if company and company.get("website"):
                return company["website"]
        except Exception:
            pass
    try:
        for ch in db.list_contact_channels(contact["id"]):
            if ch.get("channel_type") == "website" and ch.get("value"):
                return ch["value"]
    except Exception:
        pass
    return ""


def _update_company_website(db, company_id: int, website: str):
    now = datetime.now().isoformat(timespec="seconds")
    with db._lock:
        db.conn.execute(
            "UPDATE companies SET website=?, updated_at=? WHERE id=?",
            (website, now, company_id))
        db.conn.commit()


def set_contact_extras(db, contact_id: int, address: str = "",
                       website: str = ""):
    """Speichert Adresse und/oder Webseite zu einem bereits existierenden
    Kontakt – ohne bestehende Daten zu überschreiben, wenn der jeweilige
    Wert leer ist.
    """
    if not contact_id:
        return
    contact = db.get_contact(contact_id)
    if not contact:
        return

    company_id = contact.get("company_id")

    # ---- Adresse ----
    if address:
        if company_id:
            try:
                db.set_company_address(company_id, address)
            except Exception:
                pass
        else:
            try:
                db.add_contact_address(contact_id, street=address)
            except Exception:
                pass

    # ---- Webseite ----
    if not website:
        return

    if company_id:
        try:
            _update_company_website(db, company_id, website)
        except Exception:
            pass

    existing_channel = None
    try:
        for ch in db.list_contact_channels(contact_id):
            if ch.get("channel_type") == "website":
                existing_channel = ch
                break
    except Exception:
        pass

    try:
        if existing_channel:
            with db._lock:
                db.conn.execute(
                    "UPDATE contact_channels SET value=? WHERE id=?",
                    (website, existing_channel["id"]))
                db.conn.commit()
        else:
            db.add_contact_channel(
                contact_id, "website", website, "Webseite", True)
    except Exception:
        pass