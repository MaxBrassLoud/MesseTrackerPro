from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox,
                             QInputDialog, QSpinBox, QDialog, QDialogButtonBox, QFormLayout)


class CountDialog(QDialog):
    def __init__(self, parent, item_name):
        super().__init__(parent); self.setWindowTitle(f"Zählung: {item_name}")
        form = QFormLayout(self)
        self.spin = QSpinBox(); self.spin.setRange(0, 10_000_000)
        self.note = QLineEdit()
        form.addRow("Gezählter Bestand", self.spin)
        form.addRow("Notiz", self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)


class MerchPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx; self.main = main
        v = QVBoxLayout(self)
        t = QLabel("Merch-Verwaltung"); t.setObjectName("Title"); v.addWidget(t)
        row = QHBoxLayout()
        self.inp_name = QLineEdit(); self.inp_name.setPlaceholderText("Artikelname")
        self.inp_cat = QLineEdit(); self.inp_cat.setPlaceholderText("Kategorie")
        b = QPushButton("Artikel anlegen"); b.clicked.connect(self.add_item)
        row.addWidget(self.inp_name, 1); row.addWidget(self.inp_cat, 1); row.addWidget(b)
        v.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Kategorie",
                                              "Aktueller Bestand", "Kumulativ ausgegeben"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)

        row2 = QHBoxLayout()
        c = QPushButton("Zählung erfassen"); c.clicked.connect(self.count)
        h = QPushButton("Historie"); h.setObjectName("Ghost"); h.clicked.connect(self.history)
        row2.addWidget(c); row2.addWidget(h); row2.addStretch(1)
        v.addLayout(row2)
        self.hist_label = QLabel(); self.hist_label.setStyleSheet("font-family: monospace;")
        v.addWidget(self.hist_label)

    def refresh(self):
        if not self.ctx.current_fair_id:
            self.table.setRowCount(0); return
        items = self.ctx.db.merch_summary(self.ctx.current_fair_id)
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            for c, k in enumerate(["id", "name", "category"]):
                self.table.setItem(r, c, QTableWidgetItem(str(it.get(k) or "")))
            self.table.setItem(r, 3, QTableWidgetItem(str(it["current_stock"])))
            self.table.setItem(r, 4, QTableWidgetItem(str(it["cumulative_issued"])))

    def add_item(self):
        if not self.ctx.current_fair_id:
            QMessageBox.warning(self, "Messe", "Bitte zuerst eine Messe auswählen."); return
        name = self.inp_name.text().strip()
        if not name: return
        self.ctx.db.create_merch_item(self.ctx.current_fair_id, name,
                                      self.inp_cat.text().strip())
        self.inp_name.clear(); self.inp_cat.clear(); self.refresh()

    def count(self):
        row = self.table.currentRow()
        if row < 0: return
        item_id = int(self.table.item(row, 0).text())
        name = self.table.item(row, 1).text()
        d = CountDialog(self, name)
        if d.exec_():
            self.ctx.db.add_merch_count(
                item_id, self.ctx.current_fair_id, d.spin.value(),
                fair_day_id=self.ctx.current_fair_day_id, note=d.note.text().strip())
            self.refresh()

    def history(self):
        row = self.table.currentRow()
        if row < 0: return
        item_id = int(self.table.item(row, 0).text())
        hist = self.ctx.db.merch_history(item_id)
        lines = []
        for h in hist:
            lines.append(f"#{h['id']} {h['timestamp']}: Bestand {h['counted_stock']} "
                         f"(vorher {h['previous_stock']}, Ausgabe {h['issued_since_previous']}) "
                         f"{h['note'] or ''}")
        self.hist_label.setText("\n".join(lines) if lines else "Keine Zählungen.")