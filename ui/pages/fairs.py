from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox)


class FairsPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        t = QLabel("Messen")
        t.setObjectName("Title")
        v.addWidget(t)

        row = QHBoxLayout()
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Name der Messe")
        self.inp_loc = QLineEdit()
        self.inp_loc.setPlaceholderText("Ort (optional)")
        self.btn_add = QPushButton("Messe anlegen")
        self.btn_add.clicked.connect(self.add_fair)
        row.addWidget(self.inp_name, 2)
        row.addWidget(self.inp_loc, 1)
        row.addWidget(self.btn_add)
        v.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Ort", "Archiviert"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)

        row2 = QHBoxLayout()
        self.btn_archive = QPushButton("Ausgewählte archivieren")
        self.btn_archive.setObjectName("Ghost")
        self.btn_archive.clicked.connect(self.archive_selected)
        row2.addWidget(self.btn_archive)
        row2.addStretch(1)
        v.addLayout(row2)

    def refresh(self):
        fairs = self.ctx.db.list_fairs(include_archived=True)
        self.table.setRowCount(len(fairs))
        for r, f in enumerate(fairs):
            for c, k in enumerate(["id", "name", "location", "archived"]):
                self.table.setItem(r, c, QTableWidgetItem(str(f.get(k) or "")))

    def add_fair(self):
        name = self.inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehlt", "Name der Messe erforderlich.")
            return
        new_id = self.ctx.db.create_fair(name, self.inp_loc.text().strip())
        self.ctx.set_fair(new_id)
        self.inp_name.clear()
        self.inp_loc.clear()
        self.refresh()
        self.main.pages["home"].refresh()
        self.main.notify_fair_changed()

    def archive_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Auswahl",
                                    "Bitte zuerst eine Messe in der Tabelle auswählen.")
            return
        fid = int(self.table.item(row, 0).text())
        if QMessageBox.question(self, "Archivieren",
                                "Messe wirklich archivieren?") == QMessageBox.Yes:
            self.ctx.db.update_fair(fid, archived=1)
            self.refresh()