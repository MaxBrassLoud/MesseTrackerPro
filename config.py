# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "messe_tracker.db"
CARDS_DIR = DATA_DIR / "cards"
BACKUP_DIR = DATA_DIR / "backups"
SSL_DIR = DATA_DIR / "ssl"

for d in (DATA_DIR, CARDS_DIR, BACKUP_DIR, SSL_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_STATUSES = ["Interessiert", "Anfrage", "Auftrag erteilt"]
DEFAULT_THEME = "Flipper"

SOURCES = ["Smartphone", "Visitenkarte", "Manuell"]
PROCESSING_STATES = ["ok", "needs_review"]

WEB_HOST = "0.0.0.0"
WEB_PORT = 8765

# ---------------------------------------------------------------------------
# HTTPS / TLS
# ---------------------------------------------------------------------------
# Pfade sind immer gesetzt – ob HTTPS aktiv ist, wird zur Laufzeit anhand
# der Existenz der Dateien entschieden (siehe web.server.start_server).
SSL_CERT_FILE = Path(os.environ.get("MT_SSL_CERT", str(SSL_DIR / "cert.pem")))
SSL_KEY_FILE = Path(os.environ.get("MT_SSL_KEY", str(SSL_DIR / "key.pem")))

# Automatisches Erzeugen beim Start (abschaltbar via MT_SSL_AUTO=0)
SSL_AUTO_GENERATE = os.environ.get("MT_SSL_AUTO", "1") != "0"

# Gültigkeitsdauer in Tagen. 825 Tage = Apple-Limit für öffentliche
# Zertifikate. Für selbst-signierte im lokalen Vertrauensspeicher wäre
# auch mehr möglich, aber 825 ist plattformübergreifend unkritisch.
SSL_VALID_DAYS = int(os.environ.get("MT_SSL_VALID_DAYS", "825"))

# Sicherheit & Backups
CSRF_ENABLED = True
BACKUP_ROTATION_COUNT = 10
BACKUP_AUTO_INTERVAL_HOURS = 24
MAX_UPLOAD_MB = 20
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

DEFAULT_AUTO_LOGOUT_MINUTES = 5
AUTO_LOGOUT_MIN = 0
AUTO_LOGOUT_MAX = 240

MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_DIMENSION = 2400
IMAGE_JPEG_QUALITY = 88