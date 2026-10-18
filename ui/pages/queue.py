import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QFormLayout, QLineEdit, QTextEdit, QComboBox,
                             QMessageBox, QSplitter, QShortcut, QDialog,
                             QDialogButtonBox)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from core.ocr import ocr_image
from ui.widgets import FullSizeImageDialog


class OcrWorker(QThread):
    done = pyqtSignal(int, dict)

    def __init__(self, card_id, path):
        super().__init__()
        self.card_id = card_id
        self.path = path

    def run(self):
        try:
            result = ocr_image(self.path)
        except Exception as e:
            result = {
                "name": "", "company": "", "position": "", "phone": "",
                "email": "", "needs_review": True, "confidence": 0.0,
                "raw_text": "", "error": f"Unerwarteter Fehler: {e}",
            }
        self.done.emit(self.card_id, result)


class RawTextDialog(QDialog):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.setWindowTitle("OCR-Rohtext")
        self.resize(600, 400)
        v = QVBoxLayout(self)
        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text or "(kein Rohtext)")
        v.addWidget(edit)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)


class QueuePage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        self.current_card = None

        self._ocr_running = False
        self._current_worker = None
        self._last_ocr_result = None

        v = QVBoxLayout(self)
        t = QLabel("Visitenkarten-Warteschlange")
        t.setObjectName("Title")
        v.addWidget(t)
        split = QSplitter(Qt.Horizontal)
        v.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.on_select)
        lv.addWidget(self.list)

        self.btn_ocr = QPushButton("OCR starten")
        self.btn_ocr.clicked.connect(self.run_ocr)
        lv.addWidget(self.btn_ocr)

        self.btn_raw = QPushButton("Rohtext anzeigen")
        self.btn_raw.setObjectName("Ghost")
        self.btn_raw.setEnabled(False)
        self.btn_raw.clicked.connect(self.show_raw)
        lv.addWidget(self.btn_raw)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)

        self.preview = QLabel("Kein Bild")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setStyleSheet(
            "background:#000;border:1px solid #333;"
            "color:#888;font-size:10pt;")
        self.preview.setCursor(Qt.ArrowCursor)
        self.preview.setToolTip("")
        self.preview.mousePressEvent = self._on_preview_click
        rv.addWidget(self.preview)

        self.btn_fullsize = QPushButton("🔍 Bild groß anzeigen")
        self.btn_fullsize.setObjectName("Ghost")
        self.btn_fullsize.clicked.connect(self.show_full_image)
        self.btn_fullsize.setEnabled(False)
        rv.addWidget(self.btn_fullsize)

        self.confidence_label = QLabel("")
        self.confidence_label.setStyleSheet("padding:4px;font-size:9pt;")
        self.confidence_label.setWordWrap(True)
        rv.addWidget(self.confidence_label)

        form = QFormLayout()
        self.f = {}
        for k in ("name", "company", "position", "phone", "email"):
            w = QLineEdit()
            form.addRow(k.capitalize(), w)
            self.f[k] = w
        self.status = QComboBox()
        form.addRow("Status", self.status)
        self.notes = QTextEdit()
        form.addRow("Notizen", self.notes)
        rv.addLayout(form)

        row = QHBoxLayout()
        self.btn_save = QPushButton("Speichern (Strg+Enter)")
        self.btn_save.clicked.connect(self.save)
        self.btn_skip = QPushButton("Überspringen")
        self.btn_skip.setObjectName("Ghost")
        self.btn_skip.clicked.connect(self.refresh)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_skip)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([350, 700])
        QShortcut(QKeySequence("Ctrl+Return"), self, self.save)

    def _rebuild_status_combo(self, keep_current=True):
        current = self.status.currentText() if keep_current else ""
        self.status.clear()
        names = [s["name"]
                 for s in self.ctx.db.list_statuses(active_only=True)]
        if current and current not in names:
            names.append(current)
        if not names:
            names = ["—"]
        self.status.addItems(names)
        idx = self.status.findText(current)
        if idx >= 0:
            self.status.setCurrentIndex(idx)

    def _clear_form(self):
        """FIX #5: Felder bei leerem Zustand leeren."""
        for w in self.f.values():
            w.clear()
        self.notes.clear()
        # Status-Dropdown auf ersten Eintrag
        if self.status.count() > 0:
            self.status.setCurrentIndex(0)

    def refresh(self):
        self._rebuild_status_combo()
        self.list.clear()
        for c in self.ctx.db.list_card_queue():
            if c["status"] == "processed":
                continue
            # 'orphaned' Karten werden mit Hinweis angezeigt
            label = f"#{c['id']} · {c['status']} · {c['created_at']}"
            if c["status"] == "orphaned":
                label = f"#{c['id']} · ⚠ verwaist · {c['created_at']}"
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, c["id"])
            self.list.addItem(it)
        self.current_card = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Kein Bild")
        self.preview.setCursor(Qt.ArrowCursor)
        self.preview.setToolTip("")
        self.confidence_label.setText("")
        self.btn_raw.setEnabled(False)
        self.btn_fullsize.setEnabled(False)
        self._last_ocr_result = None
        self._clear_form()

    def _all_active_cards(self):
        cards = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            cid = it.data(Qt.UserRole)
            c = self.ctx.db.get_card(cid)
            if c and c["status"] != "processed":
                cards.append(c)
        return cards

    def on_select(self, cur, _):
        if not cur:
            return
        cid = cur.data(Qt.UserRole)
        c = self.ctx.db.get_card(cid)
        self.current_card = c
        p = c["image_path"]
        if os.path.exists(p):
            pix = QPixmap(p)
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(
                    self.preview.size(), Qt.KeepAspectRatio,
                    Qt.SmoothTransformation))
                self.preview.setCursor(Qt.PointingHandCursor)
                self.preview.setToolTip(
                    "Klicken für Großansicht (Pfeiltasten zum Blättern)")
            else:
                self.preview.setPixmap(QPixmap())
                self.preview.setText("Bild nicht lesbar")
                self.preview.setCursor(Qt.ArrowCursor)
                self.preview.setToolTip("")
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Bilddatei nicht gefunden")
            self.preview.setCursor(Qt.ArrowCursor)
            self.preview.setToolTip("")

        for k in ("name", "company", "position", "phone", "email"):
            self.f[k].setText(c.get(f"ocr_{k}") or "")
        self.notes.clear()
        self._rebuild_status_combo()
        if self.status.currentText() == "—" and self.status.count() > 0:
            self.status.setCurrentIndex(0)
        self.confidence_label.setText("")
        self.btn_raw.setEnabled(False)
        self.btn_fullsize.setEnabled(os.path.exists(p))
        self._last_ocr_result = None

    def _on_preview_click(self, event):
        if event.button() == Qt.LeftButton:
            self.show_full_image()

    def show_full_image(self):
        cards = self._all_active_cards()
        if not cards or not self.current_card:
            QMessageBox.information(
                self, "Keine Karte",
                "Bitte zuerst eine Karte in der Liste auswählen.")
            return

        start_idx = 0
        for i, c in enumerate(cards):
            if c["id"] == self.current_card["id"]:
                start_idx = i
                break

        dlg = FullSizeImageDialog(self, cards, start_idx)
        dlg.exec_()

        new_id = cards[dlg.index]["id"] if cards else None
        if new_id and (not self.current_card or
                       new_id != self.current_card["id"]):
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == new_id:
                    self.list.setCurrentRow(i)
                    break

    def run_ocr(self):
        if not self.current_card or self._ocr_running:
            return

        self._ocr_running = True
        self.btn_ocr.setEnabled(False)
        self.btn_ocr.setText("OCR läuft …")
        self.btn_raw.setEnabled(False)

        self._current_worker = OcrWorker(
            self.current_card["id"], self.current_card["image_path"])
        self._current_worker.done.connect(self.on_ocr_done)
        self._current_worker.finished.connect(self._on_worker_finished)
        self._current_worker.start()

    def _on_worker_finished(self):
        self._current_worker = None

    def on_ocr_done(self, cid, result):
        self._ocr_running = False
        self.btn_ocr.setEnabled(True)
        self.btn_ocr.setText("OCR starten")
        self._last_ocr_result = result

        if not self.current_card or self.current_card["id"] != cid:
            return

        for k in ("name", "company", "position", "phone", "email"):
            self.f[k].setText(result.get(k, ""))

        if result.get("error"):
            self.confidence_label.setText(
                f'<span style="color:#ff6b6b;">⚠ {result["error"]}</span>')
            self.btn_raw.setEnabled(bool(result.get("raw_text")))
            return

        conf = result.get("confidence", 0.0)
        pct = int(round(conf * 100))
        if conf >= 0.8:
            color, hint = "#00c853", "sicher erkannt"
        elif conf >= 0.5:
            color, hint = "#ffb300", "teilweise erkannt – bitte prüfen"
        else:
            color, hint = "#ff6b6b", "unsicher – bitte manuell ergänzen"

        self.confidence_label.setText(
            f'<span style="color:{color};">OCR-Vertrauen: '
            f'<b>{pct}%</b> ({hint})</span>')

        new_status = ("needs_review" if result.get("needs_review")
                      else "ocr_done")
        self.ctx.db.update_card_ocr(
            cid, status=new_status,
            ocr_name=result.get("name", ""),
            ocr_company=result.get("company", ""),
            ocr_position=result.get("position", ""),
            ocr_phone=result.get("phone", ""),
            ocr_email=result.get("email", ""))

        self.btn_raw.setEnabled(bool(result.get("raw_text")))

    def show_raw(self):
        if not self._last_ocr_result:
            return
        RawTextDialog(self, self._last_ocr_result.get("raw_text", "")).exec_()

    def save(self):
        if not self.current_card:
            QMessageBox.information(self, "Kein Eintrag",
                                    "Bitte Eintrag auswählen.")
            return
        vals = {k: w.text() for k, w in self.f.items()}
        self.ctx.db.create_contact(
            fair_id=self.current_card["fair_id"],
            fair_day_id=self.current_card["fair_day_id"],
            employee_id=self.current_card["employee_id"],
            source="Visitenkarte",
            card_image_path=self.current_card["image_path"],
            status=self.status.currentText(),
            notes=self.notes.toPlainText(),
            processing_status="ok", **vals)
        self.ctx.db.update_card_ocr(
            self.current_card["id"], status="processed")

        # FIX A1: Auto-Advance
        current_row = self.list.currentRow()
        self.refresh()
        self.main.pages["contacts"].refresh()

        if self.list.count() > 0:
            next_row = min(max(0, current_row), self.list.count() - 1)
            self.list.setCurrentRow(next_row)