from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QMessageBox)
from core.auth import AuthService, AuthError


class ChangePasswordDialog(QDialog):
    def __init__(self, auth: AuthService, user: dict, parent=None):
        super().__init__(parent)
        self.auth, self.user = auth, user
        self.setWindowTitle("Passwort ändern")
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        self.inp_old = QLineEdit(); self.inp_old.setEchoMode(QLineEdit.Password)
        self.inp_new1 = QLineEdit(); self.inp_new1.setEchoMode(QLineEdit.Password)
        self.inp_new2 = QLineEdit(); self.inp_new2.setEchoMode(QLineEdit.Password)
        form.addRow("Aktuelles Passwort:", self.inp_old)
        form.addRow("Neues Passwort:", self.inp_new1)
        form.addRow("Neues Passwort wiederholen:", self.inp_new2)
        b = QPushButton("Passwort ändern")
        b.clicked.connect(self._submit)
        form.addRow(b)

    def _submit(self):
        if self.inp_new1.text() != self.inp_new2.text():
            QMessageBox.warning(self, "Passwort",
                                "Neue Passwörter stimmen nicht überein.")
            return
        try:
            ok = self.auth.change_own_password(
                self.user["id"], self.inp_old.text(), self.inp_new1.text())
        except (AuthError, ValueError) as e:
            QMessageBox.warning(self, "Nicht möglich", str(e)); return
        if not ok:
            QMessageBox.warning(self, "Fehler",
                                "Aktuelles Passwort ist falsch."); return
        QMessageBox.information(self, "Erfolg", "Passwort wurde geändert.")
        self.accept()