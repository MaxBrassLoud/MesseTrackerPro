"""flipper_cli.py – minimaler Flipper-CLI-Client über pyserial."""
from __future__ import annotations
import re
import time
import serial

BAUD = 115200

# Firmware 1.5.x nutzt ">: " als Prompt
PROMPT_CANDIDATES = (b">: ", b"> ")
_SIZE_PREFIX = re.compile(r"^Size:\s*\d+\s*\r?\n", re.IGNORECASE)


class FlipperCLIError(Exception):
    pass


class FlipperCLI:
    def __init__(self, port, baud=BAUD, verbose=False):
        self.port = port
        self.verbose = verbose
        self.ser = serial.Serial(port, baud, timeout=0.1, write_timeout=2)
        time.sleep(0.3)
        self._drain()
        try:
            self.ser.write(b"\r\n")
            self._read_until_prompt(timeout=2.0)
        except FlipperCLIError:
            pass

    def _drain(self):
        self.ser.reset_input_buffer()
        while self.ser.in_waiting:
            self.ser.read(self.ser.in_waiting)
            time.sleep(0.01)

    def _read_until_prompt(self, timeout=5.0):
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self.ser.read(1)
            if not chunk:
                continue
            buf += chunk
            for prompt in PROMPT_CANDIDATES:
                if len(buf) >= len(prompt) and buf[-len(prompt):] == prompt:
                    return bytes(buf)
        raise FlipperCLIError(
            f"Timeout ({timeout}s) – Rohdaten der letzten 200 Bytes: "
            f"{bytes(buf)[-200:]!r}"
        )

    def command(self, cmd, timeout=5.0):
        self._drain()
        if self.verbose:
            print(f">>> {cmd}")
        self.ser.write((cmd + "\r\n").encode())
        self.ser.flush()
        raw = self._read_until_prompt(timeout)
        text = raw.decode("utf-8", errors="replace")

        # Prompt entfernen
        for prompt in (">: ", "> "):
            if text.endswith(prompt):
                text = text[:-len(prompt)]
                break

        # Echo der Befehlszeile entfernen (erste Zeile)
        lines = text.split("\n", 1)
        if lines and cmd.split()[0] in lines[0]:
            text = lines[1] if len(lines) > 1 else ""

        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

        if self.verbose:
            print(f"<<< {text!r}")
        return text

    def list_dir(self, path, timeout=5.0):
        """Liefert (name, is_dir)-Tupel.

        Flipper-CLI-Format:
            \\t[D] days
            \\t[F] config.txt 29b
        """
        try:
            out = self.command(f"storage list {path}", timeout=timeout)
        except FlipperCLIError:
            return []
        entries = []
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            is_dir = False
            if line.startswith("[D]"):
                is_dir, name = True, line[3:].strip()
            elif line.startswith("[F]"):
                name = line[3:].strip()
                # Size-Suffix abschneiden: "name.ext 123b" → "name.ext"
                if " " in name:
                    name = name.rsplit(" ", 1)[0]
            else:
                continue
            if name:
                entries.append((name, is_dir))
        return entries

    def read_file(self, path, timeout=10.0):
        try:
            content = self.command(f"storage read {path}", timeout=timeout)
        except FlipperCLIError:
            return None
        low = content.lower()[:30]
        if "error" in low or "not found" in low or "not exist" in low:
            return None
        # Flipper-CLI stellt "Size: N" voran – entfernen
        content = _SIZE_PREFIX.sub("", content)
        return content

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def find_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    flipper_ports = []
    other_ports = []
    for p in list_ports.comports():
        dev = p.device or ""
        desc = p.description or ""
        if not dev:
            continue
        is_flipper = (
            (getattr(p, "vid", None) == 0x0483
             and getattr(p, "pid", None) == 0x5740)
            or "flipper" in desc.lower()
            or "usbmodem" in dev.lower()
        )
        entry = (dev, desc or dev)
        if is_flipper:
            flipper_ports.append(entry)
        else:
            other_ports.append(entry)
    return flipper_ports + other_ports