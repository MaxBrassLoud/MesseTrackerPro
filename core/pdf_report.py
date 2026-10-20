"""Druckfreundlicher PDF-Messebericht aus den lokalen Anwendungsdaten."""
from datetime import datetime
from textwrap import wrap

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from core.contact_extras import get_contact_address, get_contact_website


# Geometrie / Layout
_LINE_HEIGHT = 0.028      # Zeilenhöhe in Achsen-Koordinaten
_TEXT_TOP = 0.91          # Startposition Body-Text (unter dem Divider)
_TEXT_BOTTOM = 0.03       # Unterkante – darunter neue Seite
_FONT_SIZE = 10
_MAX_CHARS = 95           # Zeichen pro Zeile bei Schriftgröße 10


def _new_page(title):
    """A4-Seite mit Titel + Trennlinie, Achsen fest auf 0–1 gesetzt."""
    fig = Figure(figsize=(8.27, 11.69))
    ax = fig.add_axes((.08, .07, .84, .86))
    # FIX: feste Limits verhindern Auto-Scaling durch ax.plot / ax.text
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0, 0.97, title, fontsize=20, fontweight="bold",
            color="#FF8200", va="top")
    ax.plot((0, 1), (.925, .925), color="#FF8200", lw=2)
    return fig, ax


def _wrap_line(text, max_chars=_MAX_CHARS):
    if not text:
        return [""]
    return wrap(str(text), max_chars) or [""]


def _paginate(title, raw_lines, pdf):
    """Rendert eine Liste von Zeilen – bei Bedarf über mehrere Seiten."""
    # Erst alle Zeilen umbrechen (auch lange Notizen)
    all_lines = []
    for line in raw_lines:
        all_lines.extend(_wrap_line(line))

    total = len(all_lines)
    lines_per_page = max(1, int((_TEXT_TOP - _TEXT_BOTTOM) / _LINE_HEIGHT))

    offset = 0
    first_page = True
    while offset < total or first_page:
        page_title = title if first_page else f"{title} (Fortsetzung)"
        fig, ax = _new_page(page_title)
        first_page = False

        y = _TEXT_TOP
        end = min(offset + lines_per_page, total)
        while offset < end:
            ax.text(0, y, all_lines[offset], fontsize=_FONT_SIZE,
                    va="top", color="#000000")
            y -= _LINE_HEIGHT
            offset += 1

        pdf.savefig(fig)
        fig.clear()


def _format_address(address):
    """Adress-Dict → einzeiliger String, robust bei None-Feldern."""
    if not address:
        return ""
    parts = []
    if address.get("street"):
        parts.append(address["street"])
    plz_city = " ".join(
        p for p in (address.get("postal_code"), address.get("city")) if p)
    if plz_city:
        parts.append(plz_city)
    if address.get("country"):
        parts.append(address["country"])
    return ", ".join(parts)


def generate_fair_report(db, fair_id, path):
    fair = next((item for item in db.list_fairs(include_archived=True)
                 if item["id"] == fair_id), None)
    if not fair:
        raise ValueError("Messe nicht gefunden.")

    contacts = db.search_contacts(fair_id=fair_id)
    stats = db.dashboard_stats(fair_id)
    contacts.sort(key=lambda c: ((c.get("name") or "").lower(),
                                 c.get("id") or 0))

    try:
        employees = {e["id"]: e["name"] for e in db.list_employees()}
    except Exception:
        employees = {}

    with PdfPages(path) as pdf:
        # ---------- Titelseite ----------
        title_lines = [
            f"Messe: {fair.get('name') or '—'}",
            f"Ort: {fair.get('location') or 'keine Angabe'}",
            f"Zeitraum: {fair.get('start_date') or '—'} bis "
            f"{fair.get('end_date') or '—'}",
            "",
            f"Exportiert am: {datetime.now():%d.%m.%Y %H:%M}",
            "",
            "Zusammenfassung:",
            f"• {len(contacts)} Kontakte erfasst",
            f"• {stats.get('companies', 0)} unterschiedliche Unternehmen",
            f"• {stats.get('tasks_open', 0)} offene Nachfassaktionen "
            f"({stats.get('tasks_overdue', 0)} überfällig)",
        ]
        _paginate("Messebericht", title_lines, pdf)

        # ---------- Auswertung ----------
        status_lines = ["Kontakte nach Status:"]
        by_status = stats.get("by_status", {}) or {}
        if by_status:
            for name, count in by_status.items():
                status_lines.append(f"• {name}: {count}")
        else:
            status_lines.append("• Keine Statusdaten vorhanden.")
        status_lines.append("")
        status_lines.append(
            "Hinweis: Fehlende Angaben wurden nicht geschätzt.")
        _paginate("Auswertung", status_lines, pdf)

        # ---------- Einzelkontakte ----------
        for number, contact in enumerate(contacts, 1):
            title = (f"Kontakt {number}: "
                     f"{contact.get('name') or 'Ohne Namen'}")
            lines = []

            # Ansprechpartner
            lines.append("Ansprechpartner")
            lines.append(f"Name: {contact.get('name') or '—'}")
            lines.append(f"Position: {contact.get('position') or '—'}")

            # Kontaktdaten
            lines.append("")
            lines.append("Kontaktdaten")
            lines.append(f"E-Mail: {contact.get('email') or '—'}")
            lines.append(f"Telefon: {contact.get('phone') or '—'}")

            try:
                website = get_contact_website(db, contact)
            except Exception:
                website = ""
            lines.append(f"Webseite: {website or '—'}")

            try:
                address = get_contact_address(db, contact)
            except Exception:
                address = ""
            lines.append(f"Adresse: {address or '—'}")

            contact_id = contact.get("id")

            # Weitere Kontaktwege (Kanäle)
            try:
                channels = db.list_contact_channels(contact_id)
            except Exception:
                channels = []
            if channels:
                lines.append("")
                lines.append("Weitere Kontaktwege:")
                for ch in channels:
                    label = (ch.get("label")
                             or (ch.get("channel_type") or "").title())
                    lines.append(
                        f"• {label}: {ch.get('value') or '—'}")

            # Weitere Adressen am Kontakt
            try:
                addresses = db.list_contact_addresses(contact_id)
            except Exception:
                addresses = []
            if addresses:
                lines.append("")
                lines.append("Weitere Adressen:")
                for addr in addresses:
                    formatted = _format_address(addr)
                    if formatted:
                        lines.append(
                            f"• {addr.get('label') or 'Adresse'}: "
                            f"{formatted}")

            # Firma & weitere Ansprechpartner
            company_id = contact.get("company_id")
            if company_id:
                company = None
                try:
                    company = db.get_company(company_id)
                except Exception:
                    pass
                if company:
                    lines.append("")
                    lines.append("Firma")
                    lines.append(f"Name: {company.get('name') or '—'}")
                    if company.get("address"):
                        lines.append(
                            f"Adresse: {company['address']}")
                    if company.get("phone"):
                        lines.append(
                            f"Telefon: {company['phone']}")
                    if company.get("website"):
                        lines.append(
                            f"Webseite: {company['website']}")

                    try:
                        others = [
                            p for p in db.company_contacts(company_id)
                            if p.get("id") != contact_id]
                    except Exception:
                        others = []
                    if others:
                        lines.append("")
                        lines.append("Weitere Ansprechpartner:")
                        for p in others:
                            pos = p.get("position")
                            extra = f" ({pos})" if pos else ""
                            lines.append(
                                f"• {p.get('name') or '?'}{extra}")

            # Erfassungs-Metadaten
            lines.append("")
            lines.append("Erfassung")
            lines.append(f"Quelle: {contact.get('source') or '—'}")
            lines.append(f"Status: {contact.get('status') or '—'}")
            lines.append(
                f"Erfasst am: {contact.get('created_at') or '—'}")
            emp_id = contact.get("employee_id")
            if emp_id and emp_id in employees:
                lines.append(f"Erfasst von: {employees[emp_id]}")

            # Notizen
            lines.append("")
            lines.append("Notizen")
            lines.append(
                contact.get("notes") or "Keine Angaben vorhanden.")

            # Nachfassaktionen
            try:
                tasks = db.list_tasks(contact_id=contact_id)
            except Exception:
                tasks = []
            lines.append("")
            lines.append("Nachfassaktionen")
            if tasks:
                for t in tasks:
                    due = t.get("due_date") or "ohne Termin"
                    status = t.get("status") or "?"
                    prio = t.get("priority") or ""
                    lines.append(
                        f"• {t.get('title') or '?'} – {status} "
                        f"({prio}), fällig: {due}")
            else:
                lines.append("Keine Nachfassaktionen hinterlegt.")

            # Historie
            try:
                history = db.contact_history(contact_id)
            except Exception:
                history = []
            if history:
                lines.append("")
                lines.append("Letzte Aktivitäten")
                for event in history[:10]:
                    ts = event.get("created_at") or ""
                    if ts and len(ts) >= 16:
                        ts = ts[:16].replace("T", " ")
                    etype = event.get("event_type") or "?"
                    details = event.get("details") or ""
                    text = f"• {ts}: {etype}"
                    if details:
                        text += f" – {details}"
                    lines.append(text)

            _paginate(title, lines, pdf)

    return len(contacts)