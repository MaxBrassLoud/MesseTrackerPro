from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QStackedWidget, QLabel, QButtonGroup,
                             QMessageBox, QApplication)
import logging

from ui.themes import get_theme, build_qss
from ui.pages.home import HomePage
from ui.pages.fairs import FairsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.contacts import ContactsPage
from ui.pages.queue import QueuePage
from ui.pages.merch import MerchPage
from ui.pages.reports import ReportsPage
from ui.pages.settings import SettingsPage
from ui.pages.users import UsersPage
from core.permissions import Perm, PermissionDenied


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
    def __init__(self, db, auth, user, session_token=None):
        super().__init__()
        self.ctx = AppContext(db)
        self.auth = auth
        self.user = user
        self.session_token = session_token
        self.setWindowTitle(
            f"Messe Tracker Pro – "
            f"{user.get('display_name') or user['username']}")
        self.resize(1280, 800)
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
        self.pages = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        page_specs = [
            ("home",      "Start",               None,
             lambda: HomePage(self.ctx, self)),
            ("fairs",     "Messen",              Perm.EDIT_DATA,
             lambda: FairsPage(self.ctx, self)),
            ("dashboard", "Dashboard",           Perm.VIEW_DATA,
             lambda: DashboardPage(self.ctx, self)),
            ("contacts",  "Kundenkartei",        Perm.VIEW_DATA,
             lambda: ContactsPage(self.ctx, self)),
            ("queue",     "Visitenkarten",       Perm.CREATE_DATA,
             lambda: QueuePage(self.ctx, self)),
            ("merch",     "Merch",               Perm.MANAGE_MERCH,
             lambda: MerchPage(self.ctx, self)),
            ("reports",   "Auswertung & Export", Perm.VIEW_DATA,
             lambda: ReportsPage(self.ctx, self)),
            ("users",     "Benutzer",            Perm.MANAGE_USERS,
             lambda: UsersPage(self.ctx, self, auth, user)),
            ("settings",  "Einstellungen",       Perm.EDIT_SETTINGS,
             lambda: SettingsPage(self.ctx, self)),
        ]

        for key, label, perm, factory in page_specs:
            if perm is not None and not auth.has(user, perm):
                continue
            try:
                page = factory()
            except Exception as e:
                logging.exception("Seite %s konnte nicht geladen werden", key)
                page = QWidget()
                err_lbl = QLabel(f"Seite „{label}“ nicht verfügbar:\n{e}")
                err_lbl.setStyleSheet("color:#ff6b6b;padding:20px;")
                err_lbl.setWordWrap(True)
                pv = QVBoxLayout(page)
                pv.addWidget(err_lbl)
            self.pages[key] = page
            self.stack.addWidget(page)
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.show_page(k))
            self.group.addButton(b)
            sb.addWidget(b)

        # ---- Benutzerinfo + Logout ----
        sb.addStretch(1)
        info = QLabel(
            f"👤 {user.get('display_name') or user['username']}"
            f"{'  (Admin)' if user.get('is_admin') else ''}")
        info.setStyleSheet("color:#888;padding:8px 18px;font-size:9pt;")
        info.setWordWrap(True)
        sb.addWidget(info)

        # Passwort ändern, wenn must_change oder freiwillig
        from ui.dialogs.password_change import ChangePasswordDialog
        if user.get("must_change_password"):
            b_pw = QPushButton("Passwort jetzt ändern")
            b_pw.clicked.connect(
                lambda: ChangePasswordDialog(auth, user, self).exec_())
            sb.addWidget(b_pw)

        b_logout = QPushButton("Abmelden")
        b_logout.setObjectName("Ghost")
        b_logout.clicked.connect(self._logout)
        sb.addWidget(b_logout)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)

        # Erste Seite auswählen
        first = next(iter(self.pages), None)
        if first:
            self.group.buttons()[0].setChecked(True)
            self.show_page(first)

    def apply_theme(self):
        theme_name = self.ctx.db.get_setting("theme", "Flipper")
        self.current_theme = get_theme(theme_name)
        self.setStyleSheet(build_qss(self.current_theme))

    def show_page(self, key):
        page = self.pages.get(key)
        if not page:
            return
        self.stack.setCurrentWidget(page)
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

    def _logout(self):
        if QMessageBox.question(
                self, "Abmelden",
                "Möchten Sie sich abmelden und zur Mitarbeiterauswahl zurückkehren?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.auth.logout(self.session_token)
        finally:
            QApplication.exit(42)  # wird in main() als Benutzerwechsel behandelt
