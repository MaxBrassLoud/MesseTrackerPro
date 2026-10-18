"""Zentrale Berechtigungs-Konstanten und Rollen-Definitionen.

Rechte werden als Strings gespeichert und sind damit schema-tolerant.
Neue Rechte können ohne Migration hinzugefügt werden.
"""


class Perm:
    VIEW_DATA       = "data.view"
    CREATE_DATA     = "data.create"
    EDIT_DATA       = "data.edit"
    DELETE_DATA     = "data.delete"
    EXPORT_DATA     = "data.export"
    GENERATE_REPORT = "report.generate"
    MANAGE_TASKS    = "tasks.manage"
    MANAGE_MERCH    = "merch.manage"
    MANAGE_USERS    = "admin.users"
    MANAGE_ROLES    = "admin.roles"
    BACKUP_RESTORE  = "admin.backup"
    EDIT_SETTINGS   = "admin.settings"


ALL_PERMISSIONS = [
    (Perm.VIEW_DATA,       "Daten anzeigen"),
    (Perm.CREATE_DATA,     "Datensätze erstellen"),
    (Perm.EDIT_DATA,       "Datensätze bearbeiten"),
    (Perm.DELETE_DATA,     "Datensätze löschen"),
    (Perm.EXPORT_DATA,     "Kunden exportieren"),
    (Perm.GENERATE_REPORT, "Messeberichte erzeugen"),
    (Perm.MANAGE_TASKS,    "Aufgaben verwalten"),
    (Perm.MANAGE_MERCH,    "Merchandise verwalten"),
    (Perm.MANAGE_USERS,    "Benutzer verwalten"),
    (Perm.MANAGE_ROLES,    "Rollen verwalten"),
    (Perm.BACKUP_RESTORE,  "Backup und Wiederherstellung"),
    (Perm.EDIT_SETTINGS,   "Einstellungen ändern"),
]

PERMISSION_LABELS = dict(ALL_PERMISSIONS)

# System-Rollen — feste IDs, damit Restore und Migration konsistent bleiben
SYSTEM_ROLE_ADMIN_ID = 1
SYSTEM_ROLE_USER_ID  = 2

# Standardrechte für neue Nicht-Admin-Benutzer
DEFAULT_USER_PERMISSIONS = {
    Perm.VIEW_DATA,
    Perm.CREATE_DATA,
    Perm.EDIT_DATA,
    Perm.MANAGE_TASKS,
}


class PermissionDenied(Exception):
    """Wird geworfen, wenn ein Benutzer eine Aktion nicht ausführen darf."""