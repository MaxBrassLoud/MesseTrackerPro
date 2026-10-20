"""Vollflächige Firmenakte: Stammdaten + Ansprechpartner + Notizen + Historie."""
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QTextEdit, QGroupBox, QFormLayout,
    QMessageBox,
)
from PyQt5.QtCore import Qt


class CompanyProfilePage(QWidget):
    def __init__(self, ctx, main, contacts_page):
        super().__init__()
        self.ctx = ctx
        self.main = main
        self.contacts_page = contacts_page
        self.company_id = None
        self.company = None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)

        bar = QHBoxLayout()
        self.btn_back = QPushButton("←")
        self.btn_back.setFixedSize(44, 44)
        self.btn_back.setStyleSheet(
            "QPushButton{font-size:18pt;font-weight:bold;padding:0;"
            "border-radius:22px;}")
        self.btn_back.clicked.connect(self._go_back)
        bar.addWidget(self.btn_back)
        self.title = QLabel("Firmenakte")
        self.title.setObjectName("Title")
        bar.addWidget(self.title, 1)
        self.btn_new_contact = QPushButton("+ Ansprechpartner")
        self.btn_new_contact.clicked.connect(self._new_contact)
        bar.addWidget(self.btn_new_contact)
        v.addLayout(bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        v.addWidget(sep)

        info_box = QGroupBox("Stammdaten")
        fl = QFormLayout(info_box)
        self.info_website = QLabel("—")
        self.info_phone = QLabel("—")
        self.info_address = QLabel("—")
        self.info_website.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fl.addRow("Website:", self.info_website)
        fl.addRow("Telefon:", self.info_phone)
        fl.addRow("Adresse:", self.info_address)
        v.addWidget(info_box)

        body = QHBoxLayout()
        left = QGroupBox("Ansprechpartner")
        lv = QVBoxLayout(left)
        self.people = QListWidget()
        self.people.itemDoubleClicked.connect(self._open_person)
        lv.addWidget(self.people)
        body.addWidget(left, 3)

        right = QGroupBox("Gemeinsame Gesprächsnotizen")
        rv = QVBoxLayout(right)
        self.notes_list = QListWidget()
        rv.addWidget(self.notes_list, 1)
        self.note_input = QTextEdit()
        self.note_input.setMinimumHeight(80)
        self.note_input.setPlaceholderText(
            "Neue Gesprächsnotiz – wird für alle Ansprechpartner "
            "dieser Firma gespeichert.")
        rv.addWidget(self.note_input)
        btn = QPushButton("Notiz speichern")
        btn.clicked.connect(self._save_note)
        rv.addWidget(btn)
        body.addWidget(right, 2)
        v.addLayout(body, 1)

    def set_company(self, company_id: int):
        self.company_id = company_id
        self._reload()

    def _reload(self):
        if not self.company_id:
            return
        self.company = self.ctx.db.get_company(self.company_id)
        if not self.company:
            QMessageBox.warning(self, "Nicht gefunden",
                                "Die Firma existiert nicht mehr.")
            self._go_back()
            return
        self.title.setText(f"Firmenakte: {self.company['name']}")
        self.info_website.setText(self.company.get("website") or "—")
        self.info_phone.setText(self.company.get("phone") or "—")
        self.info_address.setText(self.company.get("address") or "—")

        self.people.clear()
        for c in self.ctx.db.company_contacts(self.company_id):
            label = c.get("name") or "Ohne Namen"
            if c.get("position"):
                label += f" – {c['position']}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, c["id"])
            self.people.addItem(item)

        self.notes_list.clear()
        with self.ctx.db._lock:
            rows = self.ctx.db.conn.execute(
                """SELECT n.note, n.actor_name, n.created_at
                   FROM company_notes n
                   WHERE n.company_id=?
                   ORDER BY n.created_at DESC""",
                (self.company_id,)).fetchall()
        for r in rows:
            prefix = r["created_at"][:16].replace("T", " ")
            self.notes_list.addItem(
                f"[{prefix}] {r['actor_name'] or 'Unbekannt'}: {r['note']}")

    def _save_note(self):
        text = self.note_input.toPlainText().strip()
        if not text:
            return
        actor = getattr(self.main, "user", {}) or {}
        actor_name = actor.get("display_name") or actor.get("username") or "—"
        with self.ctx.db._lock:
            self.ctx.db.conn.execute(
                """INSERT INTO company_notes
                   (company_id, actor_user_id, actor_name, note, created_at)
                   VALUES (?,?,?,?,?)""",
                (self.company_id, actor.get("id"), actor_name, text,
                 datetime.now().isoformat(timespec="seconds")))
            self.ctx.db.conn.commit()
        self.note_input.clear()
        self._reload()

    def _new_contact(self):
        if not self.company:
            return
        self.main.show_page("contacts")
        self.contacts_page.new(self.company["name"])

    def _open_person(self, item):
        cid = item.data(Qt.UserRole)
        if cid:
            contact = self.ctx.db.get_contact(cid)
            if contact:
                self.main.show_page("contacts")
                self.contacts_page._select_contact_by_id(cid)
                self.main.open_contact_profile(contact)

    def _go_back(self):
        self.main.close_company_profile()