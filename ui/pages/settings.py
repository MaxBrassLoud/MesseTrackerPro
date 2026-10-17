from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFileDialog, QMessageBox, QComboBox, QGroupBox,
                             QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
                             QLineEdit, QColorDialog, QDialogButtonBox, QCheckBox,
                             QSpinBox)
from PyQt5.QtGui import QColor
from core.backup import create_backup, restore_backup
from ui.themes import THEMES
from config import WEB_PORT
from ui.pages.employees import local_ip
import os
import subprocess
import sys


class StatusDialog(QDialog):
    def __init__(self, parent, status=None):
        super().__init__(parent)
        self.setWindowTitle("Status bearbeiten" if status else "Status anlegen")
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        self.inp_name = QLineEdit(status["name"] if status else "")
        form.addRow("Name", self.inp_name)

        color_row = QHBoxLayout()
        self.color_value = status["color"] if status else "#FF8200"
        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(28)
        self._update_color_button()
        self.color_btn.clicked.connect(self.pick_color)
        color_row.addWidget(self.color_btn)
        form.addRow("Farbe", color_row)

        self.inp_order = QSpinBox()
        self.inp_order.setRange(0, 10000)
        self.inp_order.setValue(status["sort_order"] if status else 100)
        form.addRow("Sortierung", self.inp_order)

        self.cb_active = QCheckBox("Aktiv")
        self.cb_active.setChecked(bool(status["active"]) if status else True)
        form.addRow(self.cb_active)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _update_color_button(self):
        c = QColor(self.color_value)
        fg = "#000" if c.lightness() > 128 else "#fff"
        self.color_btn.setStyleSheet(
            f"background:{self.color_value};color:{fg};")
        self.color_btn.setText(self.color_value)

    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.color_value), self, "Farbe wählen")
        if c.isValid():
            self.color_value = c.name()
            self._update_color_button()

    def values(self):
        return {
            "name": self.inp_name.text().strip(),
            "color": self.color_value,
            "sort_order": self.inp_order.value(),
            "active": 1 if self.cb_active.isChecked() else 0,
        }


class SettingsPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        t = QLabel("Einstellungen & Datensicherung")
        t.setObjectName("Title")
        v.addWidget(t)

        # -------- Theme --------
        theme_box = QGroupBox("Design / Theme")
        tv = QVBoxLayout(theme_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        row.addWidget(self.theme_combo, 1)
        apply_btn = QPushButton("Anwenden")
        apply_btn.clicked.connect(self.apply_theme)
        row.addWidget(apply_btn)
        tv.addLayout(row)
        tv.addWidget(QLabel(
            "Das Theme wirkt sofort auf Desktop und Smartphone-Webseite."))
        v.addWidget(theme_box)

        # -------- Statuses --------
        status_box = QGroupBox("Kundenstatus bearbeiten")
        sv = QVBoxLayout(status_box)
        self.status_table = QTableWidget(0, 5)
        self.status_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Farbe", "Sortierung", "Aktiv"])
        self.status_table.horizontalHeader().setStretchLastSection(True)
        self.status_table.setMinimumHeight(180)
        sv.addWidget(self.status_table)

        srow = QHBoxLayout()
        b_add = QPushButton("Hinzufügen")
        b_add.clicked.connect(self.add_status)
        b_edit = QPushButton("Bearbeiten")
        b_edit.setObjectName("Ghost")
        b_edit.clicked.connect(self.edit_status)
        b_del = QPushButton("Löschen")
        b_del.setObjectName("Ghost")
        b_del.clicked.connect(self.delete_status)
        b_toggle = QPushButton("Aktiv/Inaktiv")
        b_toggle.setObjectName("Ghost")
        b_toggle.clicked.connect(self.toggle_status)
        srow.addWidget(b_add)
        srow.addWidget(b_edit)
        srow.addWidget(b_del)
        srow.addWidget(b_toggle)
        srow.addStretch(1)
        sv.addLayout(srow)
        sv.addWidget(QLabel(
            "Beim Umbenennen werden bestehende Kontakte automatisch mit aktualisiert. "
            "Löschen ist nur möglich, wenn kein Kontakt den Status verwendet."))
        v.addWidget(status_box)

        # -------- Server --------
        server_box = QGroupBox("Lokaler Webserver")
        svv = QVBoxLayout(server_box)
        self.server_label = QLabel("")
        self.server_label.setObjectName("Sub")
        svv.addWidget(self.server_label)
        v.addWidget(server_box)

        # -------- Backup --------
        backup_box = QGroupBox("Datensicherung")
        bv = QVBoxLayout(backup_box)
        b1 = QPushButton("Datenbank-Backup erstellen")
        b1.clicked.connect(self.backup)
        b2 = QPushButton("Backup wiederherstellen")
        b2.setObjectName("Ghost")
        b2.clicked.connect(self.restore)
        b3 = QPushButton("Datenverzeichnis öffnen")
        b3.setObjectName("Ghost")
        b3.clicked.connect(self.open_dir)
        bv.addWidget(b1)
        bv.addWidget(b2)
        bv.addWidget(b3)
        v.addWidget(backup_box)

        v.addStretch(1)

    # ---- Refresh ----
    def refresh(self):
        current = self.ctx.db.get_setting("theme", "Flipper")
        idx = self.theme_combo.findText(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.server_label.setText(f"http://{local_ip()}:{WEB_PORT}")
        self._load_statuses()

    def _load_statuses(self):
        rows = self.ctx.db.list_statuses(active_only=False)
        self.status_table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            self.status_table.setItem(r, 0, QTableWidgetItem(str(s["id"])))
            self.status_table.setItem(r, 1, QTableWidgetItem(s["name"]))
            color_item = QTableWidgetItem(s["color"])
            color_item.setBackground(QColor(s["color"]))
            # Kontrastfarbe
            c = QColor(s["color"])
            color_item.setForeground(
                QColor("#000") if c.lightness() > 128 else QColor("#fff"))
            self.status_table.setItem(r, 2, color_item)
            self.status_table.setItem(r, 3, QTableWidgetItem(str(s["sort_order"])))
            self.status_table.setItem(r, 4, QTableWidgetItem(
                "Ja" if s["active"] else "Nein"))

    # ---- Theme ----
    def apply_theme(self):
        name = self.theme_combo.currentText()
        self.ctx.db.set_setting("theme", name)
        self.main.apply_theme()
        QMessageBox.information(
            self, "Theme",
            f"Theme „{name}“ angewendet. Das Web-Theme wird mit dem nächsten "
            "Seitenaufruf aktiv.")

    # ---- Status CRUD ----
    def _selected_status(self):
        row = self.status_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Auswahl",
                                    "Bitte einen Status auswählen.")
            return None
        sid = int(self.status_table.item(row, 0).text())
        return self.ctx.db.get_status(sid)

    def add_status(self):
        d = StatusDialog(self)
        if not d.exec_():
            return
        vals = d.values()
        if not vals["name"]:
            QMessageBox.warning(self, "Fehlt", "Name darf nicht leer sein.")
            return
        try:
            self.ctx.db.create_status(
                vals["name"], vals["color"], vals["sort_order"])
            if not vals["active"]:
                # Nachträglich deaktivieren
                for s in self.ctx.db.list_statuses(active_only=False):
                    if s["name"] == vals["name"]:
                        self.ctx.db.update_status(s["id"], active=0)
                        break
        except ValueError as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        self._load_statuses()
        self._refresh_related_pages()

    def edit_status(self):
        s = self._selected_status()
        if not s:
            return
        d = StatusDialog(self, status=s)
        if not d.exec_():
            return
        vals = d.values()
        try:
            self.ctx.db.update_status(s["id"], **vals)
        except ValueError as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        self._load_statuses()
        self._refresh_related_pages()

    def toggle_status(self):
        s = self._selected_status()
        if not s:
            return
        self.ctx.db.update_status(s["id"], active=0 if s["active"] else 1)
        self._load_statuses()
        self._refresh_related_pages()

    def delete_status(self):
        s = self._selected_status()
        if not s:
            return
        in_use = self.ctx.db.status_usage_count(s["id"])
        if in_use > 0:
            if QMessageBox.question(
                    self, "Wird verwendet",
                    f"Status „{s['name']}“ wird von {in_use} Kontakt(en) verwendet.\n\n"
                    "Statt zu löschen jetzt deaktivieren? (Ausblenden aus Dropdowns, "
                    "bestehende Kontakte behalten den Status.)",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.ctx.db.update_status(s["id"], active=0)
                self._load_statuses()
                self._refresh_related_pages()
            return
        if QMessageBox.question(
                self, "Löschen",
                f"Status „{s['name']}“ endgültig löschen?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        _in_use, err = self.ctx.db.delete_status(s["id"])
        if err:
            QMessageBox.warning(self, "Nicht möglich", err)
            return
        self._load_statuses()
        self._refresh_related_pages()

    def _refresh_related_pages(self):
        for key in ("contacts", "queue", "dashboard"):
            p = self.main.pages.get(key)
            if p and hasattr(p, "refresh"):
                try:
                    p.refresh()
                except Exception:
                    pass

    # ---- Backup ----
    def backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup speichern", "messe_tracker_backup.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            create_backup(path)
            QMessageBox.information(self, "Backup", f"Backup erstellt:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Backup wählen", "", "ZIP (*.zip)")
        if not path:
            return
        if QMessageBox.question(
                self, "Bestätigen",
                "Aktuelle Datenbank wird überschrieben. Fortfahren?"
                ) != QMessageBox.Yes:
            return
        try:
            restore_backup(path, confirm_overwrite=True)
            QMessageBox.information(
                self, "Wiederherstellung",
                "Backup eingespielt. Bitte Anwendung neu starten.")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def open_dir(self):
        d = os.path.abspath("data")
        if sys.platform.startswith("win"):
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])