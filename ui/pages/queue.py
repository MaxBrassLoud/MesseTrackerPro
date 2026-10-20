import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QFormLayout, QLineEdit, QTextEdit, QComboBox,
                             QMessageBox, QSplitter, QShortcut, QDialog,
                             QDialogButtonBox)
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from core.ocr import ocr_image
from core.duplicates import find_similar_contacts
from core.contact_extras import set_contact_extras
from ui.widgets import FullSizeImageDialog
from ui.dialogs.merge_dialog import MergeContactDialog


def _conf_color(c: float) -> str:
    if c >= 0.8:
        return "#00c853"
    if c >= 0.5:
        return "#ffb300"
    return "#ff6b6b"


# (key, label) – Reihenfolge entspricht der Anzeige im Formular
_FORM_FIELDS = [
    ("name", "Name"),
    ("company", "Firma"),
    ("position", "Position"),
    ("phone", "Telefon"),
    ("email", "E-Mail"),
    ("website", "Webseite"),
    ("address", "Adresse"),
]
_CONF_FIELDS = [
    ("Name", "name"),
    ("Firma", "company"),
    ("Position", "position"),
    ("Telefon", "phone"),
    ("E-Mail", "email"),
    ("Webseite", "website"),
    ("Adresse", "address"),
]


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
                "email": "", "website": "", "address": "",
                "needs_review": True, "confidence": 0.0,
                "field_confidence": {
                    "name": 0.0, "company": 0.0, "position": 0.0,
                    "phone": 0.0, "email": 0.0, "website": 0.0,
                    "address": 0.0,
                },
                "language": "mixed",
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
        # In-Memory-Cache für Webseite/Adresse pro Karte – diese Felder
        # sind nicht in card_queue.ocr_* persistiert.
        self._ocr_extra_cache: dict[int, dict] = {}
        self._dup_banner_holder = None

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
        for key, label in _FORM_FIELDS:
            w = QLineEdit()
            form.addRow(label, w)
            self.f[key] = w
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
        for w in self.f.values():
            w.clear()
        self.notes.clear()
        if self.status.count() > 0:
            self.status.setCurrentIndex(0)

    def _remove_dup_banner(self):
        if self._dup_banner_holder is not None:
            try:
                self.layout().removeWidget(self._dup_banner_holder)
                self._dup_banner_holder.setParent(None)
                self._dup_banner_holder.deleteLater()
            except Exception:
                pass
            self._dup_banner_holder = None

    def refresh(self):
        self._remove_dup_banner()
        self._rebuild_status_combo()
        self.list.clear()
        for c in self.ctx.db.list_card_queue():
            if c["status"] == "processed":
                continue
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

        # Grundfelder aus der Karte, Webseite/Adresse aus dem Cache
        cached = self._ocr_extra_cache.get(cid, {})
        for key, _label in _FORM_FIELDS:
            if key in ("website", "address"):
                self.f[key].setText(cached.get(key, "") or "")
            else:
                self.f[key].setText(c.get(f"ocr_{key}") or "")
        self.notes.clear()
        self._rebuild_status_combo()
        if self.status.currentText() == "—" and self.status.count() > 0:
            self.status.setCurrentIndex(0)
        self.confidence_label.setText("")
        self.btn_raw.setEnabled(False)
        self.btn_fullsize.setEnabled(os.path.exists(p))
        self._last_ocr_result = None
        self._remove_dup_banner()

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

        # Formular befüllen (inkl. Webseite + Adresse)
        for key, _label in _FORM_FIELDS:
            self.f[key].setText(result.get(key, "") or "")

        # Für Kartenwechsel zwischenspeichern (nicht in DB persistiert)
        self._ocr_extra_cache[cid] = {
            "website": result.get("website", ""),
            "address": result.get("address", ""),
        }

        if result.get("error"):
            self.confidence_label.setText(
                f'<span style="color:#ff6b6b;">⚠ {result["error"]}</span>')
            self.btn_raw.setEnabled(bool(result.get("raw_text")))
            return

        fc = result.get("field_confidence", {})
        overall = result.get("confidence", 0.0)
        lang = result.get("language", "mixed")
        parts = []
        for label, key in _CONF_FIELDS:
            c = fc.get(key, 0.0)
            if c > 0:
                parts.append(
                    f'<span style="color:{_conf_color(c)};">'
                    f'{label} {int(round(c*100))}%</span>')
            else:
                parts.append(f'<span style="color:#666;">{label} –</span>')
        lang_label = {"de": "DE", "en": "EN", "fr": "FR",
                      "es": "ES", "it": "IT"}.get(lang, "MEHRSPR.")
        self.confidence_label.setText(
            f'<span style="color:{_conf_color(overall)};">'
            f'OCR-Vertrauen gesamt: <b>{int(round(overall*100))}%</b></span> '
            f'<span style="color:#888;">· Sprache: {lang_label}</span><br>'
            + " · ".join(parts))

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

        # Dubletten-Vorschau
        probe = {
            "id": -1,
            "name": result.get("name", ""),
            "company": result.get("company", ""),
            "email": result.get("email", ""),
            "phone": result.get("phone", ""),
            "external_id": None,
        }
        matches = find_similar_contacts(self.ctx.db, probe)
        if matches:
            self._show_duplicate_banner(matches)

    def _show_duplicate_banner(self, matches):
        self._remove_dup_banner()
        if not matches:
            return

        top = matches[0][0]
        reasons = ", ".join(sorted(matches[0][1]))
        text = (f'⚠ <b>Mögliche Dublette:</b> '
                f'„{top.get("name") or "?"}“ '
                f'({top.get("company") or "ohne Firma"}) – '
                f'Ähnlichkeit: {reasons}')

        banner = QLabel(text)
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background:#430;color:#fc9;padding:8px;border-radius:6px;"
            "border:1px solid #a30;")

        btn = QPushButton("Zusammenführen…")
        btn.setObjectName("Ghost")
        btn.clicked.connect(lambda: self._prompt_merge_with_existing(top))

        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(banner, 1)
        h.addWidget(btn)

        self.layout().insertWidget(1, holder)
        self._dup_banner_holder = holder

    def _prompt_merge_with_existing(self, existing_contact):
        if not self.current_card:
            return
        with self.ctx.db._lock:
            row = self.ctx.db.conn.execute(
                "SELECT id FROM contacts WHERE card_image_path=? "
                "ORDER BY id DESC LIMIT 1",
                (self.current_card["image_path"],)).fetchone()
        if not row:
            QMessageBox.information(
                self, "Noch nicht gespeichert",
                "Bitte speichern Sie den Kontakt zuerst – danach kann "
                "die Dublette zusammengeführt werden. Die Prüfung läuft "
                "beim Speichern automatisch.")
            return
        saved = self.ctx.db.get_contact(row["id"])
        if not saved:
            return
        if MergeContactDialog(self, self.ctx.db, saved,
                              existing_contact).exec_():
            self.refresh()
            if self.main.pages.get("contacts"):
                self.main.pages["contacts"].refresh()

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
        address = vals.pop("address", "").strip()
        website = vals.pop("website", "").strip()

        new_id = self.ctx.db.create_contact(
            fair_id=self.current_card["fair_id"],
            fair_day_id=self.current_card["fair_day_id"],
            employee_id=self.current_card["employee_id"],
            source="Visitenkarte",
            card_image_path=self.current_card["image_path"],
            status=self.status.currentText(),
            notes=self.notes.toPlainText(),
            processing_status="ok", **vals)

        # Adresse + Webseite an Firma bzw. Kontakt speichern
        try:
            set_contact_extras(
                self.ctx.db, new_id, address=address, website=website)
        except Exception:
            import logging
            logging.exception("Zusatzfelder konnten nicht gespeichert werden.")

        self.ctx.db.update_card_ocr(
            self.current_card["id"], status="processed")

        # OCR-Details persistieren
        if self._last_ocr_result:
            import json as _json
            from datetime import datetime as _dt
            fc = self._last_ocr_result.get("field_confidence", {})
            lang = self._last_ocr_result.get("language", "mixed")
            raw = self._last_ocr_result.get("raw_text", "")
            try:
                with self.ctx.db._lock:
                    self.ctx.db.conn.execute(
                        """INSERT INTO contact_ocr_details
                           (contact_id, field_confidence_json,
                            detected_language, raw_text, ocr_engine,
                            processed_at)
                           VALUES (?,?,?,?,?,?)
                           ON CONFLICT(contact_id) DO UPDATE SET
                             field_confidence_json=excluded.field_confidence_json,
                             detected_language=excluded.detected_language,
                             raw_text=excluded.raw_text,
                             processed_at=excluded.processed_at""",
                        (new_id, _json.dumps(fc, ensure_ascii=False),
                         lang, raw, "tesseract",
                         _dt.now().isoformat(timespec="seconds")))
                    self.ctx.db.conn.commit()
            except Exception:
                pass

        # Dublettenprüfung nach dem Speichern
        saved = self.ctx.db.get_contact(new_id)
        if saved:
            matches = find_similar_contacts(self.ctx.db, saved)
            if matches:
                top, reasons, _score = matches[0]
                if QMessageBox.question(
                        self, "Mögliche Dublette",
                        f"Der gespeicherte Kontakt ähnelt #{top['id']} "
                        f"„{top.get('name') or '?'}“ "
                        f"({top.get('company') or 'ohne Firma'}) "
                        f"[{', '.join(sorted(reasons))}].\n\n"
                        f"Jetzt zusammenführen?",
                        QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                    MergeContactDialog(self, self.ctx.db, saved, top).exec_()

        current_row = self.list.currentRow()
        self.refresh()
        if self.main.pages.get("contacts"):
            self.main.pages["contacts"].refresh()

        if self.list.count() > 0:
            next_row = min(max(0, current_row), self.list.count() - 1)
            self.list.setCurrentRow(next_row)