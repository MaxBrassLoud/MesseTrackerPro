"""Authentifizierung und Autorisierung.

Passwort-Hashing: PBKDF2-HMAC-SHA256 (Standardbibliothek, OWASP-konform).
Sessions: token-basiert, DB-gestützt, serverseitig widerrufbar.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional

from core.permissions import (
    ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS, Perm, PermissionDenied,
    SYSTEM_ROLE_ADMIN_ID, SYSTEM_ROLE_USER_ID,
)

logger = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 260_000
_PBKDF2_ALGO = "sha256"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
SESSION_HOURS = 8
MIN_PASSWORD_LEN = 10
_USERNAME_RE = re.compile(r"[A-Za-z0-9_.\-]{3,64}")


def _validate_password(password: str):
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise ValueError(
            f"Passwort muss mindestens {MIN_PASSWORD_LEN} Zeichen lang sein.")
    if password.strip() != password:
        raise ValueError("Passwort darf nicht mit Leerzeichen beginnen/enden.")


def hash_password(password: str, salt_hex: str | None = None,
                  iterations: int = _PBKDF2_ITERATIONS) -> tuple[str, str, int]:
    if salt_hex is None:
        _validate_password(password)
        salt_hex = secrets.token_hex(16)
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGO, password.encode("utf-8"), salt, iterations)
    return digest.hex(), salt_hex, iterations


def verify_password(password: str, password_hash: str, salt_hex: str,
                    iterations: int) -> bool:
    if not password or not password_hash or not salt_hex:
        return False
    try:
        digest = hashlib.pbkdf2_hmac(
            _PBKDF2_ALGO, password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), password_hash)


class AuthError(Exception):
    pass


class AuthService:
    def __init__(self, db):
        self.db = db
        self._lock = threading.RLock()

    # ---------------- Erst-Einrichtung ----------------

    def is_setup_required(self) -> bool:
        return not self.db.has_any_user()

    def create_initial_admin(self, username: str, password: str,
                             display_name: str = "") -> int:
        if not self.is_setup_required():
            raise AuthError("Ersteinrichtung wurde bereits abgeschlossen.")
        return self.create_user(
            username=username, password=password,
            display_name=display_name or username,
            is_admin=True, must_change_password=False,
            actor_user_id=None)

    # ---------------- Benutzerverwaltung ----------------

    def create_user(self, username: str, password: str,
                    display_name: str = "", email: str = "",
                    is_admin: bool = False,
                    must_change_password: bool = True,
                    actor_user_id: Optional[int] = None) -> int:
        username = (username or "").strip()
        if not _USERNAME_RE.fullmatch(username):
            raise AuthError(
                "Benutzername: 3–64 Zeichen, nur Buchstaben, Ziffern, "
                "Punkt, Unterstrich, Bindestrich.")
        if self.db.get_user_by_username(username):
            raise AuthError(f"Benutzername „{username}“ ist bereits vergeben.")

        pw_hash, salt, iters = hash_password(password)
        uid = self.db.create_user(
            username=username, display_name=display_name or username,
            email=email, password_hash=pw_hash, password_salt=salt,
            password_iter=iters, must_change_password=must_change_password,
            is_admin=is_admin)
        self.db.ensure_employee_for_user(uid, display_name or username, email)
        role_id = (SYSTEM_ROLE_ADMIN_ID if is_admin else SYSTEM_ROLE_USER_ID)
        self.db.set_user_role(uid, role_id)
        if actor_user_id is not None:
            self.db.audit(actor_user_id, "user.create",
                          target_type="user", target_id=uid,
                          details=f"username={username}, admin={is_admin}")
        return uid

    def set_password(self, user_id: int, new_password: str,
                     must_change: bool, actor_user_id: Optional[int] = None):
        pw_hash, salt, iters = hash_password(new_password)
        self.db.update_user_password(user_id, pw_hash, salt, iters,
                                     must_change_password=must_change)
        self.db.revoke_user_sessions(user_id)
        if actor_user_id is not None:
            self.db.audit(actor_user_id, "user.password_reset",
                          target_type="user", target_id=user_id)

    def change_own_password(self, user_id: int, old_password: str,
                            new_password: str) -> bool:
        u = self.db.get_user(user_id)
        if not u:
            raise AuthError("Benutzer nicht gefunden.")
        if not verify_password(old_password, u["password_hash"],
                               u["password_salt"], u["password_iter"]):
            return False
        if old_password == new_password:
            raise AuthError("Neues Passwort muss sich vom alten unterscheiden.")
        self.set_password(user_id, new_password, must_change=False,
                          actor_user_id=user_id)
        return True

    def set_active(self, user_id: int, active: bool,
                   actor_user_id: Optional[int] = None):
        if not active and self.db.count_active_admins(
                exclude_user_id=user_id) == 0:
            raise AuthError(
                "Der letzte aktive Administrator darf nicht deaktiviert werden.")
        self.db.set_user_active(user_id, active)
        if not active:
            self.db.revoke_user_sessions(user_id)
        if actor_user_id is not None:
            self.db.audit(actor_user_id,
                          "user.activate" if active else "user.deactivate",
                          target_type="user", target_id=user_id)

    def set_admin(self, user_id: int, is_admin: bool,
                  actor_user_id: Optional[int] = None):
        if not is_admin and self.db.count_active_admins(
                exclude_user_id=user_id) == 0:
            raise AuthError(
                "Der letzte aktive Administrator darf die Admin-Rolle "
                "nicht verlieren.")
        self.db.set_user_admin(user_id, is_admin)
        role_id = (SYSTEM_ROLE_ADMIN_ID if is_admin else SYSTEM_ROLE_USER_ID)
        self.db.set_user_role(user_id, role_id)
        if actor_user_id is not None:
            self.db.audit(actor_user_id,
                          "user.grant_admin" if is_admin else "user.revoke_admin",
                          target_type="user", target_id=user_id)

    def set_roles(self, user_id: int, role_ids, actor_user_id: Optional[int] = None):
        """Setzt Rollen; ein Administrator behält aus Sicherheitsgründen Vollzugriff."""
        user = self.db.get_user(user_id)
        if not user:
            raise AuthError("Benutzer nicht gefunden.")
        if user.get("is_admin"):
            role_ids = set(role_ids) | {SYSTEM_ROLE_ADMIN_ID}
        self.db.set_user_roles(user_id, role_ids)
        if actor_user_id is not None:
            self.db.audit(actor_user_id, "user.roles_changed", "user", user_id,
                          ",".join(map(str, sorted(role_ids))))

    def create_role(self, name, description, permissions, actor_user_id=None):
        name = (name or "").strip()
        if not name:
            raise AuthError("Rollenname erforderlich.")
        allowed = {p for p, _ in ALL_PERMISSIONS}
        permissions = set(permissions)
        if not permissions <= allowed:
            raise AuthError("Unbekannte Berechtigung.")
        role_id = self.db.create_role(name, description, permissions)
        if actor_user_id is not None:
            self.db.audit(actor_user_id, "role.create", "role", role_id, name)
        return role_id

    # ---------------- Login ----------------

    def login(self, username: str, password: str,
              ip: str = "", user_agent: str = "") -> tuple[dict, str]:
        username = (username or "").strip()
        if not username or not password:
            raise AuthError("Benutzername und Passwort erforderlich.")

        with self._lock:
            u = self.db.get_user_by_username(username)
            now = datetime.now()

            if u and u.get("locked_until"):
                try:
                    until = datetime.fromisoformat(u["locked_until"])
                except ValueError:
                    until = None
                if until and until > now:
                    self.db.log_login_attempt(username, ip, False)
                    raise AuthError(
                        "Zu viele Fehlversuche. Bitte später erneut versuchen.")

            if not u or not u.get("is_active"):
                self.db.log_login_attempt(username, ip, False)
                raise AuthError("Benutzername oder Passwort ist falsch.")

            ok = verify_password(password, u["password_hash"],
                                 u["password_salt"], u["password_iter"])
            if not ok:
                self.db.increment_failed_login(u["id"])
                fails = self.db.get_failed_login_count(u["id"])
                self.db.log_login_attempt(username, ip, False)
                if fails >= MAX_FAILED_ATTEMPTS:
                    until = (now + timedelta(minutes=LOCKOUT_MINUTES)
                             ).isoformat(timespec="seconds")
                    self.db.set_user_lockout(u["id"], until)
                    logger.warning("Account locked: username=%s", username)
                raise AuthError("Benutzername oder Passwort ist falsch.")

            self.db.reset_failed_login(u["id"])
            self.db.set_user_last_login(u["id"])
            self.db.log_login_attempt(username, ip, True)

            token = secrets.token_urlsafe(32)
            expires = (now + timedelta(hours=SESSION_HOURS)
                       ).isoformat(timespec="seconds")
            self.db.create_session(u["id"], token, expires, ip, user_agent)
            self.db.audit(u["id"], "auth.login", target_type="user",
                          target_id=u["id"])

            return self.db.get_user(u["id"]), token

    def logout(self, token: str):
        if token:
            self.db.revoke_session(token)

    def user_for_session(self, token: str) -> Optional[dict]:
        if not token:
            return None
        s = self.db.get_session(token)
        if not s:
            return None
        try:
            if datetime.fromisoformat(s["expires_at"]) < datetime.now():
                self.db.revoke_session(token)
                return None
        except (ValueError, TypeError):
            self.db.revoke_session(token)
            return None
        u = self.db.get_user(s["user_id"])
        if not u or not u.get("is_active"):
            self.db.revoke_session(token)
            return None
        return u

    # ---------------- Berechtigungen ----------------

    def permissions_for(self, user: Optional[dict]) -> set[str]:
        if not user:
            return set()
        if user.get("is_admin"):
            return {p for p, _ in ALL_PERMISSIONS}
        return self.db.get_user_permissions(user["id"])

    def has(self, user: Optional[dict], permission: str) -> bool:
        return permission in self.permissions_for(user)

    def require(self, user: Optional[dict], permission: str):
        if not self.has(user, permission):
            raise PermissionDenied(f"Fehlende Berechtigung: {permission}")
