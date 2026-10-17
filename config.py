import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "messe_tracker.db"
CARDS_DIR = DATA_DIR / "cards"
BACKUP_DIR = DATA_DIR / "backups"

for d in (DATA_DIR, CARDS_DIR, BACKUP_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Nur noch als Seed für die Erstinstallation / Migration
DEFAULT_STATUSES = ["Interessiert", "Anfrage", "Auftrag erteilt"]
DEFAULT_THEME = "Flipper"

SOURCES = ["Smartphone", "Visitenkarte", "Manuell"]
PROCESSING_STATES = ["ok", "needs_review"]

WEB_HOST = "0.0.0.0"
WEB_PORT = 8765