import sys
import traceback

from PyQt5.QtWidgets import QApplication, QMessageBox

from config import DB_PATH, WEB_PORT
from database.db import Database
from web.server import start_server
from ui.main_window import MainWindow


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
    """Fängt jede unbehandelte Exception aus Qt-Slots ab.

    Verhindert, dass PyQt5 qFatal()/abort() aufruft und die App mit
    0xC0000409 abstürzt. Stattdessen: Traceback in Konsole, Dialog
    in der UI, Anwendung bleibt am Leben.
    """
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("[UNBEHANDELTE EXCEPTION]\n" + tb_text, file=sys.stderr)

    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Unerwarteter Fehler")
        msg.setText(
            f"Es ist ein unerwarteter Fehler aufgetreten:\n\n"
            f"{exc_type.__name__}: {exc_value}")
        msg.setDetailedText(tb_text)
        msg.setInformativeText(
            "Die Anwendung läuft weiter. Bitte prüfe die Konsole für Details.")
        msg.exec_()
    except Exception:
        # Falls Qt selbst schon kaputt ist, kein erneuter Crash
        pass


def main():
    sys.excepthook = _excepthook

    db = Database(str(DB_PATH))
    db.init_db()
    start_server(db)

    print("[Messe Tracker Pro]")
    print(f"  Lokaler Webserver: http://{_local_ip()}:{WEB_PORT}")
    print(f"  Datenbank:         {DB_PATH}")
    print()

    app = QApplication(sys.argv)
    w = MainWindow(db)
    w.show()
    code = app.exec_()
    db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()