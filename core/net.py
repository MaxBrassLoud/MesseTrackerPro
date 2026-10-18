# core/net.py
"""Netzwerk-Helfer, zentralisiert."""
import socket


def local_ip() -> str:
    """Ermittelt die lokale LAN-IP möglichst zuverlässig.

    Reihenfolge:
      1. UDP-Socket-Trick (verbindet zu 8.8.8.8, sendet nichts)
      2. Hostname-Auflösung
      3. Fallback 127.0.0.1
    """
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