"""Automatische Erzeugung eines selbst-signierten TLS-Zertifikats.

Wird für PWA-Installation und Kamerazugriff (getUserMedia) benötigt,
weil Service Worker und Medien-APIs einen sicheren Kontext voraussetzen.

Das Zertifikat ist selbst-signiert (nicht offiziell), funktioniert aber
für den lokalen Betrieb im Messe-LAN. Es ist als CA:TRUE markiert, damit
es auf iOS als vertrauenswürdiges Root-Zertifikat installiert werden kann.

Primärquelle: `cryptography` (reines Python).
Fallback: openssl-Kommandozeile (falls cryptography fehlt).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    logger.warning(
        "cryptography nicht installiert – SSL-Generierung nur via openssl CLI.")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _current_lan_ip() -> str:
    """Ermittelt möglichst zuverlässig die LAN-IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _san_entries():
    """Sammelt alle Hostnamen und IPs, für die das Zertifikat gilt."""
    entries = [x509.DNSName("localhost")]
    try:
        hostname = socket.gethostname()
        if hostname and hostname != "localhost":
            entries.append(x509.DNSName(hostname))
            entries.append(x509.DNSName(f"{hostname}.local"))
    except Exception:
        pass

    ip_strings = ["127.0.0.1", "::1"]
    lan_ip = _current_lan_ip()
    if lan_ip and lan_ip not in ip_strings and not lan_ip.startswith("127."):
        ip_strings.append(lan_ip)
    for s in ip_strings:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            pass
    return entries


# ---------------------------------------------------------------------------
# Erzeugung via cryptography
# ---------------------------------------------------------------------------

def _generate_with_cryptography(cert_path: Path, key_path: Path,
                                valid_days: int):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Messe Tracker Pro"),
        x509.NameAttribute(NameOID.COMMON_NAME, "messe-tracker.local"),
    ])

    now = datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(
            x509.SubjectAlternativeName(_san_entries()),
            critical=False,
        )
        # CA:TRUE damit das Zertifikat auf iOS als Root installiert
        # werden kann. path_length=0 verhindert, dass es Zwischen-CAs
        # signieren darf.
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    # Key-Datei nur für Besitzer lesbar
    try:
        key_path.chmod(0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fallback: openssl CLI
# ---------------------------------------------------------------------------

def _generate_with_openssl(cert_path: Path, key_path: Path,
                           valid_days: int):
    hostname = socket.gethostname()
    lan_ip = _current_lan_ip()
    san_parts = [
        "DNS:localhost", "DNS:messe-tracker.local",
        f"DNS:{hostname}", f"DNS:{hostname}.local",
        "IP:127.0.0.1", "IP:::1",
    ]
    if lan_ip and lan_ip not in ("127.0.0.1",) and not lan_ip.startswith("127."):
        san_parts.append(f"IP:{lan_ip}")
    san = "subjectAltName=" + ",".join(san_parts)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key_path),
        "-out", str(cert_path),
        "-days", str(valid_days),
        "-nodes",
        "-subj", "/C=DE/ST=Local/L=Local/O=Messe Tracker Pro"
                 "/CN=messe-tracker.local",
        "-addext", san,
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,"
                   "keyCertSign",
        "-addext", "extendedKeyUsage=serverAuth",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    try:
        key_path.chmod(0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def ensure_ssl_certificate(cert_path, key_path,
                           valid_days: int = 825) -> tuple[Path, Path]:
    """Stellt sicher, dass cert/key existieren und zur aktuellen LAN-IP passen.

    Regeneriert das Zertifikat, wenn:
    - die Dateien fehlen
    - die LAN-IP sich seit der letzten Erzeugung geändert hat

    :raises RuntimeError: wenn weder cryptography noch openssl verfügbar sind
    """
    cert_path = Path(cert_path)
    key_path = Path(key_path)
    ip_marker = cert_path.with_suffix(".ip")

    current_ip = _current_lan_ip()

    if cert_path.exists() and key_path.exists():
        try:
            saved_ip = ip_marker.read_text(encoding="utf-8").strip()
        except Exception:
            saved_ip = ""
        if saved_ip == current_ip:
            logger.info("SSL-Zertifikat aktuell: %s (IP %s)",
                        cert_path, current_ip)
            return cert_path, key_path
        if saved_ip:
            logger.info("LAN-IP geändert (%s → %s) – Zertifikat wird neu "
                        "erzeugt.", saved_ip, current_ip)

    logger.info("Erzeuge selbst-signiertes SSL-Zertifikat: %s", cert_path)

    if _CRYPTO_OK:
        _generate_with_cryptography(cert_path, key_path, valid_days)
    else:
        try:
            _generate_with_openssl(cert_path, key_path, valid_days)
        except FileNotFoundError as e:
            raise RuntimeError(
                "Weder 'cryptography' noch 'openssl' verfügbar. Bitte "
                "installiere 'cryptography' (pip install cryptography) "
                "oder OpenSSL.") from e

    try:
        ip_marker.write_text(current_ip, encoding="utf-8")
    except Exception:
        pass

    logger.info(
        "SSL-Zertifikat erzeugt: %s (gültig %d Tage, IP %s). "
        "Beim ersten Aufruf im Browser muss die Zertifikatswarnung "
        "einmalig akzeptiert werden.", cert_path, valid_days, current_ip)
    return cert_path, key_path


def cert_fingerprint_sha256(cert_path) -> str:
    """Liefert den SHA-256-Fingerprint als Hex-String (für Anzeige)."""
    cert_path = Path(cert_path)
    if not cert_path.exists():
        return ""
    try:
        if _CRYPTO_OK:
            data = cert_path.read_bytes()
            cert = x509.load_pem_x509_certificate(data)
            return cert.fingerprint(hashes.SHA256()).hex().upper()
        # Fallback: openssl x509
        out = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-noout",
             "-fingerprint", "-sha256"],
            capture_output=True, check=True,
        ).stdout.decode()
        return out.split("=")[-1].strip()
    except Exception:
        return ""