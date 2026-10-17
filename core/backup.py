import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from config import DB_PATH, CARDS_DIR


def create_backup(target_zip: str):
    """Konsistentes Backup via SQLite-Backup-API + Bilder als ZIP."""
    target = Path(target_zip)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = target.with_suffix(".sqlite.tmp")
    if tmp_db.exists():
        tmp_db.unlink()
    # Konsistente SQLite-Kopie
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(tmp_db))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    meta = {"created_at": datetime.now().isoformat(timespec="seconds"),
            "schema": 1, "app": "Messe Tracker Pro"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "messe_tracker.db")
        z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        if CARDS_DIR.exists():
            for p in CARDS_DIR.rglob("*"):
                if p.is_file():
                    z.write(p, f"cards/{p.relative_to(CARDS_DIR)}")
    tmp_db.unlink(missing_ok=True)
    return target


def restore_backup(source_zip: str, confirm_overwrite: bool = False):
    if not confirm_overwrite:
        raise RuntimeError("Wiederherstellung erfordert ausdrückliche Bestätigung.")
    src = Path(source_zip)
    if not src.exists():
        raise FileNotFoundError(src)
    with zipfile.ZipFile(src, "r") as z:
        names = z.namelist()
        if "messe_tracker.db" not in names:
            raise ValueError("Backup enthält keine messe_tracker.db")
        # DB ersetzen
        tmp = DB_PATH.with_suffix(".restore.tmp")
        with z.open("messe_tracker.db") as f, open(tmp, "wb") as out:
            shutil.copyfileobj(f, out)
        # Bilder ersetzen
        if CARDS_DIR.exists():
            shutil.rmtree(CARDS_DIR)
        CARDS_DIR.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.startswith("cards/") and not n.endswith("/"):
                out = CARDS_DIR / n[len("cards/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as f, open(out, "wb") as o:
                    shutil.copyfileobj(f, o)
        tmp.replace(DB_PATH)
    return True