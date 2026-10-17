import io
import socket

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QDialog, QApplication,
    QHeaderView, QAbstractItemView)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

from config import WEB_PORT

try:
    import qrcode
    _QR = True
except Exception:
    _QR = False


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


class QRDialog(QDialog):
    def __init__(self, parent, url, employee_name="", warning=""):
        super().__init__(parent)
        self.setWindowTitle("QR-Code für Smartphone")
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)

        if employee_name:
            n = QLabel(employee_name)
            n.setStyleSheet(
                "font-size:14pt;color:#FF8200;font-weight:bold;")
            v.addWidget(n)

        if _QR:
            try:
                img = qrcode.make(url)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                pix = QPixmap()
                pix.loadFromData(buf.getvalue())
                lbl = QLabel()
                lbl.setPixmap(pix.scaled(280, 280, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
                v.addWidget(lbl)
            except Exception as e:
                v.addWidget(QLabel(
                    f"QR-Code konnte nicht erzeugt werden:\n{e}"))
        else:
            v.addWidget(QLabel(
                "QR-Bibliothek fehlt (pip install qrcode[pil])."))

        url_label = QLabel(f"URL: {url}")
        url_label.setWordWrap(True)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_label.setStyleSheet("color:#aaa;font-size:9pt;")
        v.addWidget(url_label)

        copy_btn = QPushButton("URL kopieren")
        copy_btn.setObjectName("Ghost")

        def _copy():
            QApplication.clipboard().setText(url)
            copy_btn.setText("✔ Kopiert")

        copy_btn.clicked.connect(_copy)
        v.addWidget(copy_btn)

        if warning:
            w = QLabel(warning)
            w.setStyleSheet("color:#ff8800;")
            w.setWordWrap(True)
            v.addWidget(w)

        if "127.0.0.1" in url:
            warn_ip = QLabel(
                "⚠️ Lokale Netzwerk-IP nicht ermittelbar – QR funktioniert "
                "so nicht vom Smartphone. Bitte WLAN prüfen.")
            warn_ip.setStyleSheet("color:#ff4444;")
            warn_ip.setWordWrap(True)
            v.addWidget(warn_ip)

        info = QLabel(
            "Smartphone und Laptop müssen im selben WLAN sein. Beim ersten "
            f"Start ggf. die Firewall-Freigabe für Python/Port {WEB_PORT} "
            "bestätigen.")
        info.setStyleSheet("color:#888;font-size:9pt;")
        info.setWordWrap(True)
        v.addWidget(info)


class EmployeesPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main

        v = QVBoxLayout(self)

        title = QLabel("Mitarbeiter")
        title.setObjectName("Title")
        v.addWidget(title)

        # Neuen Mitarbeiter anlegen
        row = QHBoxLayout()
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Name")
        self.inp_email = QLineEdit()
        self.inp_email.setPlaceholderText("E-Mail (optional)")
        b = QPushButton("Mitarbeiter anlegen")
        b.clicked.connect(self.add_emp)
        row.addWidget(self.inp_name, 1)
        row.addWidget(self.inp_email, 1)
        row.addWidget(b)
        v.addLayout(row)

        # Tabelle
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Name", "E-Mail", "Anwesend", "Aktiv"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        v.addWidget(self.table, 1)

        # Aktionsleiste
        act = QHBoxLayout()
        self.btn_qr = QPushButton("QR-Code anzeigen")
        self.btn_qr.clicked.connect(self.show_qr)
        act.addWidget(self.btn_qr)

        self.btn_toggle = QPushButton("Aktiv/Inaktiv umschalten")
        self.btn_toggle.setObjectName("Ghost")
        self.btn_toggle.clicked.connect(self.toggle_active)
        act.addWidget(self.btn_toggle)

        refresh = QPushButton("Aktualisieren")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self.refresh)
        act.addWidget(refresh)

        act.addStretch(1)
        v.addLayout(act)

        self._update_action_buttons()

    def _update_action_buttons(self):
        has_sel = self.table.currentRow() >= 0
        self.btn_qr.setEnabled(has_sel)
        self.btn_toggle.setEnabled(has_sel)

    def refresh(self):
        emps = self.ctx.db.list_employees()

        att = {}
        if self.ctx.current_fair_id:
            att = self.ctx.db.current_attendance(self.ctx.current_fair_id)

        self.table.setRowCount(len(emps))
        for r, e in enumerate(emps):
            self.table.setItem(r, 0, QTableWidgetItem(str(e["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(e.get("name") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(e.get("email") or ""))

            info = att.get(e["id"])
            if info and info["event_type"] == "enter":
                status = f"🟢 {_fmt_dt(info['timestamp'])}"
            elif info and info["event_type"] == "leave":
                status = f"⚪ {_fmt_dt(info['timestamp'])}"
            elif self.ctx.current_fair_id:
                status = "❔ —"
            else:
                status = "—"
            self.table.setItem(r, 3, QTableWidgetItem(status))
            self.table.setItem(
                r, 4,
                QTableWidgetItem("Ja" if e.get("active") else "Nein"))

        self._update_action_buttons()

    def _selected_employee(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Mitarbeiter auswählen",
                "Bitte zuerst einen Mitarbeiter in der Tabelle auswählen.")
            return None
        try:
            emp_id = int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            return None
        for e in self.ctx.db.list_employees():
            if e["id"] == emp_id:
                return e
        return None

    def add_emp(self):
        name = self.inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehlt", "Name erforderlich.")
            return
        _emp_id, token = self.ctx.db.create_employee(
            name, self.inp_email.text().strip())
        self.inp_name.clear()
        self.inp_email.clear()
        self.refresh()
        if QMessageBox.question(
                self, "QR-Code anzeigen",
                f"Mitarbeiter „{name}“ wurde angelegt.\n\n"
                "Jetzt QR-Code anzeigen?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.show_qr_for_token(token, name)

    def show_qr(self):
        emp = self._selected_employee()
        if not emp:
            return
        self.show_qr_for_token(emp["token"], emp["name"])

    def show_qr_for_token(self, token, name):
        url = f"http://{local_ip()}:{WEB_PORT}/scan/{token}"
        ad = self.ctx.db.get_active_fair_day()

        warnings = []
        if not ad:
            warnings.append(
                "⚠️ Aktuell läuft kein Messetag. Bitte zuerst auf der "
                "Startseite einen Messetag starten – sonst schlagen "
                "Uploads und Statuswechsel fehl.")

        # Prüfen, ob der Mitarbeiter aktiv ist
        emp = self.ctx.db.get_employee_by_token(token)
        if emp and not emp.get("active"):
            warnings.append(
                "⛔ Dieser Mitarbeiter ist deaktiviert. Der QR-Code "
                "führt zu einer Sperrseite. Bitte zuerst in der "
                "Mitarbeitertabelle aktivieren.")

        QRDialog(self, url, name, "\n\n".join(warnings)).exec_()

    def toggle_active(self):
        emp = self._selected_employee()
        if not emp:
            return
        self.ctx.db.update_employee(
            emp["id"], active=0 if emp.get("active") else 1)
        self.refresh()