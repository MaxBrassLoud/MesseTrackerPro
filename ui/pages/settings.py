# ui/pages/settings.py
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QComboBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
    QLineEdit, QColorDialog, QDialogButtonBox, QCheckBox,
    QSpinBox, QApplication,
)
from PyQt5.QtGui import QColor

from core.backup import (
    create_backup, restore_backup,
    validate_backup_for_restore, stage_restore,
)
from ui.themes import THEMES
from config import (
    WEB_PORT, DEFAULT_AUTO_LOGOUT_MINUTES,
    AUTO_LOGOUT_MIN, AUTO_LOGOUT_MAX,
)
from core.net import local_ip
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

        # ---- Theme ----
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

        # ---- Sicherheit / Sitzung ----
        sec_box = QGroupBox("Sicherheit / Sitzung")
        sec_v = QVBoxLayout(sec_box)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Automatische Abmeldung nach Inaktivität:"))
        self.auto_logout_spin = QSpinBox()
        self.auto_logout_spin.setRange(AUTO_LOGOUT_MIN, AUTO_LOGOUT_MAX)
        self.auto_logout_spin.setSuffix(" Minuten")
        self.auto_logout_spin.setSpecialValueText("Deaktiviert")
        self.auto_logout_spin.setValue(DEFAULT_AUTO_LOGOUT_MINUTES)
        row2.addWidget(self.auto_logout_spin)
        row2.addStretch(1)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save_auto_logout)
        row2.addWidget(save_btn)
        sec_v.addLayout(row2)
        hint_sec = QLabel(
            "Nach dieser Zeit ohne Maus-, Tastatur- oder Scroll-Aktivität "
            "wird die Sitzung automatisch gesperrt (Blur) und eine erneute "
            "Anmeldung verlangt. Wert 0 deaktiviert die Funktion.")
        hint_sec.setWordWrap(True)
        hint_sec.setObjectName("Sub")
        sec_v.addWidget(hint_sec)
        v.addWidget(sec_box)

        # ---- Status ----
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

        # ---- Eigene Felder ----
        self._build_custom_fields_box(v)

        # ---- Server ----
        server_box = QGroupBox("Lokaler Webserver")
        svv = QVBoxLayout(server_box)
        self.server_label = QLabel("")
        self.server_label.setObjectName("Sub")
        svv.addWidget(self.server_label)
        v.addWidget(server_box)

        # ---- Backup ----
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

    def refresh(self):
        current = self.ctx.db.get_setting("theme", "Flipper")
        idx = self.theme_combo.findText(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.server_label.setText(f"http://{local_ip()}:{WEB_PORT}")

        try:
            cur_auto = int(self.ctx.db.get_setting(
                "auto_logout_minutes", str(DEFAULT_AUTO_LOGOUT_MINUTES)))
        except (ValueError, TypeError):
            cur_auto = DEFAULT_AUTO_LOGOUT_MINUTES
        if cur_auto < AUTO_LOGOUT_MIN:
            cur_auto = AUTO_LOGOUT_MIN
        if cur_auto > AUTO_LOGOUT_MAX:
            cur_auto = AUTO_LOGOUT_MAX
        self.auto_logout_spin.setValue(cur_auto)

        self._load_statuses()
        self._load_custom_fields()

    def _load_statuses(self):
        rows = self.ctx.db.list_statuses(active_only=False)
        self.status_table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            self.status_table.setItem(r, 0, QTableWidgetItem(str(s["id"])))
            self.status_table.setItem(r, 1, QTableWidgetItem(s["name"]))
            color_item = QTableWidgetItem(s["color"])
            color_item.setBackground(QColor(s["color"]))
            c = QColor(s["color"])
            color_item.setForeground(
                QColor("#000") if c.lightness() > 128 else QColor("#fff"))
            self.status_table.setItem(r, 2, color_item)
            self.status_table.setItem(r, 3, QTableWidgetItem(str(s["sort_order"])))
            self.status_table.setItem(
                r, 4, QTableWidgetItem("Ja" if s["active"] else "Nein"))

    def apply_theme(self):
        name = self.theme_combo.currentText()
        self.ctx.db.set_setting("theme", name)
        self.main.apply_theme()
        QMessageBox.information(
            self, "Theme",
            f"Theme „{name}“ angewendet. Das Web-Theme wird mit dem nächsten "
            "Seitenaufruf aktiv.")

    def _save_auto_logout(self):
        val = self.auto_logout_spin.value()
        self.ctx.db.set_setting("auto_logout_minutes", str(val))
        if val == 0:
            QMessageBox.information(
                self, "Sicherheit",
                "Automatische Abmeldung deaktiviert. Die Änderung wirkt "
                "sofort.")
        else:
            QMessageBox.information(
                self, "Sicherheit",
                f"Automatische Abmeldung nach {val} Minuten Inaktivität "
                f"aktiv. Die Änderung wirkt sofort (auch für die laufende "
                f"Sitzung).")

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
                    f"Status „{s['name']}“ wird von {in_use} Kontakt(en) "
                    f"verwendet.\n\n"
                    "Statt zu löschen jetzt deaktivieren? (Ausblenden aus "
                    "Dropdowns, bestehende Kontakte behalten den Status.)",
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

    # ---- Eigene Felder ----
    def _build_custom_fields_box(self, parent_layout):
        box = QGroupBox("Eigene Felder (pro Messe konfigurierbar)")
        bv = QVBoxLayout(box)

        self.cf_scope = QComboBox()
        self.cf_scope.addItem("Gilt für alle Messen", None)
        for fair in self.ctx.db.list_fairs(include_archived=False):
            self.cf_scope.addItem(f"Messe: {fair['name']}", fair["id"])
        self.cf_scope.currentIndexChanged.connect(self._load_custom_fields)
        bv.addWidget(self.cf_scope)

        self.cf_table = QTableWidget(0, 6)
        self.cf_table.setHorizontalHeaderLabels(
            ["ID", "Bezeichnung", "Typ", "Pflicht", "Sortierung", "Aktiv"])
        self.cf_table.horizontalHeader().setStretchLastSection(True)
        self.cf_table.setMinimumHeight(160)
        bv.addWidget(self.cf_table)

        row = QHBoxLayout()
        b_add = QPushButton("Feld hinzufügen")
        b_add.clicked.connect(self._add_custom_field)
        b_edit = QPushButton("Bearbeiten")
        b_edit.setObjectName("Ghost")
        b_edit.clicked.connect(self._edit_custom_field)
        b_del = QPushButton("Löschen")
        b_del.setObjectName("Ghost")
        b_del.clicked.connect(self._delete_custom_field)
        row.addWidget(b_add)
        row.addWidget(b_edit)
        row.addWidget(b_del)
        row.addStretch(1)
        bv.addLayout(row)
        parent_layout.addWidget(box)

    def _load_custom_fields(self):
        from core import custom_fields as cf
        fair_id = self.cf_scope.currentData() if hasattr(self, "cf_scope") else None
        try:
            fields = cf.list_fields(
                self.ctx.db, fair_id=fair_id,
                entity_type="contact", active_only=False)
        except Exception:
            fields = []
        self.cf_table.setRowCount(len(fields))
        for r, f in enumerate(fields):
            self.cf_table.setItem(r, 0, QTableWidgetItem(str(f["id"])))
            self.cf_table.setItem(r, 1, QTableWidgetItem(f["label"]))
            self.cf_table.setItem(r, 2, QTableWidgetItem(f["field_type"]))
            self.cf_table.setItem(
                r, 3, QTableWidgetItem("Ja" if f["required"] else "Nein"))
            self.cf_table.setItem(r, 4, QTableWidgetItem(str(f["sort_order"])))
            self.cf_table.setItem(
                r, 5, QTableWidgetItem("Ja" if f["active"] else "Nein"))

    def _add_custom_field(self):
        from PyQt5.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox,
            QCheckBox, QSpinBox,
        )
        from core import custom_fields as cf
        dlg = QDialog(self)
        dlg.setWindowTitle("Eigenes Feld anlegen")
        form = QFormLayout(dlg)
        inp_label = QLineEdit()
        inp_type = QComboBox()
        for key, label in (("text", "Text"), ("number", "Zahl"),
                           ("date", "Datum"), ("select", "Auswahl"),
                           ("checkbox", "Ja/Nein"), ("multiline", "Mehrzeilig")):
            inp_type.addItem(label, key)
        inp_required = QCheckBox("Pflichtfeld")
        inp_order = QSpinBox()
        inp_order.setRange(0, 10000)
        inp_order.setValue(100)
        inp_options = QLineEdit()
        inp_options.setPlaceholderText(
            "Nur bei Typ „Auswahl“: Optionen mit Komma trennen")
        form.addRow("Bezeichnung:", inp_label)
        form.addRow("Typ:", inp_type)
        form.addRow("Optionen:", inp_options)
        form.addRow("Pflichtfeld:", inp_required)
        form.addRow("Sortierung:", inp_order)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec_():
            return
        try:
            options = []
            if inp_type.currentData() == "select":
                options = [o.strip() for o in
                           inp_options.text().split(",") if o.strip()]
            cf.create_field(
                self.ctx.db,
                label=inp_label.text(),
                field_type=inp_type.currentData(),
                entity_type="contact",
                fair_id=self.cf_scope.currentData(),
                options=options,
                required=inp_required.isChecked(),
                sort_order=inp_order.value())
        except Exception as e:
            QMessageBox.warning(self, "Anlegen fehlgeschlagen", str(e))
            return
        self._load_custom_fields()

    def _edit_custom_field(self):
        from PyQt5.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
            QCheckBox, QSpinBox,
        )
        from core import custom_fields as cf
        row = self.cf_table.currentRow()
        if row < 0:
            return
        fid = int(self.cf_table.item(row, 0).text())
        fields = cf.list_fields(self.ctx.db, entity_type="contact",
                                active_only=False)
        field = next((f for f in fields if f["id"] == fid), None)
        if not field:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Feld bearbeiten")
        form = QFormLayout(dlg)
        inp_label = QLineEdit(field["label"])
        inp_required = QCheckBox("Pflichtfeld")
        inp_required.setChecked(bool(field["required"]))
        inp_order = QSpinBox()
        inp_order.setRange(0, 10000)
        inp_order.setValue(field["sort_order"])
        inp_active = QCheckBox("Aktiv")
        inp_active.setChecked(bool(field["active"]))
        form.addRow("Bezeichnung:", inp_label)
        form.addRow("Pflichtfeld:", inp_required)
        form.addRow("Sortierung:", inp_order)
        form.addRow("Aktiv:", inp_active)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec_():
            return
        cf.update_field(
            self.ctx.db, fid,
            label=inp_label.text(),
            required=inp_required.isChecked(),
            sort_order=inp_order.value(),
            active=inp_active.isChecked())
        self._load_custom_fields()

    def _delete_custom_field(self):
        from core import custom_fields as cf
        row = self.cf_table.currentRow()
        if row < 0:
            return
        fid = int(self.cf_table.item(row, 0).text())
        if QMessageBox.question(
                self, "Löschen",
                "Feld und alle zugehörigen Werte löschen?") != QMessageBox.Yes:
            return
        cf.delete_field(self.ctx.db, fid)
        self._load_custom_fields()

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

        try:
            meta = validate_backup_for_restore(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Ungültiges Backup",
                f"Das Backup konnte nicht validiert werden:\n\n{e}")
            return

        if QMessageBox.question(
                self, "Wiederherstellung vorbereiten",
                f"Backup vom {meta.get('created_at', '?')} "
                f"(Schema {meta.get('schema', '?')}).\n\n"
                f"Die Anwendung wird beendet und beim nächsten Start "
                f"wird die Datenbank wiederhergestellt. Fortfahren?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        try:
            stage_restore(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Fehler",
                f"Restore konnte nicht vorbereitet werden:\n\n{e}")
            return

        QMessageBox.information(
            self, "Vorbereitet",
            "Die Wiederherstellung wird beim nächsten Start durchgeführt.\n\n"
            "Die Anwendung wird jetzt beendet.")
        QApplication.quit()

    def open_dir(self):
        d = os.path.abspath("data")
        if sys.platform.startswith("win"):
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])