# core/net.py
"""Netzwerk-Helfer, zentralisiert."""
import socket
from pathlib import Path


def local_ip() -> str:
    """Ermittelt die lokale LAN-IP möglichst zuverlässig."""
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


def web_scheme() -> str:
    """Liefert 'https', wenn ein TLS-Zertifikat vorliegt, sonst 'http'."""
    from config import SSL_CERT_FILE, SSL_KEY_FILE
    try:
        if Path(SSL_CERT_FILE).exists() and Path(SSL_KEY_FILE).exists():
            return "https"
    except Exception:
        pass
    return "http"


def web_url(host: str | None = None, port: int | None = None) -> str:
    """Baut die vollständige Webserver-URL inkl. Schema."""
    from config import WEB_PORT
    if host is None:
        host = local_ip()
    if port is None:
        port = WEB_PORT
    return f"{web_scheme()}://{host}:{port}"