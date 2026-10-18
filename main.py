# main.py
import sys
import traceback
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PyQt5.QtWidgets import QApplication, QMessageBox

from config import DB_PATH, WEB_PORT, DATA_DIR, BACKUP_DIR
from database.db import Database
from web.server import start_server
from ui.main_window import MainWindow
from core.backup import (
    create_backup, apply_pending_restore, BackupError
)
from core.net import local_ip

LOG_PATH = DATA_DIR / "messe_tracker.log"


def _setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)


def _auto_backup(db):
    today = datetime.now().date().isoformat()
    last = db.get_setting("last_auto_backup_date", "")
    if last == today:
        logging.info("Auto-Backup heute bereits erstellt.")
        return
    try:
        auto_path = BACKUP_DIR / (
            f"auto_backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
        )
        create_backup(str(auto_path), auto_rotate=True)
        db.set_setting("last_auto_backup_date", today)
        logging.info("Automatisches Backup erstellt: %s", auto_path)
    except Exception as e:
        logging.exception("Automatisches Backup fehlgeschlagen: %s", e)


def _excepthook(exc_type, exc_value, exc_tb):
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error("Unbehandelte Exception:\n%s", tb_text)
    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Unerwarteter Fehler")
        msg.setText(
            f"Es ist ein unerwarteter Fehler aufgetreten:\n\n"
            f"{exc_type.__name__}: {exc_value}")
        msg.setDetailedText(tb_text)
        msg.setInformativeText(
            "Die Anwendung läuft weiter. Details im Logfile: "
            f"{LOG_PATH}")
        msg.exec_()
    except Exception:
        pass


def main():
    _setup_logging()
    sys.excepthook = _excepthook

    app = QApplication(sys.argv)

    # 1. Pending Restore vor dem Öffnen der DB
    try:
        if apply_pending_restore():
            QMessageBox.information(
                None, "Wiederherstellung",
                "Das Backup wurde erfolgreich eingespielt.")
    except Exception as e:
        logging.exception("Wiederherstellung fehlgeschlagen.")
        QMessageBox.critical(
            None, "Wiederherstellung fehlgeschlagen",
            f"Das vorbereitete Backup konnte nicht eingespielt werden:\n\n"
            f"{e}\n\n"
            f"Die vorhandene Datenbank wurde beibehalten. Die ZIP-Datei "
            f"bleibt liegen und wird beim nächsten Start erneut versucht.")

    # 2. DB öffnen & migrieren
    db = Database(str(DB_PATH))
    db.init_db()

    _auto_backup(db)

    # Der QR-/Upload-Webserver ist bewusst unabhängig von der Desktop-Sitzung:
    # Mitarbeitende müssen während eines Anmelde- oder Benutzerwechsels weiter
    # Visitenkarten und Kontakte erfassen können.
    start_server(db)

    # 3. Auth-Service
    from core.auth import AuthService, AuthError
    auth = AuthService(db)

    # 4. Setup-Wizard ODER Login
    user = None
    session_token = None
    if auth.is_setup_required():
        from ui.setup_wizard import SetupWizard
        wiz = SetupWizard(auth)
        if not wiz.exec_():
            logging.info("Ersteinrichtung abgebrochen.")
            db.close()
            sys.exit(0)
        try:
            user, session_token = auth.login(
                wiz.inp_user.text().strip(), wiz.inp_pw1.text())
        except AuthError as e:
            QMessageBox.critical(None, "Fehler",
                f"Anmeldung nach Einrichtung fehlgeschlagen:\n{e}")
            db.close()
            sys.exit(1)
    else:
        from ui.login_dialog import LoginDialog
        dlg = LoginDialog(auth)
        if not dlg.exec_() or not dlg.user:
            logging.info("Anmeldung abgebrochen.")
            db.close()
            sys.exit(0)
        user, session_token = dlg.user, dlg.session_token

    # 5. Desktop-Sitzung ist erfolgreich angemeldet.
    print("[Messe Tracker Pro]")
    print(f"  Lokaler Webserver: http://{local_ip()}:{WEB_PORT}")
    print(f"  Datenbank:         {DB_PATH}")
    print(f"  Logfile:           {LOG_PATH}")
    print(f"  Angemeldet als:    {user['username']}"
          f"{' (Admin)' if user.get('is_admin') else ''}")
    print()

    # 6. Hauptfenster; Exit-Code 42 bedeutet Benutzerwechsel, nicht Programmende.
    w = None
    last_code = 0
    while True:
        w = MainWindow(db, auth, user, session_token)
        w.show()
        last_code = app.exec_()

        if last_code != 42:
            break

        # Benutzerwechsel wurde innerhalb von MainWindow._do_logout()
        # vorbereitet: neue Credentials stehen in _pending_user/_pending_token.
        new_user = getattr(w, "_pending_user", None)
        new_token = getattr(w, "_pending_token", None)

        # Altes Fenster sauber abbauen
        try:
            w.hide()
            w.close()
            w.deleteLater()
        except Exception:
            logging.exception("Altes MainWindow konnte nicht abgebaut werden.")

        if not new_user:
            # Abbruch der Neuanmeldung → Programm beenden
            last_code = 0
            break

        user, session_token = new_user, new_token
        # Neue Iteration baut ein frisches MainWindow mit dem neuen Benutzer

    # Beim Beenden: aktuelle Session revoken
    try:
        auth.logout(session_token)
    except Exception:
        pass
    db.close()
    sys.exit(last_code)


if __name__ == "__main__":
    main()