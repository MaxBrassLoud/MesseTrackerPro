"""OCR-Dienst. pytesseract + Bildvorverarbeitung für beste Erkennung."""
from __future__ import annotations

import logging
import re
from pathlib import Path

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    _TESS = True
except ImportError:
    pytesseract = None
    Image = None
    _TESS = False

# Windows: Tesseract-Pfad explizit setzen
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
if _TESS:
    for _candidate in _TESSERACT_CANDIDATES:
        if Path(_candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = _candidate
            break


# Domains, die nicht als Firma missverstanden werden sollen
_GENERIC_DOMAINS = {
    "gmail", "googlemail", "web", "gmx", "t-online", "outlook",
    "hotmail", "yahoo", "live", "icloud", "me", "aol", "mail",
}


def _empty_result(error: str = "") -> dict:
    return {
        "name": "", "company": "", "position": "", "phone": "", "email": "",
        "needs_review": True, "confidence": 0.0, "raw_text": "", "error": error,
    }


def _preprocess_image(image):
    """Graustufen → Blur gegen Moiré → Autokontrast → Upscale → Schärfen.
    Der Blur-Schritt ist entscheidend für Fotos von Bildschirmen."""
    try:
        img = image.convert("L")
        # 1. Leichter Blur entfernt Moiré und Sensorrauschen
        img = img.filter(ImageFilter.GaussianBlur(radius=1))
        # 2. Autokontrast dehnt den nutzbaren Bereich
        img = ImageOps.autocontrast(img, cutoff=2)
        # 3. Hochskalieren, falls zu klein (Tesseract mag ~1000 px Breite)
        if img.width < 1000:
            ratio = 1000 / img.width
            img = img.resize((1000, int(img.height * ratio)),
                             Image.Resampling.LANCZOS)
        # 4. Sanftes Schärfen (Unsharp Mask, kein aggressives SHARPEN)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150,
                                                 threshold=3))
        # 5. Kontrast leicht anheben
        img = ImageEnhance.Contrast(img).enhance(1.4)
        return img
    except Exception:
        return image.convert("L")


def _run_tesseract(img) -> str:
    """Probiert mehrere PSM-Modi, bis Text gefunden wird."""
    for psm in (6, 11, 4):
        try:
            text = pytesseract.image_to_string(
                img, lang="deu+eng", config=f"--oem 3 --psm {psm}")
            if text and len(text.strip()) >= 3:
                return text
        except Exception:
            continue
    # Fallback: nur Englisch, falls deu-Sprachpaket fehlt
    try:
        return pytesseract.image_to_string(
            img, lang="eng", config="--oem 3 --psm 6")
    except Exception:
        return ""


def _parse_text(text: str) -> dict:
    raw_lines = [line.strip() for line in text.splitlines()]
    lines = [re.sub(r"^[^\w]+|[^\w]+$", "", line).strip() for line in raw_lines]
    lines = [line for line in lines if line]

    data = {"name": "", "company": "", "position": "", "email": "", "phone": ""}

    # 1. E-Mail
    m = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if m:
        data["email"] = m.group(0).lower().replace(",", ".")

    # 2. Telefon (DE bevorzugt, sonst international)
    m = re.search(r"(?:\+?49|0)[\d\s\-/()]{7,}", text)
    if not m:
        m = re.search(r"\+?\d[\d\s\-/()]{7,}\d", text)
    if m:
        clean = re.sub(r"[^\d+]", "", m.group(0).strip())
        if len(clean) >= 7:
            data["phone"] = clean

    def is_contact_info(line: str) -> bool:
        return bool(re.search(
            r"[@\d]|www\.|\.de\b|\.com\b|\.org\b|\.net\b|http", line, re.I))

    text_lines = [l for l in lines if not is_contact_info(l)]

    # 3. Name (2–4 reine Buchstaben-Wörter, Groß-/Kleinschreibung egal)
    titles = r"\b(Dr\.?|Prof\.?|Dipl\.?|Ing\.?|MSc|BSc|MBA)\b"
    bad_words = (r"\b(Senior|Junior|Lead|Head|Chief|Manager|Designer|"
                 r"Developer|Sales|Vertrieb)\b")
    for line in text_lines:
        clean = re.sub(titles, "", line).strip()
        words = clean.split()
        if 2 <= len(words) <= 4 and \
                all(re.fullmatch(r"[A-Za-zÄÖÜäöüß\-\.]+", w) for w in words) and \
                not re.search(bad_words, clean, re.I):
            data["name"] = line
            break

    # 4. Position
    pos_kw = (r"\b(Geschäftsführer|Manager|Direktor|Leiter|CEO|CTO|CFO|"
              r"Vertrieb|Sales|Engineer|Entwickler|Developer|Berater|"
              r"Consultant|Assistent|Designer|Marketing|Produkt|Projekt|HR|"
              r"Gründer|Founder|Owner|Inhaber|Architekt)\b")
    for line in text_lines:
        if line == data["name"]:
            continue
        if re.search(pos_kw, line, re.I):
            data["position"] = line
            break

    # 5. Firma (explizite Firmensuffixe)
    co_kw = (r"\b(GmbH|AG|KG|OHG|UG|Inc|Ltd|SE|e\.V\.|mbH|GbR|Co\.|"
             r"Studio|Agency|Agentur|Solutions|Systems|Consulting|Group|"
             r"Holding)\b")
    for line in text_lines:
        if line in (data["name"], data["position"]):
            continue
        if re.search(co_kw, line, re.I):
            data["company"] = line
            break

    # 6. Firma-Fallback aus E-Mail-Domain (z. B. fbdesign@... → Fbdesign)
    if not data["company"] and data["email"]:
        try:
            domain_part = data["email"].split("@")[1]
            base = domain_part.split(".")[0]
            if base.lower() not in _GENERIC_DOMAINS and len(base) > 2:
                data["company"] = base.capitalize()
        except (IndexError, AttributeError):
            pass

    # 7. Firma-Fallback aus Domain-Zeile (z. B. "fbdesign.de")
    if not data["company"]:
        for line in lines:
            m2 = re.fullmatch(
                r"((?:www\.)?[a-zA-Z0-9\-]+\.(?:de|com|org|net|eu|io|at|ch))",
                line, re.I)
            if m2:
                domain = m2.group(1)
                base = domain.replace("www.", "").split(".")[0]
                if base.lower() not in _GENERIC_DOMAINS and len(base) > 2:
                    data["company"] = base.capitalize()
                    break

    # 8. Letzter Name-Fallback
    if not data["name"] and text_lines:
        for line in text_lines[:3]:
            if len(line) > 3 and not re.search(r"\d", line):
                data["name"] = line
                break

    return data


def ocr_image(path: str) -> dict:
    """Erkennt Felder aus einer Visitenkarte."""
    if not _TESS:
        return _empty_result(
            "OCR nicht verfügbar. Bitte pytesseract + Tesseract installieren.")

    p = Path(path)
    if not p.exists():
        return _empty_result(f"Bild nicht gefunden: {path}")

    try:
        with Image.open(p) as image:
            image.load()
            processed = _preprocess_image(image)
    except Exception as e:
        return _empty_result(f"Bild konnte nicht gelesen werden: {e}")

    text = _run_tesseract(processed)
    if not text.strip():
        return _empty_result(
            "Kein Text erkannt. Das Bild ist möglicherweise zu unscharf, "
            "zu dunkel oder enthält kein lesbares Schriftstück.")

    logging.debug("OCR Rohtext:\n%s", text)

    data = _parse_text(text)
    found = sum(1 for v in data.values() if v)
    confidence = found / 5.0

    return {
        **data,
        "needs_review": confidence < 0.6,
        "confidence": confidence,
        "raw_text": text,
        "error": "",
    }