"""Druckfreundlicher PDF-Messebericht aus den lokalen Anwendungsdaten."""
from datetime import datetime
from textwrap import wrap

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure


def _page(title):
    fig = Figure(figsize=(8.27, 11.69))  # A4
    ax = fig.add_axes((.08, .07, .84, .86)); ax.axis("off")
    ax.text(0, 1, title, fontsize=20, fontweight="bold", color="#FF8200", va="top")
    ax.plot((0, 1), (.955, .955), color="#FF8200", lw=2)
    return fig, ax


def _lines(ax, lines, y=.91, size=10):
    for line in lines:
        for part in wrap(str(line), 100) or [""]:
            ax.text(0, y, part, fontsize=size, va="top", color="#000000")
            y -= .026
    return y


def generate_fair_report(db, fair_id, path):
    fair = next((item for item in db.list_fairs(include_archived=True) if item["id"] == fair_id), None)
    if not fair: raise ValueError("Messe nicht gefunden.")
    contacts = db.search_contacts(fair_id=fair_id)
    stats = db.dashboard_stats(fair_id)
    # Hohe Bewertungen/Status zuerst, danach Name: dokumentierte und stabile Sortierung.
    contacts.sort(key=lambda c: (-(c.get("lead_score") or 0), c.get("name") or "", c["id"]))
    with PdfPages(path) as pdf:
        fig, ax = _page("Messebericht")
        _lines(ax, [fair["name"], fair.get("location") or "Ort: keine Angabe", f"Zeitraum: {fair.get('start_date') or 'keine Angabe'} – {fair.get('end_date') or 'keine Angabe'}", "", f"Exportiert am: {datetime.now():%d.%m.%Y %H:%M}", "", "Zusammenfassung", f"{len(contacts)} Kontakte, {stats['companies']} Unternehmen", f"{stats['tasks_open']} offene Nachfassaktionen, davon {stats['tasks_overdue']} überfällig."], size=12)
        pdf.savefig(fig); fig.clear()
        fig, ax = _page("Auswertung")
        by_status = stats["by_status"]
        _lines(ax, ["Datengrundlage: alle Kontakte der ausgewählten Messe.", "", "Kontakte nach Status:"] + [f"• {name}: {count}" for name, count in by_status.items()] + ["", "Hinweis: Fehlende Angaben wurden nicht geschätzt."], size=11)
        pdf.savefig(fig); fig.clear()
        for number, contact in enumerate(contacts, 1):
            fig, ax = _page(f"Kontakt {number}: {contact.get('name') or 'Ohne Namen'}")
            tasks = db.list_tasks(contact_id=contact["id"])
            addresses = db.list_contact_addresses(contact["id"])
            channels = db.list_contact_channels(contact["id"])
            lines = [f"Firma: {contact.get('company') or 'Keine Angabe vorhanden'}", f"Position: {contact.get('position') or 'Keine Angabe vorhanden'}", f"E-Mail: {contact.get('email') or 'Keine Angabe vorhanden'}", f"Telefon: {contact.get('phone') or 'Keine Angabe vorhanden'}"]
            lines += [f"{c['channel_type'].title()} ({c.get('label') or 'weitere Angabe'}): {c['value']}" for c in channels]
            lines += [f"Adresse: {a.get('street') or ''}, {a.get('postal_code') or ''} {a.get('city') or ''}, {a.get('country') or ''}" for a in addresses]
            lines += ["", f"Lead-Bewertung: {contact.get('lead_score') if contact.get('lead_score') is not None else 'nicht bewertet'}", f"Begründung: {contact.get('lead_score_reason') or 'Keine Angabe vorhanden'}", "", "Notizen:", contact.get("notes") or "Keine Angabe vorhanden", "", "Nachfassaktionen:"]
            lines += [f"• {t['title']} – {t['status']}, fällig: {t.get('due_date') or 'keine Angabe'}" for t in tasks] or ["Keine Angabe vorhanden"]
            _lines(ax, lines)
            pdf.savefig(fig); fig.clear()
    return len(contacts)
