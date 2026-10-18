import os
import tempfile
import pytest

from database.db import Database
from core.auth import (
    AuthService, AuthError, hash_password, verify_password,
    MAX_FAILED_ATTEMPTS,
)
from core.permissions import Perm, PermissionDenied


@pytest.fixture
def db():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "test.db"))
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def auth(db):
    return AuthService(db)


def test_no_plaintext_password_stored(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    u = db.get_user_by_username("admin")
    assert u["password_hash"] != "SicheresPasswort123"
    assert len(u["password_hash"]) == 64
    assert len(u["password_salt"]) == 32


def test_hash_verify_roundtrip():
    h, s, it = hash_password("EinLangesPasswort!")
    assert verify_password("EinLangesPasswort!", h, s, it)
    assert not verify_password("falsch", h, s, it)


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("kurz")


def test_setup_required_until_first_user(db, auth):
    assert auth.is_setup_required()
    auth.create_initial_admin("admin", "SicheresPasswort123")
    assert not auth.is_setup_required()


def test_cannot_create_second_initial_admin(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    with pytest.raises(AuthError, match="bereits abgeschlossen"):
        auth.create_initial_admin("admin2", "AnderesPasswort456")


def test_login_ok_returns_session(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    user, token = auth.login("admin", "SicheresPasswort123")
    assert user["username"] == "admin"
    assert token
    found = auth.user_for_session(token)
    assert found["id"] == user["id"]


def test_login_wrong_password(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    with pytest.raises(AuthError):
        auth.login("admin", "falsch")


def test_login_unknown_user_same_error(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    with pytest.raises(AuthError):
        auth.login("unbekannt", "egal")


def test_lockout_after_max_failures(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError):
            auth.login("admin", "falsch")
    with pytest.raises(AuthError, match="Fehlversuche"):
        auth.login("admin", "SicheresPasswort123")


def test_deactivated_user_cannot_login(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    user, _ = auth.login("admin", "SicheresPasswort123")
    auth.set_active(user["id"], False)
    with pytest.raises(AuthError):
        auth.login("admin", "SicheresPasswort123")


def test_logout_revokes_session(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    _, tok = auth.login("admin", "SicheresPasswort123")
    assert auth.user_for_session(tok)
    auth.logout(tok)
    assert auth.user_for_session(tok) is None


def test_admin_has_all_permissions(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    u, _ = auth.login("admin", "SicheresPasswort123")
    perms = auth.permissions_for(u)
    for p in (Perm.MANAGE_USERS, Perm.BACKUP_RESTORE, Perm.EXPORT_DATA):
        assert p in perms


def test_regular_user_has_limited_permissions(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    uid = auth.create_user("bob", "BenutzerPasswort9", is_admin=False)
    u = db.get_user(uid)
    perms = auth.permissions_for(u)
    assert Perm.VIEW_DATA in perms
    assert Perm.MANAGE_USERS not in perms


def test_require_raises_for_missing_permission(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    uid = auth.create_user("bob", "BenutzerPasswort9", is_admin=False)
    u = db.get_user(uid)
    with pytest.raises(PermissionDenied):
        auth.require(u, Perm.MANAGE_USERS)


def test_deactivating_last_admin_blocked(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    u = db.get_user_by_username("admin")
    with pytest.raises(AuthError, match="letzte aktive Administrator"):
        auth.set_active(u["id"], False)


def test_demoting_last_admin_blocked(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    u = db.get_user_by_username("admin")
    with pytest.raises(AuthError):
        auth.set_admin(u["id"], False)


def test_password_change_revokes_sessions(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    _, tok = auth.login("admin", "SicheresPasswort123")
    assert auth.user_for_session(tok)
    u = db.get_user_by_username("admin")
    assert auth.change_own_password(u["id"], "SicheresPasswort123",
                                    "NeuesSicheresPasswort9")
    assert auth.user_for_session(tok) is None


def test_audit_log_written(db, auth):
    auth.create_initial_admin("admin", "SicheresPasswort123")
    rows = db.conn.execute(
        "SELECT action FROM audit_log WHERE action LIKE 'user.%'").fetchall()
    assert any(r["action"] == "user.create" for r in rows)