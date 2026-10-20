# ui/main_window.py
from datetime import datetime

from PyQt5.QtCore import QEvent, QTimer, Qt
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QLabel, QButtonGroup, QMessageBox, QApplication,
    QGraphicsBlurEffect,
)
import logging

from config import DEFAULT_AUTO_LOGOUT_MINUTES
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
from core.permissions import Perm


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

        self._pending_user = None
        self._pending_token = None
        self._profile_page = None
        self._company_page = None

        self.setWindowTitle(
            f"Messe Tracker Pro – "
            f"{user.get('display_name') or user['username']}")
        self.resize(1280, 800)
        self.apply_theme()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        sb = QVBoxLayout(self.sidebar)
        sb.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Messe\nTracker Pro")
        title.setStyleSheet(
            f"color:{self.current_theme['accent']};"
            "font-weight:800;font-size:16pt;padding:20px;")
        sb.addWidget(title)
        sb.addStretch(1)

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

        sb.addStretch(1)
        info = QLabel(
            f"👤 {user.get('display_name') or user['username']}"
            f"{'  (Admin)' if user.get('is_admin') else ''}")
        info.setStyleSheet("color:#888;padding:8px 18px;font-size:9pt;")
        info.setWordWrap(True)
        sb.addWidget(info)

        from ui.dialogs.password_change import ChangePasswordDialog
        if user.get("must_change_password"):
            b_pw = QPushButton("Passwort jetzt ändern")
            b_pw.clicked.connect(
                lambda: ChangePasswordDialog(auth, user, self).exec_())
            sb.addWidget(b_pw)

        b_logout = QPushButton("Abmelden")
        b_logout.setObjectName("Ghost")
        b_logout.clicked.connect(lambda: self._do_logout(auto=False))
        sb.addWidget(b_logout)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)

        first = next(iter(self.pages), None)
        if first:
            self.group.buttons()[0].setChecked(True)
            self.show_page(first)

        self._blur_effect = QGraphicsBlurEffect()
        self._blur_effect.setBlurRadius(0)
        self._blur_effect.setEnabled(False)
        root.setGraphicsEffect(self._blur_effect)

        self._last_activity = datetime.now()
        self._last_timeout_min = DEFAULT_AUTO_LOGOUT_MINUTES
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(5000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (
            QEvent.MouseMove, QEvent.MouseButtonPress,
            QEvent.MouseButtonDblClick, QEvent.KeyPress, QEvent.Wheel,
        ):
            self._last_activity = datetime.now()
        return super().eventFilter(obj, event)

    def _check_idle(self):
        try:
            timeout_min = int(self.ctx.db.get_setting(
                "auto_logout_minutes",
                str(DEFAULT_AUTO_LOGOUT_MINUTES)))
        except (ValueError, TypeError):
            timeout_min = DEFAULT_AUTO_LOGOUT_MINUTES
        if timeout_min <= 0:
            return
        idle_sec = (datetime.now() - self._last_activity).total_seconds()
        if idle_sec >= timeout_min * 60:
            self._last_timeout_min = timeout_min
            self._do_logout(auto=True)

    def _do_logout(self, auto=False):
        if not auto:
            if QMessageBox.question(
                    self, "Abmelden",
                    "Möchten Sie sich abmelden und zur Mitarbeiterauswahl "
                    "zurückkehren?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return

        self._idle_timer.stop()

        try:
            self.auth.logout(self.session_token)
        except Exception:
            logging.exception("Logout der Session fehlgeschlagen.")

        self._blur_effect.setEnabled(True)
        self._blur_effect.setBlurRadius(28)

        if auto:
            QMessageBox.information(
                self, "Automatische Abmeldung",
                f"Sie wurden nach {self._last_timeout_min} Minuten "
                f"Inaktivität abgemeldet.\n\n"
                f"Bitte melden Sie sich neu an, um fortzufahren.")

        from ui.login_dialog import LoginDialog
        dlg = LoginDialog(self.auth, self)
        if not dlg.exec_() or not dlg.user:
            QApplication.quit()
            return

        new_user = dlg.user
        new_token = dlg.session_token

        same_user = (
            new_user["id"] == self.user["id"]
            and bool(new_user.get("is_admin")) == bool(self.user.get("is_admin"))
        )
        if not same_user:
            self._pending_user = new_user
            self._pending_token = new_token
            QApplication.exit(42)
            return

        self.user = new_user
        self.session_token = new_token
        self.setWindowTitle(
            f"Messe Tracker Pro – "
            f"{new_user.get('display_name') or new_user['username']}")
        self._blur_effect.setBlurRadius(0)
        self._blur_effect.setEnabled(False)
        self._last_activity = datetime.now()
        self._idle_timer.start()

    # ------------------------------------------------------------------
    # Vollflächige Kundenakte
    # ------------------------------------------------------------------
    def open_contact_profile(self, contact):
        if self._profile_page is None:
            from ui.pages.contact_profile import ContactProfilePage
            self._profile_page = ContactProfilePage(
                self.ctx, self, self.pages["contacts"])
            self.stack.addWidget(self._profile_page)
        self._profile_page.set_contact(contact)
        self.sidebar.setVisible(False)
        self.stack.setCurrentWidget(self._profile_page)

    def close_contact_profile(self):
        self.sidebar.setVisible(True)
        self._profile_page.current_contact = None
        self.show_page("contacts")

    # ------------------------------------------------------------------
    # Vollflächige Firmenakte
    # ------------------------------------------------------------------
    def open_company_profile(self, company_id: int):
        if self._company_page is None:
            from ui.pages.company_profile import CompanyProfilePage
            self._company_page = CompanyProfilePage(
                self.ctx, self, self.pages["contacts"])
            self.stack.addWidget(self._company_page)
        self._company_page.set_company(company_id)
        self.sidebar.setVisible(False)
        self.stack.setCurrentWidget(self._company_page)

    def close_company_profile(self):
        self.sidebar.setVisible(True)
        self.show_page("contacts")

    # ------------------------------------------------------------------
    # Theme / Seiten
    # ------------------------------------------------------------------
    def apply_theme(self):
        theme_name = self.ctx.db.get_setting("theme", "Flipper")
        self.current_theme = get_theme(theme_name)
        self.setStyleSheet(build_qss(self.current_theme))

    def show_page(self, key):
        page = self.pages.get(key)
        if not page:
            return
        if not self.sidebar.isVisible():
            self.sidebar.setVisible(True)
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

    def closeEvent(self, event):
        try:
            self._idle_timer.stop()
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        super().closeEvent(event)