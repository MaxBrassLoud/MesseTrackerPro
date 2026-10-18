import io

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QTableWidget,
                             QTableWidgetItem, QMessageBox, QDialog,
                             QFormLayout, QCheckBox, QHeaderView,
                             QAbstractItemView, QInputDialog, QSplitter,
                             QSizePolicy, QGraphicsBlurEffect)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from config import WEB_PORT
from core.net import local_ip
from core.auth import AuthService, AuthError
from core.permissions import Perm, PermissionDenied
from core.permissions import ALL_PERMISSIONS, PERMISSION_LABELS

try:
    import qrcode
except Exception:
    qrcode = None


class RoleDialog(QDialog):
    def __init__(self, parent, role=None, selected=()):
        super().__init__(parent)
        self.setWindowTitle("Rolle bearbeiten" if role else "Rolle anlegen")
        form = QFormLayout(self)
        self.name = QLineEdit(role.get("name", "") if role else "")
        self.description = QLineEdit(role.get("description", "") if role else "")
        form.addRow("Name:", self.name); form.addRow("Beschreibung:", self.description)
        form.addRow(QLabel("Berechtigungen:"))
        self.permissions = {}
        for permission, label in ALL_PERMISSIONS:
            check = QCheckBox(label); check.setChecked(permission in selected)
            self.permissions[permission] = check; form.addRow(check)
        buttons = QPushButton("Speichern"); buttons.clicked.connect(self.accept); form.addRow(buttons)

    def selected_permissions(self):
        return {key for key, check in self.permissions.items() if check.isChecked()}


class CreateUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Benutzer anlegen")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self.inp_user = QLineEdit()
        self.inp_name = QLineEdit()
        self.inp_pw = QLineEdit(); self.inp_pw.setEchoMode(QLineEdit.Password)
        self.cb_admin = QCheckBox("Administrator (alle Rechte)")
        form.addRow("Benutzername:", self.inp_user)
        form.addRow("Anzeigename:", self.inp_name)
        form.addRow("Vorläufiges Passwort:", self.inp_pw)
        form.addRow(self.cb_admin)
        b = QPushButton("Anlegen")
        b.clicked.connect(self._submit)
        form.addRow(b)

    def _submit(self):
        if not self.inp_user.text().strip():
            QMessageBox.warning(self, "Fehlt", "Benutzername erforderlich.")
            return
        if not self.inp_pw.text():
            QMessageBox.warning(self, "Fehlt", "Passwort erforderlich.")
            return
        self.accept()


class UsersPage(QWidget):
    def __init__(self, ctx, main, auth: AuthService, current_user: dict):
        super().__init__()
        self.ctx, self.main = ctx, main
        self.auth = auth
        self.current_user = current_user

        v = QVBoxLayout(self)
        t = QLabel("Mitarbeiter & Zugänge")
        t.setObjectName("Title")
        v.addWidget(t)

        row = QHBoxLayout()
        self.btn_new = QPushButton("+ Mitarbeiter anlegen")
        self.btn_new.clicked.connect(self.create_user)
        self.btn_new_role = QPushButton("+ Rolle anlegen")
        self.btn_new_role.setObjectName("Ghost")
        self.btn_new_role.clicked.connect(self.create_role)
        for b in (self.btn_new, self.btn_new_role):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Benutzername", "Anzeigename", "Admin", "Aktiv",
             "Rollen", "Letzter Login"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selected)
        split.addWidget(self.table)

        self.detail = QWidget()
        detail_layout = QVBoxLayout(self.detail)
        self.detail_title = QLabel("Mitarbeiter auswählen")
        self.detail_title.setObjectName("Title")
        detail_layout.addWidget(self.detail_title)
        self.detail_info = QLabel("Wählen Sie einen Mitarbeiter in der Tabelle aus.")
        self.detail_info.setWordWrap(True)
        detail_layout.addWidget(self.detail_info)
        self.qr = QLabel("QR-Code wird nach Auswahl angezeigt")
        self.qr.setAlignment(Qt.AlignCenter); self.qr.setMinimumSize(220, 220)
        self.qr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.qr.setCursor(Qt.PointingHandCursor); self.qr.mousePressEvent = self._reveal_qr
        detail_layout.addWidget(self.qr)
        self.qr_hint = QLabel("Zum Freigeben und Scannen auf den QR-Code klicken.")
        self.qr_hint.setWordWrap(True); detail_layout.addWidget(self.qr_hint)
        self.detail_buttons = QHBoxLayout()
        self.btn_active = QPushButton("Aktiv/Inaktiv") ; self.btn_active.clicked.connect(self.toggle_active)
        self.btn_reset = QPushButton("Passwort zurücksetzen"); self.btn_reset.clicked.connect(self.reset_password)
        self.btn_roles = QPushButton("Rollen"); self.btn_roles.clicked.connect(self.assign_roles)
        for button in (self.btn_active, self.btn_reset, self.btn_roles): self.detail_buttons.addWidget(button)
        detail_layout.addLayout(self.detail_buttons); detail_layout.addStretch(1)
        split.addWidget(self.detail); split.setSizes([760, 380])
        v.addWidget(split, 1)
        self._qr_blur = QGraphicsBlurEffect(self.qr); self._qr_blur.setBlurRadius(24); self.qr.setGraphicsEffect(self._qr_blur)
        self._qr_revealed = False

    def refresh(self):
        try:
            self.auth.require(self.current_user, Perm.MANAGE_USERS)
        except PermissionDenied as e:
            QMessageBox.warning(self, "Keine Berechtigung", str(e))
            return
        users = self.ctx.db.list_users()
        self.table.setRowCount(len(users))
        for r, u in enumerate(users):
            self.table.setItem(r, 0, QTableWidgetItem(str(u["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(u["username"]))
            self.table.setItem(r, 2, QTableWidgetItem(u.get("display_name") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(
                "Ja" if u.get("is_admin") else "Nein"))
            self.table.setItem(r, 4, QTableWidgetItem(
                "Ja" if u.get("is_active") else "Nein"))
            roles = [role["name"] for role in self.ctx.db.list_roles() if role["id"] in self.ctx.db.user_role_ids(u["id"])]
            self.table.setItem(r, 5, QTableWidgetItem(", ".join(roles) or "—"))
            self.table.setItem(r, 6, QTableWidgetItem(
                u.get("last_login") or "—"))
        self._show_selected()

    def _show_selected(self):
        uid = self._selected_id()
        if uid is None:
            self.detail_title.setText("Mitarbeiter auswählen"); self.detail_info.setText("Wählen Sie einen Mitarbeiter in der Tabelle aus."); return
        user = self.ctx.db.get_user(uid); employee = self.ctx.db.get_employee_by_user_id(uid)
        roles = [role["name"] for role in self.ctx.db.list_roles() if role["id"] in self.ctx.db.user_role_ids(uid)]
        self.detail_title.setText(user.get("display_name") or user["username"])
        self.detail_info.setText(f"Benutzername: {user['username']}\nE-Mail: {user.get('email') or 'Keine Angabe'}\nStatus: {'Aktiv' if user.get('is_active') else 'Deaktiviert'}\nRollen: {', '.join(roles) or 'Keine'}")
        self._qr_revealed = False
        if not employee or not qrcode:
            self.qr.setText("QR-Code nicht verfügbar" if employee else "Kein Mitarbeiterprofil vorhanden")
            return
        image = qrcode.make(f"http://{local_ip()}:{WEB_PORT}/scan/{employee['token']}")
        buf = io.BytesIO(); image.save(buf, format="PNG")
        pix = QPixmap(); pix.loadFromData(buf.getvalue())
        self.qr.setPixmap(pix.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._qr_blur.setEnabled(True); self.qr_hint.setText("QR-Code geschützt. Zum Freigeben und Scannen klicken.")

    def _reveal_qr(self, event):
        if self.qr.pixmap() is None: return
        self._qr_revealed = True; self._qr_blur.setEnabled(False)
        self.qr_hint.setText("QR-Code freigegeben. Nach Auswahl eines anderen Mitarbeiters wird er wieder verdeckt.")

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        try:
            return int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            return None

    def create_user(self):
        try:
            self.auth.require(self.current_user, Perm.MANAGE_USERS)
        except PermissionDenied as e:
            QMessageBox.warning(self, "Keine Berechtigung", str(e))
            return
        d = CreateUserDialog(self)
        if not d.exec_():
            return
        try:
            self.auth.create_user(
                username=d.inp_user.text().strip(),
                password=d.inp_pw.text(),
                display_name=d.inp_name.text().strip(),
                is_admin=d.cb_admin.isChecked(),
                must_change_password=True,
                actor_user_id=self.current_user["id"])
        except (AuthError, ValueError) as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        self.refresh()

    def toggle_admin(self):
        uid = self._selected_id()
        if uid is None:
            return
        u = self.ctx.db.get_user(uid)
        if not u:
            return
        try:
            self.auth.set_admin(uid, not u["is_admin"],
                                actor_user_id=self.current_user["id"])
        except AuthError as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        self.refresh()

    def toggle_active(self):
        uid = self._selected_id()
        if uid is None:
            return
        if uid == self.current_user["id"]:
            QMessageBox.warning(self, "Nicht möglich",
                                "Sie können Ihren eigenen Account nicht "
                                "deaktivieren.")
            return
        u = self.ctx.db.get_user(uid)
        if not u:
            return
        try:
            self.auth.set_active(uid, not u["is_active"],
                                 actor_user_id=self.current_user["id"])
        except AuthError as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        self.refresh()

    def reset_password(self):
        uid = self._selected_id()
        if uid is None:
            return
        pw, ok = QInputDialog.getText(
            self, "Passwort zurücksetzen",
            "Neues vorläufiges Passwort (min. 10 Zeichen):",
            QLineEdit.Password)
        if not ok or not pw:
            return
        try:
            self.auth.set_password(uid, pw, must_change=True,
                                   actor_user_id=self.current_user["id"])
        except (AuthError, ValueError) as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        QMessageBox.information(
            self, "Zurückgesetzt",
            "Passwort wurde zurückgesetzt. Der Benutzer muss es bei der "
            "nächsten Anmeldung ändern.")

    def create_role(self):
        try: self.auth.require(self.current_user, Perm.MANAGE_ROLES)
        except PermissionDenied as e: QMessageBox.warning(self, "Keine Berechtigung", str(e)); return
        dialog = RoleDialog(self)
        if not dialog.exec_(): return
        try:
            self.auth.create_role(dialog.name.text(), dialog.description.text(), dialog.selected_permissions(), self.current_user["id"])
        except (AuthError, ValueError) as exc:
            QMessageBox.warning(self, "Rolle", str(exc))

    def assign_roles(self):
        uid = self._selected_id()
        if uid is None: QMessageBox.information(self, "Auswahl", "Bitte Benutzer auswählen."); return
        try: self.auth.require(self.current_user, Perm.MANAGE_ROLES)
        except PermissionDenied as e: QMessageBox.warning(self, "Keine Berechtigung", str(e)); return
        user = self.ctx.db.get_user(uid)
        selected = self.ctx.db.user_role_ids(uid)
        dialog = QDialog(self); dialog.setWindowTitle(f"Rollen: {user['username']}")
        layout = QVBoxLayout(dialog); checks = {}
        for role in self.ctx.db.list_roles():
            checkbox = QCheckBox(f"{role['name']} – {role.get('description') or ''}")
            checkbox.setChecked(role['id'] in selected or (user.get('is_admin') and role['id'] == 1))
            checkbox.setEnabled(not (user.get('is_admin') and role['id'] == 1))
            checks[role['id']] = checkbox; layout.addWidget(checkbox)
        save = QPushButton("Speichern"); save.clicked.connect(dialog.accept); layout.addWidget(save)
        if dialog.exec_():
            try:
                self.auth.set_roles(uid, {rid for rid, cb in checks.items() if cb.isChecked()}, self.current_user["id"])
                self.refresh()
            except (AuthError, ValueError) as exc: QMessageBox.warning(self, "Rollen", str(exc))
