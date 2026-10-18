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
    """Erzeugt höchstens ein Auto-Backup pro Kalendertag."""
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

    # QApplication früh erstellen, damit wir bei Startup-Fehlern
    # MessageBoxen anzeigen können.
    app = QApplication(sys.argv)

    # ---------------------------------------------------------------
    # Pending Restore MUSS vor dem Öffnen der DB laufen
    # ---------------------------------------------------------------
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
        # Weiter mit vorhandener DB

    db = Database(str(DB_PATH))
    db.init_db()

    _auto_backup(db)

    start_server(db)

    print("[Messe Tracker Pro]")
    print(f"  Lokaler Webserver: http://{local_ip()}:{WEB_PORT}")
    print(f"  Datenbank:         {DB_PATH}")
    print(f"  Logfile:           {LOG_PATH}")
    print()

    w = MainWindow(db)
    w.show()
    code = app.exec_()
    db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()