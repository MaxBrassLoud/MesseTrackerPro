from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QStackedWidget, QLabel, QButtonGroup,
                             QMessageBox)

from ui.themes import get_theme, build_qss
from ui.pages.home import HomePage
from ui.pages.fairs import FairsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.contacts import ContactsPage
from ui.pages.queue import QueuePage
from ui.pages.employees import EmployeesPage
from ui.pages.merch import MerchPage
from ui.pages.reports import ReportsPage
from ui.pages.settings import SettingsPage


class AppContext:
    def __init__(self, db):
        self.db = db
        self.current_fair_id = None
        self.current_fair_day_id = None

    def set_fair(self, fair_id):
        self.current_fair_id = fair_id
        ad = self.db.get_active_fair_day()
        self.current_fair_day_id = (
            ad["id"] if ad and ad["fair_id"] == fair_id else None)

    def statuses(self, active_only=True):
        return [s["name"]
                for s in self.db.list_statuses(active_only=active_only)]


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.setWindowTitle("Messe Tracker Pro")
        self.resize(1280, 800)
        self.ctx = AppContext(db)

        self.apply_theme()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- Sidebar ----
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Messe\nTracker Pro")
        title.setStyleSheet(
            f"color:{self.current_theme['accent']};"
            "font-weight:800;font-size:16pt;padding:20px;")
        sb.addWidget(title)
        sb.addStretch(1)

        # ---- Seiten ----
        self.stack = QStackedWidget()
        self.pages = {
            "home": HomePage(self.ctx, self),
            "fairs": FairsPage(self.ctx, self),
            "dashboard": DashboardPage(self.ctx, self),
            "contacts": ContactsPage(self.ctx, self),
            "queue": QueuePage(self.ctx, self),
            "employees": EmployeesPage(self.ctx, self),
            "merch": MerchPage(self.ctx, self),
            "reports": ReportsPage(self.ctx, self),
            "settings": SettingsPage(self.ctx, self),
        }
        labels = [
            ("home", "Start"),
            ("fairs", "Messen"),
            ("dashboard", "Dashboard"),
            ("contacts", "Kundenkartei"),
            ("queue", "Visitenkarten"),
            ("employees", "Mitarbeiter"),
            ("merch", "Merch"),
            ("reports", "Auswertung & Export"),
            ("settings", "Einstellungen"),
        ]
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, label in labels:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.show_page(k))
            self.group.addButton(b)
            sb.addWidget(b)
            self.stack.addWidget(self.pages[key])
        sb.addStretch(1)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)

        self.group.buttons()[0].setChecked(True)
        self.show_page("home")

    def apply_theme(self):
        theme_name = self.ctx.db.get_setting("theme", "Flipper")
        self.current_theme = get_theme(theme_name)
        self.setStyleSheet(build_qss(self.current_theme))

    def show_page(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        page = self.pages[key]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as e:
                QMessageBox.warning(
                    self, "Fehler",
                    f"Seite konnte nicht geladen werden:\n{e}")

    def notify_fair_changed(self):
        for p in self.pages.values():
            if hasattr(p, "on_context_changed"):
                p.on_context_changed()