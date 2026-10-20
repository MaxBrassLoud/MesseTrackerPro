"""OCR-Dienst mit feldgenauer Confidence, Mehrsprachigkeit,
Webseiten- und Adress-Erkennung."""
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

_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
if _TESS:
    for _candidate in _TESSERACT_CANDIDATES:
        if Path(_candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = _candidate
            break

# Mehrsprachige OCR: Deutsch + Englisch + romanische Sprachen
_LANGS = "deu+eng+fra+spa+ita"

_GENERIC_DOMAINS = {
    "gmail", "googlemail", "web", "gmx", "t-online", "outlook",
    "hotmail", "yahoo", "live", "icloud", "me", "aol", "mail",
    "protonmail", "posteo",
}

# Sprachindikatoren (Häufigkeit in typischen Visitenkartenphrasen)
_LANG_HINTS = {
    "de": ["straße", "str.", "geschäftsführer", "vertrieb", "gmbh", "platz",
           "berater", "leiter", "tel.", "mobil", "fax"],
    "en": ["street", "manager", "sales", "director", "ltd.", "inc.",
           "phone", "mobile", "consultant", "engineering"],
    "fr": ["rue", "gérant", "directeur", "ventes", "téléphone", "sarl",
           "sas", "conseil", "responsable"],
    "es": ["calle", "gerente", "director", "ventas", "teléfono",
           "consultor", "empresa"],
    "it": ["via", "amministratore", "direttore", "vendite", "telefono",
           "consulente", "azienda"],
}

# Adressmuster – deutsche Hauptvariante + englische Fallback-Variante
_STREET_PATTERNS = [
    re.compile(
        r"^[A-ZÄÖÜ][\wäöüß\-\.]*(?:straße|strasse|str\.|weg|gasse|platz|"
        r"allee|ring|damm|ufer|steig|berg|feld|au|hof|garten|tor|pforte)"
        r"\s*\d+[a-zA-Z]?\s*$",
        re.IGNORECASE),
    re.compile(
        r"^\d+\s+[A-Z][\w\s]+\s"
        r"(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Lane|Ln\.|Boulevard|"
        r"Blvd\.|Drive|Dr\.|Way|Court|Ct\.|Place|Pl\.)\s*$",
        re.IGNORECASE),
]
_POSTAL_CITY_RE = re.compile(
    r"^([A-Z]{1,2}-\d{4,5}|\d{4,5})\s+"
    r"([A-ZÄÖÜ][\wäöüßÄÖÜ\.\-]+(?:\s+[A-ZÄÖÜ][\wäöüßÄÖÜ\.\-]+)*)\s*$")


def _empty_result(error: str = "") -> dict:
    return {
        "name": "", "company": "", "position": "", "phone": "", "email": "",
        "website": "", "address": "",
        "needs_review": True, "confidence": 0.0,
        "field_confidence": {
            k: 0.0 for k in
            ("name", "company", "position", "phone", "email",
             "website", "address")
        },
        "language": "mixed",
        "raw_text": "", "error": error,
    }


def _preprocess_image(image):
    """Graustufen → Blur gegen Moiré → Autokontrast → Upscale → Schärfen."""
    try:
        img = image.convert("L")
        img = img.filter(ImageFilter.GaussianBlur(radius=1))
        img = ImageOps.autocontrast(img, cutoff=2)
        if img.width < 1000:
            ratio = 1000 / img.width
            img = img.resize((1000, int(img.height * ratio)),
                             Image.Resampling.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150,
                                                 threshold=3))
        img = ImageEnhance.Contrast(img).enhance(1.4)
        return img
    except Exception:
        return image.convert("L")


def _run_tesseract(img) -> str:
    """Probiert mehrere PSM-Modi, dann Fallback auf Englisch."""
    for psm in (6, 11, 4):
        try:
            text = pytesseract.image_to_string(
                img, lang=_LANGS, config=f"--oem 3 --psm {psm}")
            if text and len(text.strip()) >= 3:
                return text
        except Exception:
            continue
    try:
        return pytesseract.image_to_string(
            img, lang="eng", config="--oem 3 --psm 6")
    except Exception:
        return ""


def _detect_language(text: str) -> str:
    lower = text.lower()
    hits = {lang: sum(lower.count(word) for word in words)
            for lang, words in _LANG_HINTS.items()}
    best = max(hits.items(), key=lambda kv: kv[1], default=("", 0))
    if best[1] == 0:
        return "mixed"
    ordered = sorted(hits.values(), reverse=True)
    if len(ordered) > 1 and ordered[0] > 0 and ordered[1] / ordered[0] > 0.7:
        return "mixed"
    return best[0]


def _extract_website(text: str, email: str = "") -> str:
    """Extrahiert eine Webseite; E-Mail-Adresse wird vorher entfernt."""
    cleaned = text
    if email:
        cleaned = cleaned.replace(email, " ")

    patterns = [
        (r"https?://[^\s\)\]\>\"']+", 0.95),
        (r"\bwww\.[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+"
         r"(?:/[^\s\)\]\>\"']*)?", 0.9),
        (r"\b[a-zA-Z0-9-]+\.(?:de|com|org|net|eu|io|at|ch|fr|es|it|"
         r"co\.uk|biz|info)(?:/[^\s\)\]\>\"']*)?", 0.6),
    ]
    for pattern, _conf in patterns:
        for m in re.finditer(pattern, cleaned, re.IGNORECASE):
            url = m.group(0).strip(".,;:()[]<>\"' ")
            base = url.lower()
            for prefix in ("https://", "http://", "www."):
                if base.startswith(prefix):
                    base = base[len(prefix):]
            domain_root = base.split("/")[0].split(".")[0]
            if domain_root in _GENERIC_DOMAINS:
                continue
            return url
    return ""


def _extract_address(lines: list[str]) -> str:
    """Erkennt Straße + Hausnummer und kombiniert sie mit PLZ + Ort."""
    for i, line in enumerate(lines):
        s = line.strip()
        is_street = any(p.match(s) for p in _STREET_PATTERNS)
        if not is_street:
            continue

        # Nächste Zeile nach PLZ + Ort absuchen
        if i + 1 < len(lines):
            m = _POSTAL_CITY_RE.match(lines[i + 1].strip())
            if m:
                return f"{s}, {lines[i + 1].strip()}"
        # In derselben Zeile?
        m = _POSTAL_CITY_RE.search(s)
        if m:
            return s
        # Nur Straße + Nummer
        return s

    # Fallback: reine PLZ/Ort-Zeile, aber nur wenn direkt davor
    # eine Straßenzeile steht (wird oben schon abgedeckt) – sonst nichts.
    return ""


def _field_confidence(data: dict, raw_text: str,
                      name_hint_line: int | None) -> dict:
    conf = {k: 0.0 for k in
            ("name", "company", "position", "phone", "email",
             "website", "address")}

    if data["email"]:
        conf["email"] = 0.95 if "@" in raw_text else 0.85

    if data["phone"]:
        digits = re.sub(r"\D", "", data["phone"])
        if len(digits) >= 9:
            conf["phone"] = 0.9
        elif len(digits) >= 7:
            conf["phone"] = 0.75

    if data["name"]:
        conf["name"] = 0.85 if name_hint_line == 0 else 0.7
        if re.search(r"\d", data["name"]):
            conf["name"] *= 0.6

    if data["company"]:
        if re.search(r"(GmbH|AG|KG|UG|SE|Inc|Ltd|e\.V\.|Sàrl|SAS|S\.A\.|B\.V\.)",
                     data["company"]):
            conf["company"] = 0.9
        else:
            conf["company"] = 0.5

    if data["position"]:
        conf["position"] = 0.7
        if re.search(r"\b(CEO|CTO|CFO|Geschäftsführer|Director|Manager)\b",
                     data["position"], re.I):
            conf["position"] = 0.85

    if data.get("website"):
        if data["website"].startswith(("http", "www")):
            conf["website"] = 0.9
        else:
            conf["website"] = 0.65

    if data.get("address"):
        # Vollständige Adresse = Straße + PLZ + Ort
        if re.search(r"\d+.*\d{4,5}\s+[A-ZÄÖÜ]", data["address"]):
            conf["address"] = 0.85
        else:
            conf["address"] = 0.5

    return conf


def _parse_text(text: str):
    raw_lines = [line.strip() for line in text.splitlines()]
    lines = [re.sub(r"^[^\w]+|[^\w]+$", "", line).strip() for line in raw_lines]
    lines = [line for line in lines if line]

    data = {
        "name": "", "company": "", "position": "", "email": "", "phone": "",
        "website": "", "address": "",
    }
    name_line_idx: int | None = None

    m = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if m:
        data["email"] = m.group(0).lower().replace(",", ".")

    m = re.search(r"(?:\+?49|0)[\d\s\-/()]{7,}", text)
    if not m:
        m = re.search(r"\+?\d[\d\s\-/()]{7,}\d", text)
    if m:
        clean = re.sub(r"[^\d+]", "", m.group(0).strip())
        if len(clean) >= 7:
            data["phone"] = clean

    # Webseite und Adresse aus den Rohzeilen
    data["website"] = _extract_website(text, data["email"])
    data["address"] = _extract_address(lines)

    def is_contact_info(line: str) -> bool:
        return bool(re.search(
            r"[@\d]|www\.|\.de\b|\.com\b|\.org\b|\.net\b|\.fr\b|\.es\b|"
            r"\.it\b|http",
            line, re.I))

    text_lines = [l for l in lines if not is_contact_info(l)]

    titles = r"\b(Dr\.?|Prof\.?|Dipl\.?|Ing\.?|MSc|BSc|MBA|M\.A\.|B\.A\.)\b"
    bad_words = (r"\b(Senior|Junior|Lead|Head|Chief|Manager|Designer|"
                 r"Developer|Sales|Vertrieb|Director|CEO|CTO|CFO)\b")
    for idx, line in enumerate(text_lines):
        clean = re.sub(titles, "", line).strip()
        words = clean.split()
        if 2 <= len(words) <= 4 and \
                all(re.fullmatch(r"[A-Za-zÄÖÜäöüßÀ-ÿ\-\.']+", w) for w in words) and \
                not re.search(bad_words, clean, re.I):
            data["name"] = line
            name_line_idx = idx
            break

    pos_kw = (r"\b(Geschäftsführer|Gérant|Directeur|Gerente|Amministratore|"
              r"Manager|Direktor|Leiter|CEO|CTO|CFO|"
              r"Vertrieb|Sales|Ventas|Vendite|Engineer|Entwickler|Developer|"
              r"Berater|Consultant|Consulente|Assistent|Designer|Marketing|"
              r"Produkt|Projekt|HR|Gründer|Founder|Owner|Inhaber|Architekt)\b")
    for line in text_lines:
        if line == data["name"]:
            continue
        if re.search(pos_kw, line, re.I):
            data["position"] = line
            break

    co_kw = (r"\b(GmbH|AG|KG|OHG|UG|Inc|Ltd|SE|e\.V\.|mbH|GbR|Co\.|"
             r"Sàrl|SARL|SAS|S\.A\.|S\.p\.A\.|B\.V\.|N\.V\.|PLC|LLC|LLP|"
             r"Studio|Agency|Agentur|Solutions|Systems|Consulting|Group|"
             r"Holding|Groupe|Grupo|Gruppo)\b")
    for line in text_lines:
        if line in (data["name"], data["position"]):
            continue
        if re.search(co_kw, line, re.I):
            data["company"] = line
            break

    if not data["company"] and data["email"]:
        try:
            domain_part = data["email"].split("@")[1]
            base = domain_part.split(".")[0]
            if base.lower() not in _GENERIC_DOMAINS and len(base) > 2:
                data["company"] = base.capitalize()
        except (IndexError, AttributeError):
            pass

    if not data["company"]:
        for line in lines:
            m2 = re.fullmatch(
                r"((?:www\.)?[a-zA-Z0-9\-]+\.(?:de|com|org|net|eu|io|at|ch|fr|es|it|co\.uk))",
                line, re.I)
            if m2:
                domain = m2.group(1)
                base = domain.replace("www.", "").split(".")[0]
                if base.lower() not in _GENERIC_DOMAINS and len(base) > 2:
                    data["company"] = base.capitalize()
                    break

    if not data["name"] and text_lines:
        for idx, line in enumerate(text_lines[:3]):
            if len(line) > 3 and not re.search(r"\d", line):
                data["name"] = line
                name_line_idx = idx
                break

    return data, name_line_idx


def ocr_image(path: str) -> dict:
    """Erkennt Visitenkartenfelder inkl. Feld-Confidence und Sprache."""
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

    logging.debug("OCR Rohtext (%s):\n%s", _detect_language(text), text)

    data, name_line_idx = _parse_text(text)
    field_conf = _field_confidence(data, text, name_line_idx)
    language = _detect_language(text)

    filled = sum(1 for v in data.values() if v)
    overall = (sum(field_conf.values()) / len(field_conf)) if field_conf else 0.0
    needs_review = overall < 0.6 or filled < 3

    return {
        **data,
        "needs_review": needs_review,
        "confidence": round(overall, 3),
        "field_confidence": {k: round(v, 3) for k, v in field_conf.items()},
        "language": language,
        "raw_text": text,
        "error": "",
    }