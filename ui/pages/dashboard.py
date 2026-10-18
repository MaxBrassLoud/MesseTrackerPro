from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QGroupBox,
                             QGridLayout, QHBoxLayout)
from PyQt5.QtCore import QTimer


def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


class DashboardPage(QWidget):
    def __init__(self, ctx, main):
        super().__init__()
        self.ctx = ctx
        self.main = main
        v = QVBoxLayout(self)
        self.title = QLabel("Dashboard")
        self.title.setObjectName("Title")
        v.addWidget(self.title)
        self.sub = QLabel("-")
        self.sub.setObjectName("Sub")
        v.addWidget(self.sub)

        grid = QGridLayout()
        self.labels = {}

        def stat(name, title):
            g = QGroupBox(title)
            gl = QVBoxLayout(g)
            l = QLabel("0")
            l.setObjectName("Stat")
            gl.addWidget(l)
            self.labels[name] = l
            return g

        grid.addWidget(stat("today", "Kontakte heute"), 0, 0)
        grid.addWidget(stat("total", "Kontakte gesamt"), 0, 1)
        grid.addWidget(stat("companies", "Unternehmen"), 0, 2)
        grid.addWidget(stat("cards", "Offene Visitenkarten"), 1, 0)
        grid.addWidget(stat("present", "Anwesend"), 1, 1)
        grid.addWidget(stat("absent", "Abwesend"), 1, 2)
        grid.addWidget(stat("tasks", "Offene Nachfassaktionen"), 2, 0)
        grid.addWidget(stat("overdue", "Überfällige Aufgaben"), 2, 1)
        v.addLayout(grid)

        self.att_box = QGroupBox("Anwesenheit am Stand")
        av = QVBoxLayout(self.att_box)
        self.present_label = QLabel("—")
        self.present_label.setWordWrap(True)
        self.absent_label = QLabel("—")
        self.absent_label.setWordWrap(True)
        self.unknown_label = QLabel("—")
        self.unknown_label.setWordWrap(True)

        for prefix, widget in [("🟢 Anwesend: ", self.present_label),
                               ("⚪ Abwesend: ", self.absent_label),
                               ("❔ Ohne Status: ", self.unknown_label)]:
            row = QHBoxLayout()
            lbl = QLabel(prefix)
            lbl.setStyleSheet("color:#FF8200;font-weight:600;")
            row.addWidget(lbl, 0)
            row.addWidget(widget, 1)
            av.addLayout(row)
        v.addWidget(self.att_box)

        self.status_box = QGroupBox("Kundenstatus")
        sl = QVBoxLayout(self.status_box)
        self.status_label = QLabel("-")
        self.status_label.setWordWrap(True)
        sl.addWidget(self.status_label)
        v.addWidget(self.status_box)

        self.merch_box = QGroupBox("Merch")
        ml = QVBoxLayout(self.merch_box)
        self.merch_label = QLabel("-")
        self.merch_label.setWordWrap(True)
        ml.addWidget(self.merch_label)
        v.addWidget(self.merch_box)
        v.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def refresh(self):
        if not self.ctx.current_fair_id:
            self.sub.setText("Keine Messe ausgewählt.")
            self.present_label.setText("—")
            self.absent_label.setText("—")
            self.unknown_label.setText("—")
            self.status_label.setText("-")
            self.merch_label.setText("-")
            return

        ad = self.ctx.db.get_active_fair_day()
        day_id = (ad["id"]
                  if ad and ad["fair_id"] == self.ctx.current_fair_id
                  else None)
        s = self.ctx.db.dashboard_stats(self.ctx.current_fair_id, day_id)
        self.sub.setText(
            f"Messe-ID {self.ctx.current_fair_id} · "
            + (f"Tag {day_id}" if day_id else "kein aktiver Tag"))

        self.labels["today"].setText(str(s["total_today"]))
        self.labels["total"].setText(str(s["total_fair"]))
        self.labels["companies"].setText(str(s["companies"]))
        self.labels["cards"].setText(str(s["pending_cards"]))
        self.labels["present"].setText(str(len(s["present"])))
        self.labels["absent"].setText(str(len(s["absent"])))
        self.labels["tasks"].setText(str(s["tasks_open"]))
        self.labels["overdue"].setText(str(s["tasks_overdue"]))
        self.status_label.setText(
            " · ".join(f"{k}: {v}" for k, v in s["by_status"].items()))

        emps = {e["id"]: e["name"] for e in self.ctx.db.list_employees()}
        active_ids = {e["id"]
                      for e in self.ctx.db.list_employees(active_only=True)}
        att = self.ctx.db.current_attendance(self.ctx.current_fair_id)

        present_ids = [eid for eid, v in att.items()
                       if v["event_type"] == "enter"]
        absent_ids = [eid for eid, v in att.items()
                      if v["event_type"] == "leave"]
        tracked = set(present_ids) | set(absent_ids)
        unknown_ids = sorted(active_ids - tracked)

        def names_with_time(ids):
            items = []
            for eid in ids:
                t = att.get(eid, {}).get("timestamp", "")
                items.append(f"{emps.get(eid, f'ID {eid}')} ({_fmt_dt(t)})")
            return ", ".join(items) or "—"

        def names(ids):
            return ", ".join(emps.get(i, f"ID {i}") for i in ids) or "—"

        self.present_label.setText(names_with_time(present_ids))
        self.absent_label.setText(names_with_time(absent_ids))
        self.unknown_label.setText(names(unknown_ids))

        if s["merch"]:
            self.merch_label.setText("\n".join(
                f"{m['name']}: {m['current_stock']} aktuell, "
                f"{m['cumulative_issued']} kumulativ ausgegeben"
                for m in s["merch"]))
        else:
            self.merch_label.setText("Keine Artikel.")
