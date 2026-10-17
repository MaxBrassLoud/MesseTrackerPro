from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QComboBox, QGroupBox, QMessageBox)


class HomePage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        self.title = QLabel("Start")
        self.title.setObjectName("Title")
        v.addWidget(self.title)

        g = QGroupBox("Messe")
        gv = QVBoxLayout(g)
        self.fair_combo = QComboBox()
        self.fair_combo.currentIndexChanged.connect(self.on_fair_change)
        gv.addWidget(QLabel("Aktive Messe:"))
        gv.addWidget(self.fair_combo)
        self.no_fair_hint = QLabel(
            "Noch keine Messe angelegt. Bitte zuerst unter „Messen“ eine Messe anlegen.")
        self.no_fair_hint.setStyleSheet("color:#ff8800;")
        self.no_fair_hint.setWordWrap(True)
        self.no_fair_hint.setVisible(False)
        gv.addWidget(self.no_fair_hint)
        self.btn_goto_fairs = QPushButton("Zu den Messen")
        self.btn_goto_fairs.setObjectName("Ghost")
        self.btn_goto_fairs.clicked.connect(lambda: self.main.show_page("fairs"))
        self.btn_goto_fairs.setVisible(False)
        gv.addWidget(self.btn_goto_fairs)
        v.addWidget(g)

        g2 = QGroupBox("Messetag")
        gv2 = QVBoxLayout(g2)
        self.day_status = QLabel("-")
        self.day_status.setObjectName("Sub")
        gv2.addWidget(self.day_status)
        row = QHBoxLayout()
        self.btn_start = QPushButton("Neuen Messetag starten")
        self.btn_start.clicked.connect(self.start_day)
        self.btn_end = QPushButton("Aktiven Messetag beenden")
        self.btn_end.setObjectName("Ghost")
        self.btn_end.clicked.connect(self.end_day)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_end)
        gv2.addLayout(row)
        v.addWidget(g2)

        g3 = QGroupBox("Schnellzugriff")
        gv3 = QVBoxLayout(g3)
        for label, key in [("Kundenkartei öffnen", "contacts"),
                           ("Visitenkarten-Warteschlange", "queue"),
                           ("Mitarbeiter verwalten", "employees")]:
            b = QPushButton(label)
            b.setObjectName("Ghost")
            b.clicked.connect(lambda _, k=key: self.main.show_page(k))
            gv3.addWidget(b)
        v.addWidget(g3)
        v.addStretch(1)

    def refresh(self):
        fairs = self.ctx.db.list_fairs()
        self.fair_combo.blockSignals(True)
        self.fair_combo.clear()

        if not fairs:
            self.ctx.current_fair_id = None
            self.ctx.current_fair_day_id = None
            self.fair_combo.blockSignals(False)
            self.no_fair_hint.setVisible(True)
            self.btn_goto_fairs.setVisible(True)
            self._update_day_status()
            return

        self.no_fair_hint.setVisible(False)
        self.btn_goto_fairs.setVisible(False)
        for f in fairs:
            self.fair_combo.addItem(f["name"], f["id"])

        idx = 0
        if self.ctx.current_fair_id:
            found = self.fair_combo.findData(self.ctx.current_fair_id)
            if found >= 0:
                idx = found
        self.fair_combo.setCurrentIndex(idx)
        # Wichtig: Kontext explizit setzen, da Signal blockiert war
        self.ctx.set_fair(self.fair_combo.itemData(idx))
        self.fair_combo.blockSignals(False)
        self._update_day_status()

    def _update_day_status(self):
        ad = self.ctx.db.get_active_fair_day()
        if ad and ad["fair_id"] == self.ctx.current_fair_id:
            self.ctx.current_fair_day_id = ad["id"]
            self.day_status.setText(
                f"🟢 Aktiv seit {ad['started_at']} (Tag-ID {ad['id']}, {ad['day_date']})")
            self.btn_start.setEnabled(False)
            self.btn_end.setEnabled(True)
        else:
            self.ctx.current_fair_day_id = None
            self.day_status.setText(
                "⚪ Kein aktiver Messetag." if self.ctx.current_fair_id
                else "⚪ Keine Messe ausgewählt.")
            self.btn_start.setEnabled(bool(self.ctx.current_fair_id))
            self.btn_end.setEnabled(False)

    def on_fair_change(self, _):
        fid = self.fair_combo.currentData()
        if fid:
            self.ctx.set_fair(fid)
            self._update_day_status()
            self.main.notify_fair_changed()

    def start_day(self):
        if not self.ctx.current_fair_id:
            QMessageBox.warning(self, "Messe wählen",
                                "Bitte zuerst eine Messe auswählen.")
            return
        try:
            self.ctx.db.start_fair_day(self.ctx.current_fair_id)
        except ValueError as e:
            QMessageBox.warning(self, "Nicht möglich", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Fehler",
                                 f"Messetag konnte nicht gestartet werden:\n{e}")
            return
        self._update_day_status()
        self.main.notify_fair_changed()

    def end_day(self):
        if not self.ctx.current_fair_day_id:
            QMessageBox.information(self, "Kein Tag",
                                    "Es läuft aktuell kein Messetag.")
            return
        pending = self.ctx.db.list_card_queue("pending")
        msg = "Messetag beenden?"
        if pending:
            msg += f"\n\nAchtung: {len(pending)} unbearbeitete Visitenkarten."
        if QMessageBox.question(self, "Beenden", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.ctx.db.end_fair_day(self.ctx.current_fair_day_id)
        self._update_day_status()
        self.main.notify_fair_changed()