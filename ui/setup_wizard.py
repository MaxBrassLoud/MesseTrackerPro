from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel,
                             QLineEdit, QPushButton, QMessageBox)
from core.auth import AuthService, AuthError


class SetupWizard(QDialog):
    def __init__(self, auth: AuthService, parent=None):
        super().__init__(parent)
        self.auth = auth
        self.setWindowTitle("Messe Tracker Pro – Ersteinrichtung")
        self.setMinimumWidth(460)
        self.setModal(True)

        v = QVBoxLayout(self)
        t = QLabel("Willkommen bei Messe Tracker Pro")
        t.setStyleSheet("font-size:16pt;font-weight:700;color:#FF8200;")
        v.addWidget(t)
        h = QLabel(
            "Bitte legen Sie das erste Administratorkonto an. Dieses Konto "
            "hat alle Rechte und kann weitere Benutzer verwalten.\n\n"
            "Nach Abschluss der Einrichtung ist eine Anmeldung bei jedem "
            "Start erforderlich.")
        h.setWordWrap(True)
        h.setStyleSheet("color:#aaa;")
        v.addWidget(h)

        form = QFormLayout()
        self.inp_user = QLineEdit()
        self.inp_user.setPlaceholderText("z. B. admin")
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Anzeigename (optional)")
        self.inp_pw1 = QLineEdit()
        self.inp_pw1.setEchoMode(QLineEdit.Password)
        self.inp_pw2 = QLineEdit()
        self.inp_pw2.setEchoMode(QLineEdit.Password)
        form.addRow("Benutzername:", self.inp_user)
        form.addRow("Anzeigename:", self.inp_name)
        form.addRow("Passwort:", self.inp_pw1)
        form.addRow("Passwort wiederholen:", self.inp_pw2)
        v.addLayout(form)

        hint = QLabel("Passwort: mindestens 10 Zeichen, keine Leerzeichen "
                      "am Anfang/Ende.")
        hint.setStyleSheet("color:#888;font-size:9pt;")
        v.addWidget(hint)

        b = QPushButton("Administrator anlegen und starten")
        b.clicked.connect(self._submit)
        v.addWidget(b)

    def _submit(self):
        pw1, pw2 = self.inp_pw1.text(), self.inp_pw2.text()
        if pw1 != pw2:
            QMessageBox.warning(self, "Passwort",
                                "Die Passwörter stimmen nicht überein.")
            return
        try:
            self.auth.create_initial_admin(
                username=self.inp_user.text(),
                password=pw1,
                display_name=self.inp_name.text().strip())
        except (AuthError, ValueError) as e:
            QMessageBox.warning(self, "Eingabe", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Fehler",
                f"Administrator konnte nicht angelegt werden:\n{e}")
            return
        self.accept()