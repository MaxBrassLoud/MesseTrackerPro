import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
    QFormLayout, QTextEdit, QDialogButtonBox, QSplitter, QFrame,
    QSizePolicy, QHeaderView, QAbstractItemView)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

from ui.widgets import FullSizeImageDialog


def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


# ======================================================================
# Bearbeiten-Dialog (wie bisher, nur Status dynamisch)
# ======================================================================
class ContactDialog(QDialog):
    def __init__(self, parent, contact=None, ctx=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Kontakt bearbeiten" if contact else "Kontakt anlegen")
        self.setMinimumWidth(440)
        form = QFormLayout(self)

        self.inp = {}
        for k in ("name", "company", "position", "phone", "email", "notes"):
            if k == "notes":
                w = QTextEdit()
                w.setMinimumHeight(80)
                if contact:
                    w.setPlainText(contact[k] or "")
            else:
                w = QLineEdit()
                if contact:
                    w.setText(contact[k] or "")
            form.addRow(k.capitalize(), w)
            self.inp[k] = w

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

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        d = {k: (w.toPlainText() if isinstance(w, QTextEdit) else w.text())
             for k, w in self.inp.items()}
        d["status"] = self.status.currentText()
        return d


# ======================================================================
# Detail-Widget (rechte Seite)
# ======================================================================
class ContactDetailWidget(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.ctx = page.ctx
        self.current_contact = None
        self._orig_pix = None

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)

        self.title = QLabel("Kontakt")
        self.title.setObjectName("Title")
        v.addWidget(self.title)

        # Bild
        self.image_label = QLabel("Wähle einen Kontakt aus der Tabelle")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setStyleSheet(
            "background:#000;border:1px solid #333;color:#888;")
        self.image_label.setSizePolicy(QSizePolicy.Expanding,
                                       QSizePolicy.Fixed)
        self.image_label.setCursor(Qt.ArrowCursor)
        self.image_label.mousePressEvent = self._on_image_click
        v.addWidget(self.image_label)

        self.image_hint = QLabel("")
        self.image_hint.setStyleSheet("color:#888;font-size:9pt;padding:2px;")
        self.image_hint.setAlignment(Qt.AlignCenter)
        v.addWidget(self.image_hint)

        # Felder
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fields = {}
        for key, label in [
            ("name", "Name"),
            ("company", "Firma"),
            ("position", "Position"),
            ("phone", "Telefon"),
            ("email", "E-Mail"),
            ("status", "Status"),
            ("source", "Quelle"),
            ("employee", "Mitarbeiter"),
            ("fair_day", "Messetag"),
            ("created_at", "Erfasst"),
        ]:
            l = QLabel("—")
            l.setWordWrap(True)
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.fields[key] = l
            form.addRow(label + ":", l)
        v.addLayout(form)

        # Notizen
        notes_label = QLabel("Notizen:")
        notes_label.setStyleSheet("font-weight:600;padding-top:6px;")
        v.addWidget(notes_label)

        self.notes_view = QTextEdit()
        self.notes_view.setReadOnly(True)
        self.notes_view.setMinimumHeight(90)
        self.notes_view.setPlaceholderText("(keine Notizen)")
        v.addWidget(self.notes_view)

        v.addStretch(1)

        # Aktions-Buttons
        btn_row = QHBoxLayout()
        self.btn_edit = QPushButton("Bearbeiten")
        self.btn_edit.clicked.connect(self.page.edit)
        self.btn_delete = QPushButton("Löschen")
        self.btn_delete.setObjectName("Ghost")
        self.btn_delete.clicked.connect(self.page.delete)
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        self._set_buttons_enabled(False)

    def _set_buttons_enabled(self, enabled):
        self.btn_edit.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def set_contact(self, contact):
        self.current_contact = contact
        self._orig_pix = None

        if not contact:
            self.title.setText("Kontakt")
            for l in self.fields.values():
                l.setText("—")
            self.notes_view.clear()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("Wähle einen Kontakt aus der Tabelle")
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
        self.fields["status"].setText(contact.get("status") or "—")
        self.fields["source"].setText(contact.get("source") or "—")
        self.fields["employee"].setText(
            emps.get(contact.get("employee_id"), "—"))
        self.fields["fair_day"].setText(
            days.get(contact.get("fair_day_id"), "—"))
        self.fields["created_at"].setText(
            _fmt_dt(contact.get("created_at", "")) or "—")

        self.notes_view.setPlainText(contact.get("notes") or "")

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
        w = max(self.image_label.width() - 8, 200)
        scaled = self._orig_pix.scaledToWidth(w, Qt.SmoothTransformation)
        if scaled.height() > 320:
            scaled = self._orig_pix.scaledToHeight(
                320, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
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

        # Kopf
        header = QHBoxLayout()
        title = QLabel("Kundenkartei")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch(1)
        btn_new = QPushButton("+ Neuer Kontakt")
        btn_new.clicked.connect(self.new)
        header.addWidget(btn_new)
        v.addLayout(header)

        # Filter
        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suche Name / Firma / E-Mail")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.currentIndexChanged.connect(self.refresh)
        f.addWidget(self.search, 1)
        f.addWidget(self.status_filter)
        v.addLayout(f)

        # Split: Tabelle | Detail
        split = QSplitter(Qt.Horizontal)

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
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        split.addWidget(self.table)

        self.detail = ContactDetailWidget(self)
        split.addWidget(self.detail)

        split.setSizes([640, 400])
        v.addWidget(split, 1)

    # ---------- Filter ----------
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

    # ---------- Refresh ----------
    def refresh(self):
        self._rebuild_status_filter()

        if not self.ctx.current_fair_id:
            self.table.setRowCount(0)
            self.detail.set_contact(None)
            return

        status = self.status_filter.currentText()
        rows = self.ctx.db.search_contacts(
            fair_id=self.ctx.current_fair_id,
            status=status if status != "Alle Status" else None,
            text=self.search.text().strip())

        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            self.table.setItem(
                r, 0, QTableWidgetItem(str(c.get("id") or "")))
            self.table.setItem(
                r, 1, QTableWidgetItem(c.get("name") or ""))
            self.table.setItem(
                r, 2, QTableWidgetItem(c.get("company") or ""))
            self.table.setItem(
                r, 3, QTableWidgetItem(c.get("email") or ""))
            self.table.setItem(
                r, 4, QTableWidgetItem(c.get("status") or ""))
            self.table.setItem(
                r, 5, QTableWidgetItem(_fmt_dt(c.get("created_at", ""))))
        self.table.blockSignals(False)

        # Detail zurücksetzen, wenn die aktuelle Auswahl weg ist
        if self.table.rowCount() == 0:
            self.detail.set_contact(None)
        else:
            cur_row = self.table.currentRow()
            if cur_row < 0:
                self.detail.set_contact(None)
            else:
                self._on_selection_changed()

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            self.detail.set_contact(None)
            return
        try:
            cid = int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            self.detail.set_contact(None)
            return
        contact = self.ctx.db.get_contact(cid)
        self.detail.set_contact(contact)

    # ---------- Aktionen ----------
    def _selected_contact_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        try:
            return int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            return None

    def new(self):
        if not self.ctx.current_fair_id:
            QMessageBox.warning(self, "Messe",
                                "Bitte zuerst eine Messe auswählen.")
            return
        d = ContactDialog(self, ctx=self.ctx)
        if d.exec_():
            vals = d.values()
            new_id = self.ctx.db.create_contact(
                fair_id=self.ctx.current_fair_id, source="Manuell",
                fair_day_id=self.ctx.current_fair_day_id, **vals)
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
        if d.exec_():
            self.ctx.db.update_contact(cid, **d.values())
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
                self, "Kontakt löschen",
                f"Kontakt „{description}“ wirklich löschen?\n\n"
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