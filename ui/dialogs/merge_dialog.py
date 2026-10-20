"""Dialog zum Zusammenführen zweier Kontakte."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView, QAbstractItemView,
)
from PyQt5.QtGui import QColor

from core.duplicates import (
    merge_contacts_keep_richer, dismiss_duplicate_pair,
)


_FIELDS = [
    ("name", "Name"),
    ("company", "Firma"),
    ("position", "Position"),
    ("phone", "Telefon"),
    ("email", "E-Mail"),
    ("notes", "Notizen"),
]


class MergeContactDialog(QDialog):
    def __init__(self, parent, db, keep_contact, duplicate_contact):
        super().__init__(parent)
        self.db = db
        self.keep = keep_contact
        self.dup = duplicate_contact
        self.setWindowTitle("Kontakte zusammenführen")
        self.resize(720, 520)

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            f"<b>Behalten:</b> #{keep_contact['id']} "
            f"{keep_contact.get('name') or '(ohne Namen)'}  "
            f"<span style='color:#888;'>→ dieses Profil bleibt bestehen</span>"))
        v.addWidget(QLabel(
            f"<b>Zusammenführen mit:</b> #{duplicate_contact['id']} "
            f"{duplicate_contact.get('name') or '(ohne Namen)'}  "
            f"<span style='color:#888;'>→ wird danach gelöscht, "
            f"fehlende Felder werden übernommen</span>"))

        self.table = QTableWidget(len(_FIELDS), 3)
        self.table.setHorizontalHeaderLabels(
            ["Feld", "Behalten (aktuell)", "Übernehmen aus Dublette"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        for row, (key, label) in enumerate(_FIELDS):
            self.table.setItem(row, 0, QTableWidgetItem(label))
            cur = self.keep.get(key) or "—"
            new = self.dup.get(key) or "—"
            it_cur = QTableWidgetItem(cur)
            it_new = QTableWidgetItem(new)
            if (cur in ("", "—")) and new not in ("", "—"):
                it_new.setBackground(QColor("#1f3a1f"))
                it_new.setToolTip("Wird übernommen (Feld ist leer)")
            self.table.setItem(row, 1, it_cur)
            self.table.setItem(row, 2, it_new)
        v.addWidget(self.table, 1)

        hint = QLabel(
            "Aufgaben, Historie, Adressen, Kontaktwege und eigene Felder "
            "werden automatisch auf den verbleibenden Kontakt umgehängt. "
            "Es gibt keine Datenverluste.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:9pt;")
        v.addWidget(hint)

        row = QHBoxLayout()
        b_dismiss = QPushButton("Keine Dublette")
        b_dismiss.setObjectName("Ghost")
        b_dismiss.clicked.connect(self._dismiss)
        b_merge = QPushButton("Zusammenführen")
        b_merge.clicked.connect(self._merge)
        row.addStretch(1)
        row.addWidget(b_dismiss)
        row.addWidget(b_merge)
        v.addLayout(row)

    def _dismiss(self):
        if QMessageBox.question(
                self, "Dublette verwerfen",
                "Die beiden Kontakte werden dauerhaft als „nicht identisch“ "
                "markiert. Fortfahren?") != QMessageBox.Yes:
            return
        dismiss_duplicate_pair(self.db, self.keep["id"], self.dup["id"])
        self.accept()

    def _merge(self):
        try:
            merged = merge_contacts_keep_richer(
                self.db, self.keep["id"], self.dup["id"])
        except Exception as e:
            QMessageBox.critical(self, "Fehler",
                                 f"Zusammenführen fehlgeschlagen:\n{e}")
            return
        msg = ("Kontakte zusammengeführt."
               if not merged else
               "Kontakte zusammengeführt. Übernommen: "
               + ", ".join(merged))
        QMessageBox.information(self, "Erfolg", msg)
        self.accept()