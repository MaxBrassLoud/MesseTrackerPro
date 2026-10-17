# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "messe_tracker.db"
CARDS_DIR = DATA_DIR / "cards"
BACKUP_DIR = DATA_DIR / "backups"

for d in (DATA_DIR, CARDS_DIR, BACKUP_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_STATUSES = ["Interessiert", "Anfrage", "Auftrag erteilt"]
DEFAULT_THEME = "Flipper"

SOURCES = ["Smartphone", "Visitenkarte", "Manuell"]
PROCESSING_STATES = ["ok", "needs_review"]

WEB_HOST = "0.0.0.0"
WEB_PORT = 8765

# NEU: Sicherheit & Backups
CSRF_ENABLED = True
BACKUP_ROTATION_COUNT = 10          # Anzahl automatischer Backups
BACKUP_AUTO_INTERVAL_HOURS = 24     # Automatisches Backup alle X Stunden
MAX_UPLOAD_MB = 20                  # Maximale Uploadgröße
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}