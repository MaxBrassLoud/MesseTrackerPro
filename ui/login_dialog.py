from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QLabel, QLineEdit, QPushButton, QMessageBox,
                             QListWidget, QListWidgetItem, QWidget)

from core.auth import AuthService, AuthError
from ui.themes import get_theme, build_qss


class LoginDialog(QDialog):
    """Großer Anmeldebildschirm: Mitarbeiter wählen, dann Passwort eingeben."""
    def __init__(self, auth: AuthService, parent=None):
        super().__init__(parent)
        self.auth, self.user, self.session_token = auth, None, None
        self.setWindowTitle("Messe Tracker Pro – Mitarbeiteranmeldung")
        self.resize(980, 620)
        self.setMinimumSize(820, 520)
        self.setStyleSheet(build_qss(get_theme(auth.db.get_setting("theme", "Flipper"))))
        root = QHBoxLayout(self); root.setContentsMargins(28, 28, 28, 28)

        left = QWidget(); left_layout = QVBoxLayout(left)
        title = QLabel("Wer arbeitet heute?"); title.setObjectName("Title"); left_layout.addWidget(title)
        subtitle = QLabel("Wähle deinen Namen aus. Der Status zeigt die letzte erfasste Anwesenheit am aktiven Messetag.")
        subtitle.setObjectName("Sub"); subtitle.setWordWrap(True); left_layout.addWidget(subtitle)
        self.staff = QListWidget(); self.staff.setMinimumWidth(410)
        self.staff.itemSelectionChanged.connect(self._select_user)
        self.staff.itemDoubleClicked.connect(lambda _item: self.password.setFocus())
        left_layout.addWidget(self.staff, 1); root.addWidget(left, 3)

        right = QWidget(); right_layout = QVBoxLayout(right)
        self.person_name = QLabel("Mitarbeiter auswählen"); self.person_name.setObjectName("Title"); right_layout.addWidget(self.person_name)
        self.person_info = QLabel("Links einen Mitarbeiter auswählen, um die Anmeldung zu starten.")
        self.person_info.setObjectName("Sub"); self.person_info.setWordWrap(True); right_layout.addWidget(self.person_info)
        right_layout.addStretch(1)
        form = QFormLayout(); self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password); self.password.setEnabled(False)
        form.addRow("Passwort:", self.password); right_layout.addLayout(form)
        self.login_button = QPushButton("Anmelden"); self.login_button.setDefault(True); self.login_button.setEnabled(False); self.login_button.clicked.connect(self._submit); right_layout.addWidget(self.login_button)
        hint = QLabel("Du kannst dich nach der Arbeit abmelden; die Anwendung bleibt für den nächsten Mitarbeiter geöffnet.")
        hint.setWordWrap(True); hint.setObjectName("Sub"); right_layout.addWidget(hint)
        root.addWidget(right, 2)
        self.password.returnPressed.connect(self._submit)
        self._load_staff()

    def _load_staff(self):
        active_day = self.auth.db.get_active_fair_day()
        attendance = self.auth.db.current_attendance(active_day["fair_id"]) if active_day else {}
        employees = {employee.get("user_id"): employee for employee in self.auth.db.list_employees(active_only=True)}
        for user in self.auth.db.list_users():
            if not user.get("is_active"):
                continue
            employee = employees.get(user["id"])
            event = attendance.get(employee["id"], {}).get("event_type") if employee else None
            state = "🟢 Gerade am Stand" if event == "enter" else "⚪ Nicht am Stand"
            item = QListWidgetItem(f"{user.get('display_name') or user['username']}\n{state}")
            item.setData(Qt.UserRole, user["username"]); item.setData(Qt.UserRole + 1, state)
            self.staff.addItem(item)
        if self.staff.count(): self.staff.setCurrentRow(0)

    def _select_user(self):
        item = self.staff.currentItem()
        if not item: return
        username = item.data(Qt.UserRole); user = self.auth.db.get_user_by_username(username)
        self.person_name.setText(user.get("display_name") or username)
        self.person_info.setText(f"Benutzername: <b>{username}</b><br>Anwesenheit: {item.data(Qt.UserRole + 1)}")
        self.password.clear(); self.password.setEnabled(True); self.login_button.setEnabled(True)

    def _submit(self):
        item = self.staff.currentItem()
        if not item: return
        try:
            user, token = self.auth.login(item.data(Qt.UserRole), self.password.text())
        except AuthError as error:
            QMessageBox.warning(self, "Anmeldung fehlgeschlagen", str(error)); self.password.clear(); self.password.setFocus(); return
        self.user, self.session_token = user, token
        if user.get("must_change_password"):
            QMessageBox.information(self, "Passwort ändern", "Sie verwenden ein vorläufiges Passwort. Bitte ändern Sie es zeitnah über die Benutzerseite.")
        self.accept()
