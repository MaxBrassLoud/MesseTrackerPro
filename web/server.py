"""Lokaler Flask-Server für Smartphone-Anbindung."""
import io
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (Flask, g, request, render_template_string, redirect,
                   url_for, session, send_from_directory, send_file)
from markupsafe import escape
from PIL import Image

from config import (
    WEB_HOST, WEB_PORT, CARDS_DIR, ALLOWED_IMAGE_EXTENSIONS, MAX_UPLOAD_MB,
    MAX_IMAGE_PIXELS, MAX_IMAGE_DIMENSION, IMAGE_JPEG_QUALITY,
    SSL_CERT_FILE, SSL_KEY_FILE,
)
from core.auth import AuthService, AuthError
from core.contact_extras import set_contact_extras
from core.permissions import Perm
from core.ssl_cert import cert_fingerprint_sha256
from ui.themes import get_theme, build_web_css

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

logger = logging.getLogger(__name__)

_REQ_ID_RE = re.compile(r"^[A-Fa-f0-9\-]{16,64}$")
STATIC_DIR = Path(__file__).parent / "static"


def _safe_req_id(raw: str | None) -> str:
    """Sichert request_id gegen Path-Traversal ab."""
    if raw and _REQ_ID_RE.match(raw):
        return raw
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# PWA-Icons automatisch erzeugen
# ---------------------------------------------------------------------------

def _ensure_pwa_icons():
    """Erzeugt fehlende PWA-Icons (orange Quadrate mit „MT")."""
    icons_dir = STATIC_DIR / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import ImageDraw, ImageFont
    except ImportError:
        return

    sizes = [
        (192, "icon-192.png"),
        (512, "icon-512.png"),
        (180, "apple-touch-icon.png"),
        (32, "favicon.png"),
    ]

    for size, name in sizes:
        path = icons_dir / name
        if path.exists():
            continue
        img = Image.new("RGB", (size, size), "#FF8200")
        draw = ImageDraw.Draw(img)
        text = "MT"
        font = None
        for font_name in ("Arial.ttf", "arial.ttf",
                          "/System/Library/Fonts/Helvetica.ttc",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(font_name, size // 3)
                break
            except (OSError, IOError):
                continue
        if font is None:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = (size - tw) // 2 - bbox[0]
            y = (size - th) // 2 - bbox[1]
            draw.text((x, y), text, fill="#000000", font=font)
        except Exception:
            pass
        try:
            img.save(str(path))
            logger.info("PWA-Icon erzeugt: %s", path)
        except Exception as e:
            logger.warning("Icon %s nicht erzeugbar: %s", path, e)


# ---------------------------------------------------------------------------
# HTML-Layout
# ---------------------------------------------------------------------------

BASE_HTML = """
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport"
        content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" content="#FF8200">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Messe Tracker">
  <link rel="manifest" href="/manifest.json">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <link rel="icon" href="/static/icons/icon-192.png" sizes="192x192">
  <title>Messe Tracker Pro</title>
  <style>{{ web_css|safe }}
    body{padding-bottom:env(safe-area-inset-bottom)}
    header{padding-top:calc(14px + env(safe-area-inset-top))}
    .modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.72);
      display:none;align-items:center;justify-content:center;
      z-index:1000;padding:20px;
      -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);}
    .modal-backdrop.open{display:flex}
    .modal{background:var(--bg-panel);color:var(--fg-text);
      border:1px solid var(--accent);border-radius:14px;
      padding:22px 20px;max-width:360px;width:100%;
      box-shadow:0 20px 50px rgba(0,0,0,.6);
      animation:pop .15s ease-out;}
    @keyframes pop{from{transform:scale(.92);opacity:0}to{transform:scale(1);opacity:1}}
    .modal p{font-size:1.1em;margin:0 0 18px;text-align:center;line-height:1.4}
    .modal .modal-actions{display:flex;gap:10px}
    .modal .modal-actions button{flex:1;margin:0;padding:12px}
    .modal .modal-actions button.alt{background:var(--bg-input);
      color:var(--fg-text);border:1px solid var(--border);}
    .pwa-install{position:fixed;bottom:calc(16px + env(safe-area-inset-bottom));
      left:50%;transform:translateX(-50%);background:var(--accent);
      color:var(--accent-fg);padding:12px 20px;border-radius:24px;
      font-weight:700;box-shadow:0 8px 20px rgba(0,0,0,.4);
      border:0;cursor:pointer;display:none;z-index:50;font-size:.95em;}
    .option-card{display:block;padding:18px;background:var(--bg-input);
      border:1px solid var(--border);border-radius:12px;margin-bottom:12px;
      text-decoration:none;color:var(--fg-text);transition:.15s;}
    .option-card:active{background:var(--bg-panel);border-color:var(--accent);}
    .option-card b{color:var(--accent);font-size:1.05em;display:block;
      margin-bottom:6px;}
    .option-card small{color:var(--fg-muted);font-size:.85em;}
    /* QR-Scanner */
    #qr-video{width:100%;border-radius:12px;border:1px solid var(--border);
      background:#000;min-height:220px;object-fit:cover;}
    #qr-status{text-align:center;margin:12px 0;color:var(--fg-muted);}
    #qr-error{display:none;}
    .qr-frame{position:relative;width:100%;max-width:400px;margin:0 auto;}
    .qr-frame::after{content:"";position:absolute;inset:12%;
      border:3px solid var(--accent);border-radius:12px;
      pointer-events:none;box-shadow:0 0 0 9999px rgba(0,0,0,.35);}
    /* Admin-Dashboard */
    .stats-grid{display:grid;grid-template-columns:repeat(2,1fr);
      gap:10px;margin-bottom:12px;}
    @media (min-width:600px){.stats-grid{
      grid-template-columns:repeat(4,1fr);}}
    .stat-card{background:var(--bg-panel);border:1px solid var(--border);
      border-radius:12px;padding:14px;text-align:center;}
    .stat-num{font-size:1.8em;font-weight:700;color:var(--accent);
      line-height:1.1;}
    .stat-label{font-size:.8em;color:var(--fg-muted);margin-top:4px;}
    .contact-item{padding:10px 0;border-bottom:1px solid var(--border);}
    .contact-item:last-child{border-bottom:none;}
    .contact-row{display:flex;justify-content:space-between;gap:8px;
      align-items:baseline;}
    .contact-row b{font-size:.95em;}
    .contact-row small{color:var(--fg-muted);font-size:.8em;}
    .action-btn{display:block;width:100%;padding:14px;margin:8px 0;
      background:var(--bg-input);color:var(--fg-text);
      border:1px solid var(--border);border-radius:10px;
      font-weight:600;text-align:left;text-decoration:none;
      cursor:pointer;font-size:1em;font-family:inherit;}
    .action-btn:active{background:var(--bg-panel);
      border-color:var(--accent);}
    .action-btn.primary{background:var(--accent);color:var(--accent-fg);
      border:0;}
    .action-btn.primary:active{background:var(--accent-hover);}
    .emp-row{display:flex;justify-content:space-between;
      padding:8px 0;border-bottom:1px solid var(--border);}
    .emp-row:last-child{border-bottom:none;}
    .emp-state{font-size:.85em;color:var(--fg-muted);}
    .emp-state.on{color:#4ade80;font-weight:600;}
  </style>
</head>
<body>
  <header>
    <h1>Messe Tracker Pro</h1>
    {% if emp %}<div class="emp">Mitarbeiter: <b>{{ emp.name }}</b></div>{% endif %}
    {% if fair_name %}<div class="emp">Messe: <b>{{ fair_name }}</b></div>{% endif %}
  </header>
  <main>{{ body|safe }}</main>

  <div id="modal-backdrop" class="modal-backdrop">
    <div class="modal">
      <p id="modal-text"></p>
      <div class="modal-actions">
        <button type="button" class="alt" onclick="hideModal()">Abbrechen</button>
        <button type="button" onclick="doConfirm()">Bestätigen</button>
      </div>
    </div>
  </div>

  <button id="pwa-install-btn" class="pwa-install" type="button">
    📲 App installieren
  </button>

  <script>
    let _pendingForm = null;
    function showConfirm(form, text){
      _pendingForm = form;
      document.getElementById('modal-text').textContent = text;
      document.getElementById('modal-backdrop').classList.add('open');
      document.body.style.overflow = 'hidden';
      return false;
    }
    function hideModal(){
      document.getElementById('modal-backdrop').classList.remove('open');
      document.body.style.overflow = '';
      _pendingForm = null;
    }
    function doConfirm(){
      const f = _pendingForm; hideModal();
      if (f) f.submit();
    }
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') hideModal();
    });
  </script>

  <script>
  (function(){
    // Service Worker unter Root-Scope registrieren
    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('/sw.js').catch(err =>
        console.warn('[SW] Registrierung fehlgeschlagen:', err));
    }

    let deferredPrompt = null;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) {
        btn.style.display = 'block';
        btn.addEventListener('click', async () => {
          btn.style.display = 'none';
          deferredPrompt.prompt();
          await deferredPrompt.userChoice;
          deferredPrompt = null;
        }, { once: true });
      }
    });
  })();
  </script>

  <script>
  (function(){
    const TOKEN = "{{ token or '' }}";
    if (!TOKEN) return;
    try { localStorage.setItem('mt_token', TOKEN); } catch(e){}

    const DB_NAME = 'messe-tracker';
    const DB_VERSION = 1;
    let _dbPromise = null;

    function openDb(){
      if (_dbPromise) return _dbPromise;
      _dbPromise = new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains('pending_contacts')) {
            const s = db.createObjectStore('pending_contacts',
              {keyPath:'request_id'});
            s.createIndex('status', 'status');
          }
          if (!db.objectStoreNames.contains('images')) {
            db.createObjectStore('images', {keyPath:'request_id'});
          }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      return _dbPromise;
    }

    async function listPending(){
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('pending_contacts', 'readonly');
        const req = tx.objectStore('pending_contacts').getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
      });
    }
    async function savePending(entry){
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('pending_contacts', 'readwrite');
        tx.objectStore('pending_contacts').put(entry);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }
    async function saveImage(requestId, blob){
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('images', 'readwrite');
        tx.objectStore('images').put({
          request_id: requestId, blob: blob,
          name: 'card.jpg', type: blob.type
        });
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }
    async function loadImage(requestId){
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('images', 'readonly');
        const req = tx.objectStore('images').get(requestId);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    async function removePending(requestId){
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(
          ['pending_contacts','images'], 'readwrite');
        tx.objectStore('pending_contacts').delete(requestId);
        tx.objectStore('images').delete(requestId);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }

    async function updateBanner(){
      let banner = document.getElementById('sync-banner');
      if (!banner){
        banner = document.createElement('div');
        banner.id = 'sync-banner';
        banner.style.cssText =
          'position:sticky;top:0;z-index:20;padding:8px 12px;' +
          'font-size:.9em;text-align:center;border-bottom:2px solid #000;';
        document.body.insertBefore(banner, document.body.firstChild);
      }
      const pending = await listPending();
      const online = navigator.onLine;
      if (pending.length > 0){
        banner.style.background = online ? '#063' : '#430';
        banner.style.color = '#fff';
        banner.textContent = `⏳ ${pending.length} lokal gespeicherte(r) ` +
          `Eintrag/Einträge – ` +
          (online ? 'wird synchronisiert…' :
           'offline – wird übertragen, sobald Verbindung besteht.');
      } else if (online){
        banner.style.background = '#0a2a3a';
        banner.style.color = '#9fd';
        banner.textContent = '✅ Alle Einträge synchronisiert.';
        setTimeout(() => { if (banner.parentNode) banner.remove(); }, 4000);
      } else {
        banner.style.background = '#430';
        banner.style.color = '#fc9';
        banner.textContent =
          '📡 Offline – neue Einträge werden lokal gespeichert.';
      }
    }

    async function tryFlush(){
      if (!navigator.onLine) { updateBanner(); return; }
      const pending = await listPending();
      for (const entry of pending){
        try {
          const fd = new FormData();
          for (const [k, v] of Object.entries(entry.fields))
            fd.append(k, v);
          const img = await loadImage(entry.request_id);
          if (img && img.blob) fd.append('image', img.blob, 'card.jpg');
          const resp = await fetch('/api/' + TOKEN + '/sync', {
            method: 'POST', body: fd
          });
          if (resp.ok){
            const json = await resp.json().catch(() => ({status:'synced'}));
            if (json.status === 'synced' || json.status === 'duplicate'){
              await removePending(entry.request_id);
            } else {
              entry.attempts = (entry.attempts || 0) + 1;
              entry.last_error = json.message || 'Serverfehler';
              await savePending(entry);
            }
          }
        } catch(e){ }
      }
      updateBanner();
    }

    document.addEventListener('submit', async (ev) => {
      const form = ev.target;
      if (!form.action || !form.action.includes('/api/' + TOKEN + '/submit'))
        return;
      ev.preventDefault();
      const formData = new FormData(form);
      const fields = {};
      let imageBlob = null;
      for (const [k, v] of formData.entries()){
        if (v instanceof File){
          if (v.size > 0) imageBlob = v;
        } else { fields[k] = v; }
      }
      if (!fields.request_id){
        fields.request_id = 'off_' + Math.random().toString(36).slice(2) +
                            Date.now();
      }
      const reqId = fields.request_id;
      const entry = {
        request_id: reqId, fields: fields, attempts: 0,
        status: 'pending', created_at: new Date().toISOString()
      };
      try {
        await savePending(entry);
        if (imageBlob) await saveImage(reqId, imageBlob);
      } catch(err){
        alert('Lokale Speicherung fehlgeschlagen: ' + err);
        return;
      }
      updateBanner();
      tryFlush();
      const card = form.closest('.card');
      if (card){
        const ok = document.createElement('div');
        ok.className = 'ok';
        ok.textContent = '💾 Lokal gespeichert. Übertragung läuft…';
        card.parentNode.insertBefore(ok, card);
        setTimeout(() => ok.remove(), 6000);
      }
    }, true);

    window.addEventListener('online', () => { updateBanner(); tryFlush(); });
    window.addEventListener('offline', updateBanner);
    setInterval(() => { if (navigator.onLine) tryFlush(); }, 15000);

    // Background-Sync-Trigger vom SW
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'mt-sync-now') tryFlush();
      });
    }

    updateBanner();
    tryFlush();
  })();
  </script>
</body>
</html>
"""


INDEX_BODY = """
<div class="card">
  <h3>👋 Willkommen bei Messe Tracker Pro</h3>
  <p style="color:var(--fg-muted);margin-bottom:16px;">
    Wähle deinen Zugangsweg:
  </p>
  <a href="/login" class="option-card">
    <b>🔐 Mit Zugangsdaten anmelden</b>
    <small>Benutzername und Passwort deines Messe-Tracker-Kontos</small>
  </a>
  <a href="/scan-qr" class="option-card">
    <b>📷 QR-Code scannen</b>
    <small>Persönlicher Mitarbeiter-QR-Code – öffnet den Erfassungsmodus</small>
  </a>
  <p style="margin-top:20px;color:var(--fg-muted);font-size:.85em;
            text-align:center;">
    Tipp: Auf dem Smartphone kannst du diese Seite über
    „Zum Home-Bildschirm hinzufügen" als App installieren.
  </p>
  <p style="margin-top:14px;color:var(--fg-muted);font-size:.8em;
            text-align:center;">
    Bei HTTPS-Warnung:
    <a href="/cert.crt" class="link">Zertifikat installieren</a>
    &middot;
    <a href="/cert-fingerprint" class="link">Fingerprint prüfen</a>
  </p>
</div>
"""


SCAN_QR_BODY = r"""
<div class="card">
  <h3>📷 QR-Code scannen</h3>
  <p style="color:var(--fg-muted);font-size:.9em;margin-bottom:14px;">
    Halte den persönlichen QR-Code deines Mitarbeiterprofils
    (vom Stand-Laptop oder Ausdruck) vor die Kamera.
  </p>

  <div class="qr-frame">
    <video id="qr-video" autoplay playsinline muted></video>
  </div>
  <canvas id="qr-canvas" style="display:none;"></canvas>

  <p id="qr-status">Scanner wird initialisiert…</p>
  <p id="qr-error" class="err"></p>

  <div id="qr-file-fallback" style="display:none;margin-top:16px;">
    <p style="color:var(--fg-muted);font-size:.9em;">
      Du kannst auch ein Foto des QR-Codes hochladen:
    </p>
    <input type="file" id="qr-file" accept="image/*">
  </div>

  <p style="margin-top:20px;">
    <a href="/" class="link">← Zurück zur Startseite</a>
  </p>
</div>

<script>
(function(){
  const video = document.getElementById('qr-video');
  const canvas = document.getElementById('qr-canvas');
  const statusEl = document.getElementById('qr-status');
  const errorEl = document.getElementById('qr-error');
  const fileInput = document.getElementById('qr-file');
  const fileFallback = document.getElementById('qr-file-fallback');

  let stream = null;
  let scanning = false;
  let nativeDetector = null;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });

  function setStatus(text, color) {
    statusEl.textContent = text;
    statusEl.style.color = color || 'var(--fg-muted)';
  }
  function showError(html) {
    errorEl.innerHTML = html;
    errorEl.style.display = 'block';
  }
  function clearError() {
    errorEl.style.display = 'none';
    errorEl.innerHTML = '';
  }
  function showFileFallback(text) {
    if (fileFallback) fileFallback.style.display = 'block';
    setStatus(text);
  }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;',
      '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function extractToken(value) {
    if (!value) return null;
    const s = String(value).trim();
    let m = s.match(/\/scan\/([A-Za-z0-9_\-\.]+)/);
    if (m && m[1].length >= 8) return m[1];
    try {
      const u = new URL(s);
      const parts = u.pathname.split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0] === 'scan') {
        return decodeURIComponent(parts[1]);
      }
    } catch(e) { }
    m = s.match(/^([A-Za-z0-9_\-]{16,})$/);
    if (m) return m[1];
    m = s.match(/\b([A-Za-z0-9_\-]{24,})\b/);
    if (m) return m[1];
    return null;
  }

  function handleScanned(value) {
    const s = String(value).trim();
    const token = extractToken(s);
    if (!token) {
      showError(
        'Dieser QR-Code ist kein gültiger Messe-Tracker-Code.<br>' +
        '<span style="font-size:.85em;color:var(--fg-muted);">' +
        'Gescannter Inhalt:</span>' +
        '<code style="word-break:break-all;user-select:all;display:block;' +
        'margin-top:6px;padding:8px;background:#000;border-radius:6px;' +
        'font-size:.8em;color:#fc9;">' + escapeHtml(s) + '</code>'
      );
      return;
    }
    stopScanner();
    try { localStorage.setItem('mt_token', token); } catch(e){}
    setStatus('✔ QR-Code erkannt – leite weiter…', '#0a8');
    setTimeout(() => {
      window.location.href = '/scan/' + encodeURIComponent(token);
    }, 300);
  }

  function stopScanner() {
    scanning = false;
    if (stream) {
      stream.getTracks().forEach(t => t.stop());
      stream = null;
    }
    if (video) video.srcObject = null;
  }

  function loadJsQR() {
    return new Promise((resolve, reject) => {
      if (window.jsQR) { resolve(); return; }
      const script = document.createElement('script');
      script.src = '/static/jsQR.min.js';
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(
        'jsQR.min.js nicht gefunden.'));
      document.head.appendChild(script);
    });
  }

  function scanWithJsQR() {
    if (!scanning) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = window.jsQR(imageData.data, imageData.width,
                               imageData.height, {
        inversionAttempts: 'attemptBoth'
      });
      if (code && code.data) {
        handleScanned(code.data);
        return;
      }
    }
    requestAnimationFrame(scanWithJsQR);
  }

  async function scanWithNative() {
    if (!scanning || !nativeDetector) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      try {
        const codes = await nativeDetector.detect(video);
        if (codes && codes.length > 0 && codes[0].rawValue) {
          handleScanned(codes[0].rawValue);
          return;
        }
      } catch(e) { }
    }
    requestAnimationFrame(scanWithNative);
  }

  async function startCamera() {
    if (!window.isSecureContext) {
      showFileFallback(
        'Kamera-Zugriff erfordert HTTPS.');
      return null;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showFileFallback('Dein Browser unterstützt keinen Kamera-Zugriff.');
      return null;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false
      });
      video.srcObject = stream;
      await video.play();
      return stream;
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        showError('Kamera-Zugriff verweigert.');
      } else if (e.name === 'NotFoundError') {
        showError('Keine Kamera gefunden.');
      } else {
        showError('Kamera-Fehler: ' + e.message);
      }
      showFileFallback('Alternativ kannst du ein Foto hochladen.');
      return null;
    }
  }

  function setupFileUpload() {
    if (!fileInput) return;
    fileInput.addEventListener('change', async (ev) => {
      const file = ev.target.files[0];
      if (!file) return;
      if (!window.jsQR) {
        showError('Foto-Erkennung nicht verfügbar (jsQR fehlt).');
        return;
      }
      const img = new Image();
      img.onload = () => {
        canvas.width = img.width;
        canvas.height = img.height;
        ctx.drawImage(img, 0, 0);
        const imageData = ctx.getImageData(0, 0, canvas.width,
                                           canvas.height);
        const code = window.jsQR(imageData.data, canvas.width,
                                 canvas.height, {
          inversionAttempts: 'attemptBoth'
        });
        if (code && code.data) {
          handleScanned(code.data);
        } else {
          showError('Im Foto wurde kein QR-Code erkannt.');
        }
        URL.revokeObjectURL(img.src);
      };
      img.onerror = () => showError('Bild konnte nicht geladen werden.');
      img.src = URL.createObjectURL(file);
    });
  }

  async function init() {
    setupFileUpload();

    const s = await startCamera();
    if (!s) return;

    if ('BarcodeDetector' in window) {
      try {
        const formats = await BarcodeDetector.getSupportedFormats();
        if (formats.includes('qr_code')) {
          nativeDetector = new BarcodeDetector({ formats: ['qr_code'] });
          scanning = true;
          clearError();
          setStatus('Kamera aktiv – halte den QR-Code vor die Kamera.',
                    'var(--accent)');
          requestAnimationFrame(scanWithNative);
          return;
        }
      } catch (e) { }
    }

    try {
      await loadJsQR();
      scanning = true;
      clearError();
      setStatus('Kamera aktiv – halte den QR-Code vor die Kamera.',
                'var(--accent)');
      requestAnimationFrame(scanWithJsQR);
    } catch (e) {
      showError('QR-Scanner nicht verfügbar. Administrator: bitte ' +
                'jsQR.min.js in web/static/ ablegen.');
      showFileFallback('Ohne jsQR ist keine QR-Erkennung möglich.');
    }
  }

  init();
})();
</script>
"""


WEB_LOGIN_BODY = """
<div class="card">
  <h3>🔐 Anmeldung</h3>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post"
        action="/login{% if request.args.get('next') %}?next={{ request.args.get('next') }}{% endif %}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <input name="username" placeholder="Benutzername"
           autocomplete="username" autofocus>
    <input name="password" type="password" placeholder="Passwort"
           autocomplete="current-password">
    <button type="submit">Anmelden</button>
  </form>
  <p style="margin-top:14px;">
    <a href="/" class="link">← Zurück zur Startseite</a>
  </p>
</div>
"""


WEB_ADMIN_BODY = """
<div class="card">
  <h3>👋 Willkommen, {{ username }}{% if is_admin %} · Administrator{% endif %}</h3>
  {% if fair %}
    <p style="margin-top:8px;">Aktive Messe: <b>{{ fair.name }}</b></p>
    {% if fair_day %}
      <p style="color:#4ade80;">
        🟢 Messetag aktiv seit {{ fair_day.started_at[:16]|replace('T',' ') }}
        ({{ fair_day.day_date }})
      </p>
    {% else %}
      <p style="color:var(--accent);">⚠️ Kein aktiver Messetag</p>
    {% endif %}
  {% else %}
    <p style="color:var(--accent);">⚠️ Keine Messe angelegt</p>
  {% endif %}
</div>

{% if stats %}
<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-num">{{ stats.total_today }}</div>
    <div class="stat-label">Kontakte heute</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ stats.total_fair }}</div>
    <div class="stat-label">Kontakte gesamt</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ stats.pending_cards }}</div>
    <div class="stat-label">Offene Karten</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ stats.tasks_open }}</div>
    <div class="stat-label">Offene Aufgaben</div>
  </div>
</div>
{% endif %}

<div class="card">
  <h3>⚙️ Schnellaktionen</h3>
  {% if my_employee %}
    <a href="/scan/{{ my_employee.token }}" class="action-btn primary">
      📷 Als {{ username }} erfassen
    </a>
  {% endif %}
  <a href="/scan-qr" class="action-btn">
    🔍 Anderen Mitarbeiter-QR scannen
  </a>
  {% if can_manage %}
    {% if fair_day %}
      <form method="post" action="/admin/day/end"
            onsubmit="return showConfirm(this, 'Messetag jetzt beenden?')">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="action-btn">
          ⏹ Messetag beenden
        </button>
      </form>
    {% elif fair %}
      <form method="post" action="/admin/day/start">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="action-btn">
          ▶ Messetag starten
        </button>
      </form>
    {% endif %}
  {% endif %}
</div>

{% if can_create and fair_day %}
<div class="card">
  <h3>➕ Kontakt manuell erfassen</h3>
  <form method="post" action="/admin/contact/add">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <input name="name" placeholder="Name">
    <input name="company" placeholder="Firma">
    <input name="position" placeholder="Position">
    <input name="phone" placeholder="Telefon" type="tel">
    <input name="email" placeholder="E-Mail" type="email">
    <textarea name="notes" placeholder="Notizen"></textarea>
    <button type="submit">Speichern</button>
  </form>
</div>
{% endif %}

{% if recent %}
<div class="card">
  <h3>📇 Letzte Kontakte</h3>
  {% for c in recent %}
    <div class="contact-item">
      <div class="contact-row">
        <div>
          <b>{{ c.name or '(ohne Namen)' }}</b>
          {% if c.company %}<br><small>{{ c.company }}</small>{% endif %}
        </div>
        <div style="text-align:right;">
          <small>{{ c.status }}</small><br>
          <small style="color:var(--fg-muted);">{{ c.created_at[11:16] }}</small>
        </div>
      </div>
    </div>
  {% endfor %}
</div>
{% endif %}

{% if employees %}
<div class="card">
  <h3>👥 Mitarbeiter</h3>
  {% for e in employees %}
    <div class="emp-row">
      <span>{{ e.name }}</span>
      <span class="emp-state {% if attendance.get(e.id, {}).get('event_type') == 'enter' %}on{% endif %}">
        {% if attendance.get(e.id, {}).get('event_type') == 'enter' %}
          🟢 am Stand
        {% elif attendance.get(e.id, {}).get('event_type') == 'leave' %}
          ⚪ abwesend
        {% else %}— ohne Status{% endif %}
      </span>
    </div>
  {% endfor %}
</div>
{% endif %}

<div class="card">
  <h3>Berechtigungen</h3>
  <p style="color:var(--fg-muted);font-size:.85em;">
    {% for p in perms %}<code>{{ p }}</code>{% if not loop.last %}, {% endif %}{% endfor %}
  </p>
  <form method="post" action="/logout" style="margin-top:16px;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="action-btn">Abmelden</button>
  </form>
</div>
"""


SCAN_BODY = """
{{ msg_html|safe }}

<div class="card">
  <h3>👥 Dein Status am Stand</h3>
  {% if is_present %}
    <div class="status status-on">
      🟢 <b>Am Stand</b>
      {% if since_short %}<br><small>seit {{ since_short }}</small>{% endif %}
    </div>
    <form method="post" action="/api/{{ token }}/attendance"
          onsubmit="return showConfirm(this, 'Du möchtest den Stand jetzt verlassen?')">
      <input type="hidden" name="event_type" value="leave">
      <button type="submit" class="alt">Stand verlassen</button>
    </form>
  {% else %}
    <div class="status status-off">
      ⚪ <b>Nicht am Stand</b>
      {% if since_short %}<br><small>seit {{ since_short }}</small>{% endif %}
    </div>
    <form method="post" action="/api/{{ token }}/attendance"
          onsubmit="return showConfirm(this, 'Du möchtest den Stand jetzt betreten?')">
      <input type="hidden" name="event_type" value="enter">
      <button type="submit">Stand betreten</button>
    </form>
  {% endif %}
</div>

<div class="card">
  <h3>✍️ Neuer Kontakt</h3>
  <p style="color:var(--fg-muted);font-size:.9em;margin:0 0 12px;">
    Alle Felder sind optional. Du kannst Felder ausfüllen, ein Foto
    hinzufügen oder beides kombinieren.
  </p>
  <form method="post" action="/api/{{ token }}/submit" enctype="multipart/form-data">
    <input name="name" placeholder="Name">
    <input name="company" placeholder="Firma">
    <input name="position" placeholder="Position">
    <input name="phone" placeholder="Telefon" type="tel">
    <input name="email" placeholder="E-Mail" type="email">
    <input name="website" placeholder="Webseite (z. B. www.firma.de)" type="text">
    <input name="address" placeholder="Adresse (Straße, PLZ Ort)">
    <select name="status">
      {% for s in statuses %}<option>{{ s }}</option>{% endfor %}
    </select>
    <textarea name="notes" placeholder="Notizen"></textarea>
    <label style="display:block;margin-top:14px;margin-bottom:4px;
                  color:var(--fg-muted);font-size:.9em;font-weight:600;">
      📷 Visitenkarte fotografieren (optional)
    </label>
    <input type="file" name="image" accept="image/*" capture="environment">
    <input type="hidden" name="request_id" value="{{ req_id }}">
    <button type="submit">Speichern</button>
  </form>
</div>
"""

DISABLED_BODY = """
<div class="warn">
  <h3>⛔ Zugang deaktiviert</h3>
  <p>Dein Zugang wurde deaktiviert.</p>
</div>
"""


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _fmt_dt(iso):
    if not iso or len(iso) < 16:
        return iso or ""
    return f"{iso[8:10]}.{iso[5:7]}. {iso[11:16]}"


def _theme_css(db):
    return build_web_css(get_theme(db.get_setting("theme", "Flipper")))


def _page(db, emp=None, fair_name=None, body="", token=None):
    return render_template_string(
        BASE_HTML, emp=emp, fair_name=fair_name, body=body,
        web_css=_theme_css(db), token=token)


def _active_employee(db, token):
    emp = db.get_employee_by_token(token)
    if not emp:
        return None, (_page(db, body=(
            '<div class="err">Ungültiger oder abgelaufener Zugangslink.'
            '</div>')), 404)
    if not emp.get("active"):
        return None, (_page(db, emp=emp, body=DISABLED_BODY), 403)
    return emp, None


def _validate_image(file_storage):
    try:
        img = Image.open(file_storage.stream)
        img.verify()
        file_storage.seek(0)
        return True, None
    except Exception as e:
        return False, str(e)


def _save_upload(file_storage, req_id: str) -> str:
    safe_id = _safe_req_id(req_id)
    target = CARDS_DIR / f"{safe_id}.jpg"
    if target.exists():
        return str(target)
    file_storage.stream.seek(0)
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except Exception as e:
        raise ValueError(f"Bild nicht lesbar: {e}")
    try:
        if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info):
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if max(img.size) > MAX_IMAGE_DIMENSION:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                          Image.Resampling.LANCZOS)
    except Exception as e:
        raise ValueError(f"Bildverarbeitung fehlgeschlagen: {e}")
    tmp = CARDS_DIR / f".{safe_id}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        img.save(tmp, format="JPEG", quality=IMAGE_JPEG_QUALITY,
                 optimize=True)
        os.replace(tmp, target)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Bild konnte nicht gespeichert werden: {e}")
    return str(target)


# ---------------------------------------------------------------------------
# App-Factory
# ---------------------------------------------------------------------------

def create_app(db):
    _ensure_pwa_icons()

    app = Flask(__name__)
    app.secret_key = db.get_setting("web_secret_key") or uuid.uuid4().hex
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    auth = AuthService(db)

    def _generate_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = uuid.uuid4().hex
        return session["_csrf_token"]

    app.jinja_env.globals["csrf_token"] = _generate_csrf_token

    @app.before_request
    def _auth_gate():
        if (request.path.startswith("/scan/")
                or request.path == "/scan-qr"
                or request.path.startswith("/api/")
                or request.path.startswith("/static/")
                or request.path == "/pwa-start"
                or request.path == "/sw.js"
                or request.path == "/manifest.json"
                or request.path == "/cert.crt"
                or request.path == "/cert-fingerprint"):
            return None
        if request.path in ("/", "/login"):
            return None
        if (request.path.startswith("/admin")
                or request.path == "/logout"):
            token = session.get("session_token")
            user = auth.user_for_session(token)
            if not user:
                if request.path == "/logout":
                    return redirect(url_for("web_login"))
                return redirect(url_for("web_login", next=request.path))
            g.web_user = user
        return None

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            if request.path.startswith("/api/"):
                return None
            token = session.get("_csrf_token")
            form_token = request.form.get("csrf_token")
            if not token or not form_token or token != form_token:
                logger.warning("CSRF-Fehler: path=%s", request.path)
                return (
                    '<div class="err" style="margin:20px;padding:16px;'
                    'border-radius:10px;background:#a30;color:#fff;">'
                    '<b>CSRF-Token ungültig oder abgelaufen.</b><br>'
                    'Bitte lade die Seite neu.</div>', 400,
                )
        return None

    def _fair_name(fid):
        for f in db.list_fairs(include_archived=True):
            if f["id"] == fid:
                return f["name"]
        return "?"

    def _statuses():
        return [s["name"] for s in db.list_statuses(active_only=True)]

    def _error_page(db, emp, token, message):
        return _page(db, emp=emp, token=token, body=(
            f'<div class="err">{escape(message)}</div>'
            f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))

    def _store_extras(contact_id, address, website):
        try:
            set_contact_extras(db, contact_id,
                               address=address, website=website)
        except Exception:
            logger.exception("Extras nicht gespeichert (contact=%s)",
                             contact_id)

    # ------------------------------------------------------------------
    # Root-Routen für PWA
    # ------------------------------------------------------------------
    @app.route("/sw.js")
    def serve_sw():
        """Service Worker unter Root-Scope ausliefern."""
        resp = send_from_directory(
            str(STATIC_DIR), "sw.js",
            mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    @app.route("/manifest.json")
    def serve_manifest():
        return send_from_directory(
            str(STATIC_DIR), "manifest.json",
            mimetype="application/manifest+json")

    @app.route("/")
    def index():
        return _page(db, body=INDEX_BODY)

    @app.route("/scan-qr")
    def scan_qr_page():
        return _page(db, body=SCAN_QR_BODY)

    @app.route("/cert.crt")
    def download_cert():
        cert_path = Path(SSL_CERT_FILE)
        if not cert_path.exists():
            return "Kein Zertifikat vorhanden.", 404
        return send_file(
            str(cert_path),
            mimetype="application/x-x509-ca-cert",
            as_attachment=True,
            download_name="messe-tracker.crt",
        )

    @app.route("/cert-fingerprint")
    def cert_fingerprint():
        fp = cert_fingerprint_sha256(SSL_CERT_FILE)
        if not fp:
            return _page(db, body=(
                '<div class="card"><h3>🔐 Server-Zertifikat</h3>'
                '<p>Kein Zertifikat vorhanden.</p>'
                '<p><a href="/" class="link">← Zurück</a></p></div>'))
        return _page(db, body=(
            f'<div class="card"><h3>🔐 Server-Zertifikat</h3>'
            f'<p>SHA-256:</p>'
            f'<code style="word-break:break-all;">{fp}</code>'
            f'<p><a href="/cert.crt" class="link">📥 Download</a></p>'
            f'<p><a href="/" class="link">← Zurück</a></p></div>'))

    # ------------------------------------------------------------------
    # PWA-Start
    # ------------------------------------------------------------------
    @app.route("/pwa-start")
    def pwa_start():
        return _page(db, body="""
<div id="pwa-loading" style="text-align:center;padding:40px;">
  <p style="font-size:1.2em;color:var(--fg-muted);">App wird geladen…</p>
</div>
<div id="pwa-offline" style="display:none;">
  <div class="card">
    <h3>📡 Offline-Modus</h3>
    <p style="color:var(--fg-muted);">
      Deine Erfassungsseite ist noch nicht für den Offline-Betrieb
      vorbereitet. Bitte öffne sie einmal mit Internet.
    </p>
    <a href="/scan-qr" class="option-card" style="margin-top:12px;">
      <b>📷 QR-Code scannen</b>
      <small>Mitarbeiter-QR scannen und Erfassungsseite online aufrufen</small>
    </a>
  </div>
</div>
<script>
(async function() {
  const token = localStorage.getItem('mt_token');
  if (!token) {
    location.replace('/scan-qr');
    return;
  }
  const scanUrl = '/scan/' + encodeURIComponent(token);

  if (navigator.onLine) {
    location.replace(scanUrl);
    return;
  }

  try {
    if ('caches' in window) {
      const cached = await caches.match(scanUrl);
      if (cached) { location.replace(scanUrl); return; }
    }
  } catch(e) {}

  document.getElementById('pwa-loading').style.display = 'none';
  document.getElementById('pwa-offline').style.display = 'block';
})();
</script>
""")

    # ------------------------------------------------------------------
    # Login / Logout
    # ------------------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def web_login():
        error = ""
        if request.method == "POST":
            try:
                user, token = auth.login(
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    ip=request.remote_addr or "",
                    user_agent=(request.headers.get("User-Agent", "")
                                or "")[:200])
                session.clear()
                session["session_token"] = token
                session.permanent = True
                nxt = request.args.get("next") or "/admin"
                if not (nxt.startswith("/") and not nxt.startswith("//")
                        and not nxt.startswith("/login")
                        and not nxt.startswith("/logout")):
                    nxt = "/admin"
                return redirect(nxt)
            except AuthError as e:
                error = str(e)
        return _page(db, body=render_template_string(
            WEB_LOGIN_BODY, error=error))

    @app.route("/logout", methods=["POST"])
    def web_logout():
        token = session.pop("session_token", None)
        auth.logout(token)
        session.clear()
        return redirect(url_for("web_login"))

    @app.route("/admin")
    def admin_dashboard():
        user = g.web_user
        ad = db.get_active_fair_day()
        fair = db.get_fair(ad["fair_id"]) if ad else None
        stats = db.dashboard_stats(ad["fair_id"]) if ad else None
        recent = (db.search_contacts(fair_id=ad["fair_id"])[:20]
                  if ad else [])
        employees = db.list_employees()
        attendance = db.current_attendance(ad["fair_id"]) if ad else {}
        my_employee = db.get_employee_by_user_id(user["id"])
        perms = sorted(auth.permissions_for(user))
        return _page(db, body=render_template_string(
            WEB_ADMIN_BODY,
            username=user.get("display_name") or user["username"],
            is_admin=user.get("is_admin", False),
            perms=perms, fair=fair, fair_day=ad,
            stats=stats, recent=recent, employees=employees,
            attendance=attendance, my_employee=my_employee,
            can_create=auth.has(user, Perm.CREATE_DATA),
            can_manage=auth.has(user, Perm.EDIT_DATA),
        ))

    @app.route("/admin/my-token")
    def admin_my_token():
        user = g.web_user
        emp = db.get_employee_by_user_id(user["id"])
        if emp:
            return redirect(f"/scan/{emp['token']}")
        return redirect("/admin")

    @app.route("/admin/day/start", methods=["POST"])
    def admin_day_start():
        user = g.web_user
        if not auth.has(user, Perm.EDIT_DATA):
            return "Keine Berechtigung", 403
        if db.get_active_fair_day():
            return redirect("/admin")
        fairs = db.list_fairs()
        if not fairs:
            return redirect("/admin")
        try:
            db.start_fair_day(fairs[0]["id"])
        except Exception as e:
            logger.warning("Day start failed: %s", e)
        return redirect("/admin")

    @app.route("/admin/day/end", methods=["POST"])
    def admin_day_end():
        user = g.web_user
        if not auth.has(user, Perm.EDIT_DATA):
            return "Keine Berechtigung", 403
        ad = db.get_active_fair_day()
        if ad:
            try:
                db.end_fair_day(ad["id"])
            except Exception as e:
                logger.warning("Day end failed: %s", e)
        return redirect("/admin")

    @app.route("/admin/contact/add", methods=["POST"])
    def admin_contact_add():
        user = g.web_user
        if not auth.has(user, Perm.CREATE_DATA):
            return "Keine Berechtigung", 403
        ad = db.get_active_fair_day()
        if not ad:
            return redirect("/admin")
        name = request.form.get("name", "").strip()
        company = request.form.get("company", "").strip()
        position = request.form.get("position", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        notes = request.form.get("notes", "").strip()
        if not any([name, company, phone, email, notes]):
            return redirect("/admin")
        statuses = _statuses()
        status = statuses[0] if statuses else "Interessiert"
        emp = db.get_employee_by_user_id(user["id"])
        employee_id = emp["id"] if emp else None
        try:
            db.create_contact(
                fair_id=ad["fair_id"], source="Web",
                fair_day_id=ad["id"], employee_id=employee_id,
                name=name, company=company, position=position,
                phone=phone, email=email, status=status, notes=notes,
            )
        except Exception as e:
            logger.exception("Admin-Contact-Add fehlgeschlagen: %s", e)
        return redirect("/admin")

    @app.route("/scan/<token>")
    def scan_page(token):
        emp, err = _active_employee(db, token)
        if err:
            return err
        ad = db.get_active_fair_day()
        if not ad:
            return _page(db, emp=emp, token=token, body=(
                '<div class="warn">⚠️ <b>Aktuell läuft kein Messetag.</b>'
                '<br><br>Bitte wende dich an das Standpersonal.</div>'))
        att = db.current_attendance(ad["fair_id"]).get(emp["id"], {})
        is_present = att.get("event_type") == "enter"
        since_short = _fmt_dt(att.get("timestamp", "")) if att else ""
        msg_html = ""
        ok_flag = request.args.get("att_ok")
        if ok_flag == "enter":
            msg_html = '<div class="ok">✔ Du bist jetzt am Stand.</div>'
        elif ok_flag == "leave":
            msg_html = '<div class="ok">✔ Du hast den Stand verlassen.</div>'
        fair_name = _fair_name(ad["fair_id"])
        body = render_template_string(
            SCAN_BODY, token=token, statuses=_statuses(),
            req_id=uuid.uuid4().hex, fair_name=fair_name,
            fair_day=ad["day_date"], is_present=is_present,
            since_short=since_short, msg_html=msg_html)
        return _page(db, emp=emp, fair_name=fair_name, body=body,
                     token=token)

    @app.route("/api/<token>/bootstrap")
    def api_bootstrap(token):
        emp, err = _active_employee(db, token)
        if err:
            return (json.dumps({"error": "invalid_token"}),
                    404, {"Content-Type": "application/json"})
        ad = db.get_active_fair_day()
        fair = db.get_fair(ad["fair_id"]) if ad else None
        return (json.dumps({
            "employee": {"id": emp["id"], "name": emp["name"]},
            "fair": ({"id": fair["id"], "name": fair["name"]}
                     if fair else None),
            "fair_day": ({"id": ad["id"], "day_date": ad["day_date"]}
                         if ad else None),
            "statuses": _statuses(),
        }, ensure_ascii=False),
            200, {"Content-Type": "application/json"})

    @app.route("/api/<token>/submit", methods=["POST"])
    def api_submit(token):
        emp, err = _active_employee(db, token)
        if err:
            return err
        ad = db.get_active_fair_day()
        if not ad:
            return _error_page(db, emp, token,
                               "Kein aktiver Messetag."), 400
        name = request.form.get("name", "").strip()
        company = request.form.get("company", "").strip()
        position = request.form.get("position", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        website = request.form.get("website", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        status = request.form.get("status", "").strip()
        valid = _statuses()
        if status not in valid:
            status = valid[0] if valid else "Interessiert"
        file = request.files.get("image")
        has_photo = file is not None and file.filename != ""
        has_fields = any([name, company, position, phone, email,
                          website, address, notes])
        if not has_photo and not has_fields:
            return _error_page(db, emp, token,
                               "Bitte mindestens ein Feld ausfüllen "
                               "oder ein Foto hinzufügen.")
        req_id = _safe_req_id(request.form.get("request_id"))
        image_path = None
        if has_photo:
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                return _error_page(
                    db, emp, token,
                    "Dateityp nicht erlaubt."), 400
            ok, img_err = _validate_image(file)
            if not ok:
                return _error_page(db, emp, token,
                                   f"Kein gültiges Bild ({img_err})."), 400
            try:
                image_path = _save_upload(file, req_id)
            except Exception as e:
                return _error_page(db, emp, token,
                                   f"Foto-Fehler: {e}"), 500
        try:
            if has_fields and image_path:
                contact_id, _c, _cr = db.create_contact_with_card(
                    fair_id=ad["fair_id"], source="Smartphone",
                    employee_id=emp["id"], fair_day_id=ad["id"],
                    name=name, company=company, position=position,
                    phone=phone, email=email, status=status, notes=notes,
                    image_path=image_path, original_filename=file.filename,
                    external_id=req_id)
                _store_extras(contact_id, address, website)
                return _page(db, emp=emp, token=token, body=(
                    '<div class="ok">✔ Kontakt gespeichert (mit Foto).</div>'
                    f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))
            if image_path:
                card, created = db.enqueue_card(
                    fair_id=ad["fair_id"], image_path=image_path,
                    fair_day_id=ad["id"], employee_id=emp["id"],
                    original_filename=file.filename, external_id=req_id)
                msg = (f'✔ Visitenkarte (ID {card["id"]}).'
                       if created else
                       f'✔ Karte vorhanden (ID {card["id"]}).')
                return _page(db, emp=emp, token=token, body=(
                    f'<div class="ok">{msg}</div>'
                    f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))
            contact_id = db.create_contact(
                fair_id=ad["fair_id"], source="Smartphone",
                employee_id=emp["id"], fair_day_id=ad["id"],
                name=name, company=company, position=position,
                phone=phone, email=email, status=status, notes=notes,
                external_id=req_id)
            _store_extras(contact_id, address, website)
            return _page(db, emp=emp, token=token, body=(
                '<div class="ok">✔ Kontakt gespeichert.</div>'
                f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))
        except Exception as e:
            logger.exception("Submit-Fehler: %s", e)
            return _error_page(db, emp, token,
                               f"Fehler: {e}"), 500

    @app.route("/api/<token>/sync", methods=["POST"])
    def api_sync(token):
        emp, err = _active_employee(db, token)
        if err:
            _page_, code = err
            return (json.dumps({"status": "error",
                                "message": "Token ungültig."}),
                    code, {"Content-Type": "application/json"})
        ad = db.get_active_fair_day()
        if not ad:
            return (json.dumps({"status": "error",
                                "message": "Kein aktiver Messetag."}),
                    400, {"Content-Type": "application/json"})
        req_id = _safe_req_id(request.form.get("request_id"))
        if not req_id:
            return (json.dumps({"status": "error",
                                "message": "request_id fehlt."}),
                    400, {"Content-Type": "application/json"})
        with db._lock:
            existing_contact = db.conn.execute(
                "SELECT id FROM contacts WHERE external_id=?",
                (req_id,)).fetchone()
            existing_card = db.conn.execute(
                "SELECT id FROM card_queue WHERE external_id=?",
                (req_id,)).fetchone()
        if existing_contact or existing_card:
            return (json.dumps({
                "status": "duplicate",
                "contact_id": existing_contact["id"]
                              if existing_contact else None,
                "card_id": existing_card["id"] if existing_card else None,
            }), 200, {"Content-Type": "application/json"})
        name = request.form.get("name", "").strip()
        company = request.form.get("company", "").strip()
        position = request.form.get("position", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        website = request.form.get("website", "").strip()
        address = request.form.get("address", "").strip()
        notes = request.form.get("notes", "").strip()
        status = request.form.get("status", "").strip()
        valid = _statuses()
        if status not in valid:
            status = valid[0] if valid else "Interessiert"
        file = request.files.get("image")
        has_photo = file is not None and file.filename != ""
        has_fields = any([name, company, position, phone, email,
                          website, address, notes])
        if not has_photo and not has_fields:
            return (json.dumps({"status": "error",
                                "message": "Leerer Eintrag."}),
                    400, {"Content-Type": "application/json"})
        image_path = None
        if has_photo:
            try:
                image_path = _save_upload(file, req_id)
            except Exception as e:
                return (json.dumps({"status": "error",
                                    "message": f"Bild: {e}"}),
                        500, {"Content-Type": "application/json"})
        try:
            import sqlite3 as _sq
            try:
                if has_fields and image_path:
                    contact_id, _c, _cr = db.create_contact_with_card(
                        fair_id=ad["fair_id"], source="Smartphone",
                        employee_id=emp["id"], fair_day_id=ad["id"],
                        name=name, company=company, position=position,
                        phone=phone, email=email, status=status,
                        notes=notes, image_path=image_path,
                        original_filename=file.filename,
                        external_id=req_id)
                    _store_extras(contact_id, address, website)
                    return (json.dumps({"status": "synced",
                                        "contact_id": contact_id}),
                            200, {"Content-Type": "application/json"})
                if image_path:
                    card, _cr = db.enqueue_card(
                        fair_id=ad["fair_id"], image_path=image_path,
                        fair_day_id=ad["id"], employee_id=emp["id"],
                        original_filename=file.filename,
                        external_id=req_id)
                    return (json.dumps({"status": "synced",
                                        "card_id": card["id"]}),
                            200, {"Content-Type": "application/json"})
                contact_id = db.create_contact(
                    fair_id=ad["fair_id"], source="Smartphone",
                    employee_id=emp["id"], fair_day_id=ad["id"],
                    name=name, company=company, position=position,
                    phone=phone, email=email, status=status, notes=notes,
                    external_id=req_id)
                _store_extras(contact_id, address, website)
                return (json.dumps({"status": "synced",
                                    "contact_id": contact_id}),
                        200, {"Content-Type": "application/json"})
            except _sq.IntegrityError:
                with db._lock:
                    existing = db.conn.execute(
                        "SELECT id FROM contacts WHERE external_id=?",
                        (req_id,)).fetchone()
                return (json.dumps({
                    "status": "duplicate",
                    "contact_id": existing["id"] if existing else None,
                }), 200, {"Content-Type": "application/json"})
        except Exception as e:
            logger.exception("Sync-Fehler: %s", e)
            return (json.dumps({"status": "error", "message": str(e)}),
                    500, {"Content-Type": "application/json"})

    @app.route("/api/<token>/attendance", methods=["POST"])
    def api_attendance(token):
        emp, err = _active_employee(db, token)
        if err:
            return err
        ad = db.get_active_fair_day()
        if not ad:
            return _error_page(db, emp, token,
                               "Kein aktiver Messetag."), 400
        et = request.form.get("event_type")
        if et not in ("enter", "leave"):
            return _error_page(db, emp, token,
                               "Ungültiger Ereignistyp."), 400
        try:
            _nid, changed = db.add_attendance(
                emp["id"], ad["fair_id"], et, "Smartphone",
                fair_day_id=ad["id"])
        except Exception as e:
            return _error_page(db, emp, token, f"Fehler: {e}"), 500
        if changed:
            return redirect(url_for("scan_page", token=token, att_ok=et))
        return redirect(url_for("scan_page", token=token))

    @app.route("/static/<path:filename>")
    def _static_files(filename):
        return send_from_directory(str(STATIC_DIR), filename)

    return app


def start_server(db):
    app = create_app(db)

    def _run():
        try:
            ssl_context = None
            if (SSL_CERT_FILE and SSL_KEY_FILE
                    and Path(SSL_CERT_FILE).exists()
                    and Path(SSL_KEY_FILE).exists()):
                ssl_context = (str(SSL_CERT_FILE), str(SSL_KEY_FILE))
                logger.info("HTTPS aktiv: %s", SSL_CERT_FILE)
            else:
                logger.warning("Kein SSL-Zertifikat – ohne HTTPS.")
            app.run(host=WEB_HOST, port=WEB_PORT, threaded=True,
                    use_reloader=False, debug=False,
                    ssl_context=ssl_context)
        except Exception as e:
            print(f"[WEB SERVER] Fehler beim Start: {e}")
            logger.exception("Webserver-Start fehlgeschlagen.")

    t = threading.Thread(target=_run, daemon=True, name="FlaskServer")
    t.start()
    return t