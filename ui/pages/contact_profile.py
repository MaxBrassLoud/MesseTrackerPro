# ui/pages/contact_profile.py
"""Vollflächige Kundenakte – ersetzt den früheren Popup-Dialog.

Wird im MainWindow-Stack angezeigt; die Sidebar ist ausgeblendet.
Zurück-Pfeil oben links führt zurück zur Kundenkartei.
Vor/Zurück-Pfeile oben rechts wechseln innerhalb der gefilterten Liste.
Der Inhalt selbst ist das 2-spaltige `ContactDetailWidget`:
  LINKS  – Visitenkarte oben, darunter Firmendaten + Notizen
  RECHTS – Tabs (Aufträge & Nachrichten, Kontaktwege & Adressen,
                  Firma & Ansprechpartner) + Aktionsleiste unten
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)


class ContactProfilePage(QWidget):
    def __init__(self, ctx, main, contacts_page):
        super().__init__()
        self.ctx = ctx
        self.main = main
        self.contacts_page = contacts_page
        self.current_contact = None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        # ---- Top-Bar: Zurück + Vor/Zurück ----
        bar = QHBoxLayout()
        self.btn_back = QPushButton("←")
        self.btn_back.setFixedSize(44, 44)
        self.btn_back.setToolTip("Zurück zur Kundenkartei")
        self.btn_back.setStyleSheet(
            "QPushButton{font-size:18pt;font-weight:bold;padding:0;"
            "border-radius:22px;}")
        self.btn_back.clicked.connect(self._go_back)
        bar.addWidget(self.btn_back)

        self.nav_info = QLabel("")
        self.nav_info.setStyleSheet("color:#888;font-size:9pt;padding-left:8px;")
        bar.addWidget(self.nav_info)
        bar.addStretch(1)

        self.btn_prev = QPushButton("◀  Vorheriger")
        self.btn_prev.setObjectName("Ghost")
        self.btn_prev.clicked.connect(self._prev_contact)
        bar.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Nächster  ▶")
        self.btn_next.setObjectName("Ghost")
        self.btn_next.clicked.connect(self._next_contact)
        bar.addWidget(self.btn_next)

        v.addLayout(bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#333;")
        v.addWidget(sep)

        # ---- 2-spaltiges Detail-Widget ----
        from ui.pages.contacts import ContactDetailWidget
        self.detail = ContactDetailWidget(contacts_page)
        v.addWidget(self.detail, 1)

    # ------------------------------------------------------------------
    # Kontakt setzen / aktualisieren
    # ------------------------------------------------------------------
    def set_contact(self, contact):
        if not contact:
            self.current_contact = None
            self.detail.set_contact(None)
            self._update_header()
            return

        cid = contact["id"]
        fresh = self.ctx.db.get_contact(cid)
        if not fresh:
            # Kontakt existiert nicht mehr → zurück zur Liste
            self._go_back()
            return

        self.current_contact = fresh

        # Tabellenauswahl synchron halten
        if self.contacts_page._selected_contact_id() != cid:
            self.contacts_page._select_contact_by_id(cid)

        self.detail.set_contact(fresh)
        self._update_header()

    def refresh_from_db(self):
        """Wird von ContactsPage.refresh() aufgerufen, wenn sich
        Kontaktdaten geändert haben (nach Bearbeiten/Löschen etc.)."""
        if not self.current_contact:
            return
        cid = self.current_contact["id"]
        contact = self.ctx.db.get_contact(cid)
        if not contact:
            self._go_back()
            return
        self.current_contact = contact
        self.detail.set_contact(contact)
        self._update_header()

    # ------------------------------------------------------------------
    # Header / Navigation
    # ------------------------------------------------------------------
    def _update_header(self):
        if not self.current_contact:
            self.nav_info.setText("")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        table = self.contacts_page.table
        cur = table.currentRow()
        total = table.rowCount()
        if cur >= 0 and total > 0:
            self.nav_info.setText(f"Kontakt {cur + 1} von {total}")
        else:
            self.nav_info.setText("")
        self.btn_prev.setEnabled(cur > 0)
        self.btn_next.setEnabled(cur >= 0 and cur < total - 1)

    def _go_back(self):
        self.main.close_contact_profile()

    def _prev_contact(self):
        table = self.contacts_page.table
        cur = table.currentRow()
        if cur <= 0:
            return
        table.selectRow(cur - 1)
        cid = self.contacts_page._selected_contact_id()
        if cid:
            contact = self.ctx.db.get_contact(cid)
            if contact:
                self.set_contact(contact)

    def _next_contact(self):
        table = self.contacts_page.table
        cur = table.currentRow()
        if cur < 0 or cur >= table.rowCount() - 1:
            return
        table.selectRow(cur + 1)
        cid = self.contacts_page._selected_contact_id()
        if cid:
            contact = self.ctx.db.get_contact(cid)
            if contact:
                self.set_contact(contact)