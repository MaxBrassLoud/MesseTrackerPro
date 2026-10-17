# main.py
import sys
import traceback
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

from config import DB_PATH, WEB_PORT, DATA_DIR
from database.db import Database
from web.server import start_server
from ui.main_window import MainWindow
from core.backup import create_backup, BackupError

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
    # Konsole
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

def _auto_backup():
    try:
        auto_path = DATA_DIR / "backups" / (
            f"auto_backup_{__import__('datetime').datetime.now():%Y%m%d_%H%M%S}.zip"
        )
        create_backup(str(auto_path), auto_rotate=True)
        logging.info("Automatisches Backup erstellt: %s", auto_path)
    except Exception as e:
        logging.exception("Automatisches Backup fehlgeschlagen: %s", e)

def _local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"

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

    db = Database(str(DB_PATH))
    db.init_db()

    # Automatisches Backup beim Start (nur einmal pro Tag)
    _auto_backup()

    start_server(db)

    print("[Messe Tracker Pro]")
    print(f"  Lokaler Webserver: http://{_local_ip()}:{WEB_PORT}")
    print(f"  Datenbank:         {DB_PATH}")
    print(f"  Logfile:           {LOG_PATH}")
    print()

    app = QApplication(sys.argv)
    w = MainWindow(db)
    w.show()
    code = app.exec_()
    db.close()
    sys.exit(code)

if __name__ == "__main__":
    main()