# ui/pages/contacts.py
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
    QFormLayout, QTextEdit, QDialogButtonBox, QScrollArea,
    QSizePolicy, QHeaderView, QAbstractItemView, QTabWidget,
    QListWidget, QListWidgetItem, QCheckBox, QFrame, QGroupBox)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

from ui.widgets import FullSizeImageDialog
from core.duplicates import (
    find_similar_contacts, company_similarity_warning,
)
from core import custom_fields as cf
from core.contact_extras import (
    get_contact_address, get_contact_website, set_contact_extras,
)
from ui.dialogs.merge_dialog import MergeContactDialog


def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


def _best_address_for_contact(ctx, contact):
    """Firmenadresse bevorzugt, sonst Kontaktadresse, sonst ''."""
    return get_contact_address(ctx.db, contact)


# ======================================================================
# Bearbeiten-Dialog
# ======================================================================
class ContactDialog(QDialog):
    """Dialog zum Anlegen/Bearbeiten eines Ansprechpartners.

    Wichtig:
    - Die Firma wird anhand des Feldes „Firma" automatisch erzeugt.
    - „Adresse" wird bevorzugt an der Firma gespeichert.
    - „Webseite" wird bevorzugt an der Firma gespeichert, sonst als
      Kontaktweg vom Typ 'website'.
    - Position/Telefon/E-Mail gehören immer zum Ansprechpartner.
    - Eigene Felder (pro Messe konfigurierbar) werden dynamisch eingebunden.
    """

    def __init__(self, parent, contact=None, ctx=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(
            "Ansprechpartner bearbeiten" if contact
            else "Ansprechpartner anlegen")
        self.setMinimumWidth(460)
        form = QFormLayout(self)

        hint = QLabel(
            "Der Kontakt ist ein <b>Ansprechpartner</b> einer Firma. "
            "Die Firma wird aus dem Feld „Firma“ automatisch angelegt, "
            "falls sie noch nicht existiert. Die <b>Adresse</b> und "
            "<b>Webseite</b> gehören zur Firma (Fallback: Kontakt). "
            "<b>Position</b>, <b>Telefon</b> und <b>E-Mail</b> gehören "
            "zum Ansprechpartner.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color:#888;font-size:9pt;padding-bottom:6px;")
        form.addRow(hint)

        self.inp = {}
        field_labels = [
            ("name", "Name"),
            ("company", "Firma"),
            ("position", "Position"),
            ("phone", "Telefon"),
            ("email", "E-Mail"),
            ("website", "Webseite"),
            ("notes", "Notizen"),
        ]
        for key, label in field_labels:
            if key == "notes":
                w = QTextEdit()
                w.setMinimumHeight(70)
                if contact:
                    w.setPlainText(contact.get("notes") or "")
            elif key == "website":
                w = QLineEdit()
                if contact:
                    w.setText(get_contact_website(ctx.db, contact))
            else:
                w = QLineEdit()
                if contact:
                    w.setText(contact.get(key) or "")
            form.addRow(label, w)
            self.inp[key] = w

        self.address = QLineEdit()
        self.address.setPlaceholderText(
            "Straße, PLZ Ort, Land – wird an der Firma gespeichert")
        if contact:
            existing = _best_address_for_contact(ctx, contact)
            if existing:
                self.address.setText(existing)
        form.addRow("Firmenadresse", self.address)

        statuses = [s["name"]
                    for s in ctx.db.list_statuses(active_only=True)]
        if contact and contact.get("status") and \
                contact["status"] not in statuses:
            statuses.append(contact["status"])
        if not statuses:
            statuses = ["—"]
        self.status = QComboBox()
        self.status.addItems(statuses)
        if contact:
            idx = self.status.findText(contact["status"])
            if idx >= 0:
                self.status.setCurrentIndex(idx)
        form.addRow("Status", self.status)

        # ---- Eigene Felder ----
        self._custom_widgets: dict[int, object] = {}
        self._custom_fields = []
        try:
            self._custom_fields = cf.list_fields(
                ctx.db, fair_id=ctx.current_fair_id,
                entity_type="contact", active_only=True)
        except Exception:
            self._custom_fields = []
        if self._custom_fields:
            form.addRow(QLabel("<b>Eigene Felder</b>"))
            existing_vals = (cf.get_values(ctx.db, contact_id=contact["id"])
                             if contact else {})
            for field in self._custom_fields:
                w = self._make_custom_widget(
                    field, existing_vals.get(field["id"], ""))
                self._custom_widgets[field["id"]] = w
                label = field["label"] + (" *" if field["required"] else "")
                form.addRow(label, w)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _make_custom_widget(self, field, value):
        ft = field["field_type"]
        if ft == "select":
            combo = QComboBox()
            combo.addItem("")
            for opt in field.get("options", []):
                combo.addItem(opt)
            idx = combo.findText(value or "")
            if idx >= 0:
                combo.setCurrentIndex(idx)
            return combo
        if ft == "checkbox":
            cb = QCheckBox()
            cb.setChecked(str(value).lower() in ("1", "true", "ja", "yes"))
            return cb
        if ft == "multiline":
            w = QTextEdit()
            w.setMinimumHeight(60)
            w.setPlainText(value or "")
            return w
        w = QLineEdit()
        w.setText(value or "")
        return w

    def _collect_custom_values(self) -> dict[int, str]:
        out = {}
        for fid, w in self._custom_widgets.items():
            if isinstance(w, QCheckBox):
                out[fid] = "1" if w.isChecked() else ""
            elif isinstance(w, QComboBox):
                out[fid] = w.currentText()
            elif isinstance(w, QTextEdit):
                out[fid] = w.toPlainText()
            else:
                out[fid] = w.text()
        return out

    def values(self):
        d = {k: (w.toPlainText() if isinstance(w, QTextEdit) else w.text())
             for k, w in self.inp.items()}
        d["status"] = self.status.currentText()
        d["address"] = self.address.text().strip()
        d["_custom_fields"] = self._collect_custom_values()
        return d


class ChannelDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Kontaktweg hinzufügen")
        form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItem("E-Mail", "email")
        self.kind.addItem("Telefon", "phone")
        self.kind.addItem("Webseite", "website")
        self.value, self.label = QLineEdit(), QLineEdit()
        self.primary = QCheckBox("Als Hauptkontaktweg verwenden")
        form.addRow("Art", self.kind)
        form.addRow("Wert *", self.value)
        form.addRow("Bezeichnung (z. B. Sekretariat)", self.label)
        form.addRow(self.primary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class AddressDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Adresse hinzufügen")
        form = QFormLayout(self)
        self.label, self.street, self.postal, self.city, self.country = (
            QLineEdit() for _ in range(5))
        self.label.setText("Geschäftlich")
        for name, field in (("Bezeichnung", self.label),
                            ("Straße / Hausnummer", self.street),
                            ("PLZ", self.postal),
                            ("Ort", self.city),
                            ("Land", self.country)):
            form.addRow(name, field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class FollowUpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Nachfassaktion anlegen")
        form = QFormLayout(self)
        self.title, self.description, self.due = (
            QLineEdit(), QTextEdit(), QLineEdit())
        self.due.setPlaceholderText("YYYY-MM-DD (optional)")
        self.priority = QComboBox()
        self.priority.addItem("Normal", "normal")
        self.priority.addItem("Hoch", "high")
        self.priority.addItem("Niedrig", "low")
        form.addRow("Aufgabe *", self.title)
        form.addRow("Beschreibung", self.description)
        form.addRow("Fällig am", self.due)
        form.addRow("Priorität", self.priority)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


# ======================================================================
# Detail-Widget – 2-Spalten-Layout
# ======================================================================
class ContactDetailWidget(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        self.current_contact = None
        self._orig_pix = None
        self._cf_box = None

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(16)

        # ==================== LINKE SPALTE ====================
        left_content = QWidget()
        lv = QVBoxLayout(left_content)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        self._left_layout = lv

        self.title = QLabel("Ansprechpartner")
        self.title.setObjectName("Title")
        self.title.setWordWrap(True)
        lv.addWidget(self.title)

        self.image_label = QLabel("Keine Visitenkarte")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(180)
        self.image_label.setMaximumHeight(320)
        self.image_label.setStyleSheet(
            "background:#000;border:1px solid #333;color:#888;")
        self.image_label.setSizePolicy(QSizePolicy.Expanding,
                                       QSizePolicy.Preferred)
        self.image_label.setCursor(Qt.ArrowCursor)
        self.image_label.mousePressEvent = self._on_image_click
        lv.addWidget(self.image_label)

        self.image_hint = QLabel("")
        self.image_hint.setStyleSheet(
            "color:#888;font-size:9pt;padding:2px;")
        self.image_hint.setAlignment(Qt.AlignCenter)
        lv.addWidget(self.image_hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setContentsMargins(0, 6, 0, 6)
        self.fields = {}
        for key, label in [
            ("name", "Name"),
            ("company", "Firma"),
            ("position", "Position"),
            ("phone", "Telefon"),
            ("email", "E-Mail"),
            ("website", "Webseite"),
            ("status", "Status"),
            ("source", "Quelle"),
            ("employee", "Erfasst von"),
            ("fair_day", "Messetag"),
            ("created_at", "Erfasst am"),
            ("address", "Firmenadresse"),
        ]:
            l = QLabel("—")
            l.setWordWrap(True)
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.fields[key] = l
            form.addRow(label + ":", l)
        lv.addLayout(form)

        notes_label = QLabel("Notizen:")
        notes_label.setStyleSheet("font-weight:600;padding-top:6px;")
        lv.addWidget(notes_label)

        self.notes_view = QTextEdit()
        self.notes_view.setReadOnly(True)
        self.notes_view.setMinimumHeight(80)
        self.notes_view.setPlaceholderText("(keine Notizen)")
        lv.addWidget(self.notes_view)

        lv.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left_content)
        left_scroll.setMinimumWidth(360)
        left_scroll.setMaximumWidth(500)
        main_h.addWidget(left_scroll, 2)

        # ==================== RECHTE SPALTE ====================
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.channels = QListWidget()
        self.addresses = QListWidget()
        self.company_people = QListWidget()
        self.tasks = QListWidget()
        self.history = QListWidget()

        activity_tab = QWidget()
        activity_layout = QVBoxLayout(activity_tab)
        activity_layout.addWidget(QLabel(
            "Nachfassaktionen (Doppelklick zum Erledigen)"))
        activity_layout.addWidget(self.tasks, 1)
        activity_layout.addWidget(QLabel("Historie / Nachrichten"))
        activity_layout.addWidget(self.history, 1)

        contact_tab = QWidget()
        cv = QVBoxLayout(contact_tab)
        cv.addWidget(QLabel(
            "Weitere E-Mail-Adressen, Telefonnummern und Webseiten "
            "(z. B. Sekretariat mit Bezeichnung)"))
        cv.addWidget(self.channels, 1)
        channel_actions = QHBoxLayout()
        self.btn_channel = QPushButton("+ Kontaktweg")
        self.btn_channel.clicked.connect(self.page.add_channel)
        self.btn_del_channel = QPushButton("Entfernen")
        self.btn_del_channel.clicked.connect(self.page.delete_channel)
        channel_actions.addWidget(self.btn_channel)
        channel_actions.addWidget(self.btn_del_channel)
        channel_actions.addStretch(1)
        cv.addLayout(channel_actions)

        cv.addWidget(QLabel("Adressen"))
        cv.addWidget(self.addresses, 1)
        address_actions = QHBoxLayout()
        self.btn_address = QPushButton("+ Adresse")
        self.btn_address.clicked.connect(self.page.add_address)
        self.btn_del_address = QPushButton("Entfernen")
        self.btn_del_address.clicked.connect(self.page.delete_address)
        address_actions.addWidget(self.btn_address)
        address_actions.addWidget(self.btn_del_address)
        address_actions.addStretch(1)
        cv.addLayout(address_actions)

        company_tab = QWidget()
        company_layout = QVBoxLayout(company_tab)

        self.company_header = QLabel("—")
        self.company_header.setWordWrap(True)
        self.company_header.setTextFormat(Qt.RichText)
        self.company_header.setStyleSheet(
            "background:#1a1a1a;border:1px solid #333;border-radius:6px;"
            "padding:10px;color:#eee;font-size:10pt;")
        company_layout.addWidget(self.company_header)

        company_layout.addWidget(QLabel(
            "Weitere Ansprechpartner derselben Firma"))
        company_layout.addWidget(self.company_people, 1)
        self.btn_company_contact = QPushButton(
            "+ Ansprechpartner für diese Firma")
        self.btn_company_contact.clicked.connect(
            self.page.new_company_contact)
        company_layout.addWidget(self.btn_company_contact)

        self.tabs.addTab(activity_tab, "Aufträge & Nachrichten")
        self.tabs.addTab(contact_tab, "Kontaktwege & Adressen")
        self.tabs.addTab(company_tab, "Firma & Ansprechpartner")
        rv.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        self.btn_edit = QPushButton("Bearbeiten")
        self.btn_edit.clicked.connect(self.page.edit)
        self.btn_delete = QPushButton("Löschen")
        self.btn_delete.setObjectName("Ghost")
        self.btn_delete.clicked.connect(self.page.delete)
        self.btn_task = QPushButton("+ Nachfassaktion")
        self.btn_task.clicked.connect(self.page.create_follow_up)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_task)
        btn_row.addWidget(self.btn_delete)
        rv.addLayout(btn_row)

        main_h.addWidget(right, 3)

        self._set_buttons_enabled(False)
        self.tasks.itemDoubleClicked.connect(self.page.toggle_task)
        self.company_people.itemDoubleClicked.connect(
            self.page.open_company_contact)

    def _set_buttons_enabled(self, enabled):
        self.btn_edit.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)
        self.btn_task.setEnabled(enabled)
        self.btn_channel.setEnabled(enabled)
        self.btn_del_channel.setEnabled(enabled)
        self.btn_address.setEnabled(enabled)
        self.btn_del_address.setEnabled(enabled)
        self.btn_company_contact.setEnabled(enabled)

    def _remove_custom_box(self):
        if self._cf_box is not None:
            try:
                self._left_layout.removeWidget(self._cf_box)
                self._cf_box.setParent(None)
                self._cf_box.deleteLater()
            except Exception:
                pass
            self._cf_box = None

    def set_contact(self, contact):
        self.current_contact = contact
        self._orig_pix = None
        self._remove_custom_box()

        if not contact:
            self.title.setText("Ansprechpartner")
            for l in self.fields.values():
                l.setText("—")
            self.notes_view.clear()
            for widget in (self.channels, self.addresses,
                           self.company_people, self.tasks, self.history):
                widget.clear()
            self.company_header.setText("—")
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Keine Visitenkarte")
            self.image_label.setCursor(Qt.ArrowCursor)
            self.image_hint.setText("")
            self._set_buttons_enabled(False)
            return

        self.title.setText(contact.get("name") or "(ohne Namen)")

        emps = {e["id"]: e["name"] for e in self.ctx.db.list_employees()}
        days = {}
        if contact.get("fair_id"):
            for d in self.ctx.db.list_fair_days(contact["fair_id"]):
                days[d["id"]] = d["day_date"]

        self.fields["name"].setText(contact.get("name") or "—")
        self.fields["company"].setText(contact.get("company") or "—")
        self.fields["position"].setText(contact.get("position") or "—")
        self.fields["phone"].setText(contact.get("phone") or "—")
        self.fields["email"].setText(contact.get("email") or "—")
        self.fields["website"].setText(
            get_contact_website(self.ctx.db, contact) or "—")
        self.fields["status"].setText(contact.get("status") or "—")
        self.fields["source"].setText(contact.get("source") or "—")
        self.fields["employee"].setText(
            emps.get(contact.get("employee_id"), "—"))
        self.fields["fair_day"].setText(
            days.get(contact.get("fair_day_id"), "—"))
        self.fields["created_at"].setText(
            _fmt_dt(contact.get("created_at", "")) or "—")

        addr = _best_address_for_contact(self.ctx, contact)
        self.fields["address"].setText(addr or "—")

        self.notes_view.setPlainText(contact.get("notes") or "")

        # Eigene Felder anzeigen
        try:
            field_defs = cf.list_fields(
                self.ctx.db,
                fair_id=contact.get("fair_id"),
                entity_type="contact", active_only=True)
            values = cf.get_values(
                self.ctx.db, contact_id=contact["id"])
        except Exception:
            field_defs, values = [], {}
        if field_defs:
            box = QGroupBox("Eigene Felder")
            fl = QFormLayout(box)
            for f in field_defs:
                v = values.get(f["id"], "") or "—"
                if f["field_type"] == "checkbox":
                    v = ("Ja" if values.get(f["id"]) in ("1", "true", "Ja")
                         else "Nein")
                lbl = QLabel(str(v))
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                fl.addRow(f["label"] + ":", lbl)
            self._left_layout.insertWidget(
                self._left_layout.count() - 1, box)
            self._cf_box = box

        self.channels.clear()
        for channel in self.ctx.db.list_contact_channels(contact["id"]):
            item = QListWidgetItem(
                f"{'★ ' if channel['is_primary'] else ''}"
                f"{channel['channel_type'].title()}: {channel['value']}"
                + (f"  –  {channel['label']}" if channel.get('label') else ""))
            item.setData(Qt.UserRole, channel["id"])
            self.channels.addItem(item)

        contact_addresses = self.ctx.db.list_contact_addresses(contact["id"])
        self.addresses.clear()
        for address in contact_addresses:
            text = ", ".join(part for part in (
                address.get("street"),
                " ".join(p for p in (address.get("postal_code"),
                                     address.get("city")) if p),
                address.get("country"),
            ) if part)
            item = QListWidgetItem(
                f"{'★ ' if address['is_primary'] else ''}"
                f"{address.get('label') or 'Adresse'}: "
                f"{text or 'Keine Angabe'}")
            item.setData(Qt.UserRole, address["id"])
            self.addresses.addItem(item)

        if contact.get("company_id"):
            company = None
            try:
                company = self.ctx.db.get_company(contact["company_id"])
            except Exception:
                company = None
            name = (company or {}).get("name") \
                or contact.get("company") or "—"
            addr_company = _best_address_for_contact(
                self.ctx, contact) or ""
            lines = [f"<b>{name}</b>"]
            if addr_company:
                lines.append(f"📍 {addr_company}")
            if company and company.get("phone"):
                lines.append(f"📞 {company['phone']}")
            if company and company.get("website"):
                lines.append(f"🌐 {company['website']}")
            self.company_header.setText("<br>".join(lines))

            self.company_people.clear()
            for person in self.ctx.db.company_contacts(
                    contact["company_id"]):
                item = QListWidgetItem(
                    (person.get("name") or "Ohne Namen")
                    + (f" – {person['position']}"
                       if person.get("position") else ""))
                item.setData(Qt.UserRole, person["id"])
                self.company_people.addItem(item)
        else:
            self.company_header.setText(
                "Keine Firma zugeordnet. Beim Bearbeiten kann über das "
                "Feld „Firma“ eine Firma angelegt werden.")
            self.company_people.clear()
            self.company_people.addItem("Keine Firma zugeordnet.")

        self.tasks.clear()
        for task in self.ctx.db.list_tasks(contact_id=contact["id"]):
            item = QListWidgetItem(
                f"{'✓' if task['status'] == 'done' else '○'} "
                f"{task['title']} · {task['priority']} · "
                f"{task.get('due_date') or 'ohne Termin'}")
            item.setData(Qt.UserRole, task["id"])
            item.setData(Qt.UserRole + 1, task["status"])
            self.tasks.addItem(item)

        self.history.clear()
        for event in self.ctx.db.contact_history(contact["id"]):
            self.history.addItem(
                f"{_fmt_dt(event['created_at'])} · "
                f"{event['event_type']}: {event.get('details') or ''}")

        self._load_image(contact.get("card_image_path"))
        self._set_buttons_enabled(True)

    def _load_image(self, path):
        if not path or not os.path.exists(path):
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Keine Visitenkarte")
            self.image_label.setCursor(Qt.ArrowCursor)
            self.image_hint.setText("")
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Bild nicht lesbar")
            self.image_label.setCursor(Qt.ArrowCursor)
            self.image_hint.setText("")
            return
        self._orig_pix = pix
        self.image_label.setCursor(Qt.PointingHandCursor)
        self.image_hint.setText("Klicken für Großansicht")
        self._refresh_image()

    def _refresh_image(self):
        if not self._orig_pix or self._orig_pix.isNull():
            return
        max_w = max(self.image_label.width() - 8, 200)
        max_h = 300
        scaled = self._orig_pix.scaled(
            max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "image_label"):
            self._refresh_image()

    def _on_image_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        if not self._orig_pix or self._orig_pix.isNull():
            return
        if not self.current_contact:
            return
        path = self.current_contact.get("card_image_path")
        if not path or not os.path.exists(path):
            return
        cards = [{"id": self.current_contact["id"], "image_path": path}]
        FullSizeImageDialog(self, cards, 0).exec_()


# ======================================================================
# Hauptseite
# ======================================================================
class ContactsPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main

        v = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Kundenkartei")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch(1)
        hint = QLabel("Doppelklick öffnet die vollflächige Kundenakte")
        hint.setStyleSheet("color:#888;font-size:9pt;")
        header.addWidget(hint)
        btn_new = QPushButton("+ Neuer Ansprechpartner")
        btn_new.clicked.connect(self.new)
        header.addWidget(btn_new)
        v.addLayout(header)

        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suche Name / Firma / E-Mail / Webseite")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.currentIndexChanged.connect(self.refresh)
        f.addWidget(self.search, 1)
        f.addWidget(self.status_filter)
        v.addLayout(f)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Name", "Firma", "E-Mail", "Status", "Erfasst"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header_t = self.table.horizontalHeader()
        header_t.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_t.setSectionResizeMode(1, QHeaderView.Stretch)
        header_t.setSectionResizeMode(2, QHeaderView.Stretch)
        header_t.setSectionResizeMode(3, QHeaderView.Stretch)
        header_t.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_t.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(self.open_full_profile)
        v.addWidget(self.table, 1)

        act = QHBoxLayout()
        self.btn_merge = QPushButton("Mit anderem Kontakt zusammenführen…")
        self.btn_merge.setObjectName("Ghost")
        self.btn_merge.clicked.connect(self.merge_selected)
        self.btn_company = QPushButton("Firmenakte öffnen")
        self.btn_company.setObjectName("Ghost")
        self.btn_company.clicked.connect(self.open_company)
        act.addWidget(self.btn_merge)
        act.addWidget(self.btn_company)
        act.addStretch(1)
        v.addLayout(act)

    def _current_employee_id(self):
        user = getattr(self.main, "user", None)
        if not user:
            return None
        try:
            emp = self.ctx.db.get_employee_by_user_id(user["id"])
        except Exception:
            return None
        return emp["id"] if emp else None

    def _rebuild_status_filter(self):
        current = self.status_filter.currentText() or "Alle Status"
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItem("Alle Status")
        for s in self.ctx.db.list_statuses(active_only=True):
            self.status_filter.addItem(s["name"])
        idx = self.status_filter.findText(current)
        self.status_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.status_filter.blockSignals(False)

    def refresh(self):
        self._rebuild_status_filter()

        if not self.ctx.current_fair_id:
            self.table.setRowCount(0)
            self._sync_profile()
            return

        status = self.status_filter.currentText()
        rows = self.ctx.db.search_contacts(
            fair_id=self.ctx.current_fair_id,
            status=status if status != "Alle Status" else None,
            text=self.search.text().strip())

        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(c.get("id") or "")))
            self.table.setItem(r, 1, QTableWidgetItem(c.get("name") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(c.get("company") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(c.get("email") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(c.get("status") or ""))
            self.table.setItem(
                r, 5, QTableWidgetItem(_fmt_dt(c.get("created_at", ""))))
        self.table.blockSignals(False)

        self._sync_profile()

    def _sync_profile(self):
        profile = getattr(self.main, "_profile_page", None)
        if profile is None or not profile.isVisible():
            return
        profile.refresh_from_db()

    def open_full_profile(self, _item=None):
        cid = self._selected_contact_id()
        contact = self.ctx.db.get_contact(cid) if cid else None
        if not contact:
            return
        self.main.open_contact_profile(contact)

    def _selected_contact_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        try:
            return int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            return None

    def _active_detail(self):
        profile = getattr(self.main, "_profile_page", None)
        if profile is not None and profile.isVisible():
            return profile.detail
        return None

    def new(self, company_name=""):
        if not self.ctx.current_fair_id:
            QMessageBox.warning(self, "Messe",
                                "Bitte zuerst eine Messe auswählen.")
            return
        d = ContactDialog(self, ctx=self.ctx)
        if company_name:
            d.inp["company"].setText(company_name)
        if not d.exec_():
            return

        vals = d.values()
        address = vals.pop("address", "")
        website = vals.pop("website", "").strip()
        cf_vals = vals.pop("_custom_fields", None) or {}

        employee_id = self._current_employee_id()

        new_id = self.ctx.db.create_contact(
            fair_id=self.ctx.current_fair_id,
            source="Manuell",
            fair_day_id=self.ctx.current_fair_day_id,
            employee_id=employee_id,
            **vals)

        # Adresse + Webseite an Firma bzw. Kontakt speichern
        try:
            set_contact_extras(
                self.ctx.db, new_id, address=address, website=website)
        except Exception:
            pass

        # Eigene Felder
        if cf_vals:
            field_defs = cf.list_fields(
                self.ctx.db, fair_id=self.ctx.current_fair_id,
                entity_type="contact", active_only=True)
            errors = cf.validate_values(field_defs, cf_vals)
            if errors:
                QMessageBox.warning(
                    self, "Eigene Felder",
                    "Bitte korrigieren:\n\n" + "\n".join(errors))
            else:
                cf.set_values(self.ctx.db, cf_vals, contact_id=new_id)

        # Dubletten-Prüfung
        fresh = self.ctx.db.get_contact(new_id)
        similar = find_similar_contacts(self.ctx.db, fresh) if fresh else []
        if similar:
            top, reasons, _score = similar[0]
            if QMessageBox.question(
                    self, "Mögliche Dublette",
                    f"Der neue Kontakt ähnelt #{top['id']} "
                    f"„{top.get('name') or '?'}“ "
                    f"({top.get('company') or 'ohne Firma'}) "
                    f"[{', '.join(sorted(reasons))}].\n\n"
                    f"Jetzt zusammenführen?",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                MergeContactDialog(self, self.ctx.db, fresh, top).exec_()
                self.refresh()
                keep_id = fresh["id"] if self.ctx.db.get_contact(fresh["id"]) \
                    else top["id"]
                self._select_contact_by_id(keep_id)
                return

        company_hints = (
            company_similarity_warning(self.ctx.db, fresh) if fresh else [])
        if company_hints:
            QMessageBox.information(
                self, "Firmen-Ähnlichkeit",
                "Es existiert bereits ein Unternehmen mit ähnlichem "
                "Namen:\n"
                f"„{company_hints[0]['name']}“ "
                f"(Ähnlichkeit {int(company_hints[0]['similarity']*100)}%).")

        self.refresh()
        self._select_contact_by_id(new_id)

    def edit(self):
        cid = self._selected_contact_id()
        if cid is None:
            QMessageBox.information(
                self, "Auswahl",
                "Bitte zuerst einen Kontakt in der Tabelle auswählen.")
            return
        c = self.ctx.db.get_contact(cid)
        if not c:
            QMessageBox.warning(self, "Nicht gefunden",
                                "Der Kontakt existiert nicht mehr.")
            self.refresh()
            return
        d = ContactDialog(self, contact=c, ctx=self.ctx)
        if not d.exec_():
            return

        vals = d.values()
        address = vals.pop("address", "")
        website = vals.pop("website", "").strip()
        cf_vals = vals.pop("_custom_fields", None) or {}
        self.ctx.db.update_contact(cid, **vals)

        try:
            set_contact_extras(
                self.ctx.db, cid, address=address, website=website)
        except Exception:
            pass

        if cf_vals:
            field_defs = cf.list_fields(
                self.ctx.db, fair_id=self.ctx.current_fair_id,
                entity_type="contact", active_only=True)
            errors = cf.validate_values(field_defs, cf_vals)
            if errors:
                QMessageBox.warning(
                    self, "Eigene Felder",
                    "Bitte korrigieren:\n\n" + "\n".join(errors))
            else:
                cf.set_values(self.ctx.db, cf_vals, contact_id=cid)

        self.refresh()
        self._select_contact_by_id(cid)

    def delete(self):
        cid = self._selected_contact_id()
        if cid is None:
            QMessageBox.information(
                self, "Auswahl",
                "Bitte zuerst einen Kontakt in der Tabelle auswählen.")
            return
        contact = self.ctx.db.get_contact(cid)
        if not contact:
            QMessageBox.warning(self, "Nicht gefunden",
                                "Der Kontakt existiert nicht mehr.")
            self.refresh()
            return

        name = (contact.get("name") or "").strip()
        company = (contact.get("company") or "").strip()
        description = name or company or f"ID {cid}"

        if QMessageBox.question(
                self, "Ansprechpartner löschen",
                f"Ansprechpartner „{description}“ wirklich löschen?\n\n"
                f"Die zugehörige Visitenkarte bleibt im Archiv erhalten, "
                f"nur die Kontaktdaten werden entfernt.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        try:
            self.ctx.db.delete_contact(cid)
        except Exception as e:
            QMessageBox.critical(
                self, "Löschen fehlgeschlagen",
                f"Der Kontakt konnte nicht gelöscht werden:\n\n{e}")
            return

        self.refresh()

    def _select_contact_by_id(self, cid):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text() == str(cid):
                self.table.selectRow(r)
                return

    def create_follow_up(self):
        cid = self._selected_contact_id()
        if cid is None:
            return
        dialog = FollowUpDialog(self)
        if not dialog.exec_() or not dialog.title.text().strip():
            return
        try:
            self.ctx.db.create_task(
                dialog.title.text().strip(),
                fair_id=self.ctx.current_fair_id, contact_id=cid,
                description=dialog.description.toPlainText(),
                due_date=dialog.due.text().strip() or None,
                priority=dialog.priority.currentData())
            self._sync_profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Nachfassaktion", str(exc))

    def new_company_contact(self):
        cid = self._selected_contact_id()
        contact = self.ctx.db.get_contact(cid) if cid else None
        if not contact or not contact.get("company"):
            QMessageBox.information(
                self, "Firma",
                "Bitte zuerst einen Kontakt mit Firma auswählen.")
            return
        self.new(contact["company"])

    def open_company_contact(self, item):
        contact_id = item.data(Qt.UserRole)
        if contact_id:
            contact = self.ctx.db.get_contact(contact_id)
            if contact:
                self.main.open_contact_profile(contact)

    def add_channel(self):
        cid = self._selected_contact_id()
        if cid is None:
            return
        dialog = ChannelDialog(self)
        if not dialog.exec_():
            return
        try:
            self.ctx.db.add_contact_channel(
                cid, dialog.kind.currentData(),
                dialog.value.text(), dialog.label.text(),
                dialog.primary.isChecked())
            self._sync_profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Kontaktweg", str(exc))

    def delete_channel(self):
        detail = self._active_detail()
        if not detail:
            return
        item = detail.channels.currentItem()
        if item and item.data(Qt.UserRole):
            self.ctx.db.delete_contact_channel(item.data(Qt.UserRole))
            self._sync_profile()

    def add_address(self):
        cid = self._selected_contact_id()
        if cid is None:
            return
        dialog = AddressDialog(self)
        if dialog.exec_():
            self.ctx.db.add_contact_address(
                cid, dialog.street.text(), dialog.postal.text(),
                dialog.city.text(), dialog.country.text(),
                dialog.label.text())
            self._sync_profile()

    def delete_address(self):
        detail = self._active_detail()
        if not detail:
            return
        item = detail.addresses.currentItem()
        if item and item.data(Qt.UserRole):
            self.ctx.db.delete_contact_address(item.data(Qt.UserRole))
            self._sync_profile()

    def toggle_task(self, item):
        task_id = item.data(Qt.UserRole)
        if task_id:
            self.ctx.db.update_task(
                task_id,
                status=("open" if item.data(Qt.UserRole + 1) == "done"
                        else "done"))
            self._sync_profile()

    def merge_selected(self):
        cid = self._selected_contact_id()
        if cid is None:
            QMessageBox.information(
                self, "Auswahl",
                "Bitte zuerst einen Kontakt auswählen – er ist der "
                "„Behalten“-Datensatz.")
            return
        keep = self.ctx.db.get_contact(cid)
        if not keep:
            return
        matches = find_similar_contacts(self.ctx.db, keep)
        if not matches:
            other_ids = [int(self.table.item(r, 0).text())
                         for r in range(self.table.rowCount())
                         if self.table.item(r, 0).text() != str(cid)]
            if not other_ids:
                QMessageBox.information(
                    self, "Keine Kandidaten",
                    "Es gibt keinen zweiten Kontakt zum Zusammenführen.")
                return
            other = self.ctx.db.get_contact(other_ids[0])
            if not other:
                return
            MergeContactDialog(self, self.ctx.db, keep, other).exec_()
            self.refresh()
            return

        top, _reasons, _score = matches[0]
        if not MergeContactDialog(self, self.ctx.db, keep, top).exec_():
            return
        self.refresh()
        if self.ctx.db.get_contact(keep["id"]):
            self._select_contact_by_id(keep["id"])

    def open_company(self):
        cid = self._selected_contact_id()
        if cid is None:
            return
        contact = self.ctx.db.get_contact(cid)
        if not contact or not contact.get("company_id"):
            QMessageBox.information(
                self, "Keine Firma",
                "Der Kontakt ist keiner Firma zugeordnet.")
            return
        self.main.open_company_profile(contact["company_id"])