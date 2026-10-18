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

# Sicherheit & Backups
CSRF_ENABLED = True
BACKUP_ROTATION_COUNT = 10          # Anzahl automatischer Backups
BACKUP_AUTO_INTERVAL_HOURS = 24     # Automatisches Backup alle X Stunden
MAX_UPLOAD_MB = 20                  # Maximale Uploadgröße
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# NEU: Automatische Abmeldung nach Inaktivität
DEFAULT_AUTO_LOGOUT_MINUTES = 5     # 0 = deaktiviert
AUTO_LOGOUT_MIN = 0                 # Untergrenze (0 = aus)
AUTO_LOGOUT_MAX = 240               # Obergrenze (4 Stunden)

# Bildverarbeitung (Schutz vor Decompression-Bombs & Monster-Uploads)
MAX_IMAGE_PIXELS = 50_000_000       # ~50 Megapixel
MAX_IMAGE_DIMENSION = 2400          # Längste Kante nach Re-Encoding
IMAGE_JPEG_QUALITY = 88             # JPEG-Qualität für Re-Encoding