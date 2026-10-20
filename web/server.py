"""Lokaler Flask-Server für Smartphone-Anbindung."""
import io
import json
import logging
import threading
import uuid
from datetime import timedelta
from pathlib import Path

from flask import (Flask, g, request, render_template_string, redirect,
                   url_for, session)
from markupsafe import escape
from PIL import Image

from config import (
    WEB_HOST, WEB_PORT, CARDS_DIR, ALLOWED_IMAGE_EXTENSIONS, MAX_UPLOAD_MB,
    MAX_IMAGE_PIXELS, MAX_IMAGE_DIMENSION, IMAGE_JPEG_QUALITY,
)
from core.auth import AuthService, AuthError
from core.contact_extras import set_contact_extras
from ui.themes import get_theme, build_web_css

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

logger = logging.getLogger(__name__)


BASE_HTML = """
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Messe Tracker Pro</title>
  <style>{{ web_css|safe }}
    .modal-backdrop{
      position:fixed;inset:0;background:rgba(0,0,0,.72);
      display:none;align-items:center;justify-content:center;
      z-index:1000;padding:20px;
      -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
    }
    .modal-backdrop.open{display:flex}
    .modal{
      background:var(--bg-panel);color:var(--fg-text);
      border:1px solid var(--accent);border-radius:14px;
      padding:22px 20px;max-width:360px;width:100%;
      box-shadow:0 20px 50px rgba(0,0,0,.6);
      animation:pop .15s ease-out;
    }
    @keyframes pop{from{transform:scale(.92);opacity:0}to{transform:scale(1);opacity:1}}
    .modal p{font-size:1.1em;margin:0 0 18px;text-align:center;line-height:1.4}
    .modal .modal-actions{display:flex;gap:10px}
    .modal .modal-actions button{flex:1;margin:0;padding:12px}
    .modal .modal-actions button.alt{
      background:var(--bg-input);color:var(--fg-text);border:1px solid var(--border);
    }
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

  <script>
    let _pendingForm = null;
    function showConfirm(form, text){
      _pendingForm = form;
      document.getElementById('modal-text').textContent = text;
      const bd = document.getElementById('modal-backdrop');
      bd.classList.add('open');
      document.body.style.overflow = 'hidden';
      return false;
    }
    function hideModal(){
      document.getElementById('modal-backdrop').classList.remove('open');
      document.body.style.overflow = '';
      _pendingForm = null;
    }
    function doConfirm(){
      const f = _pendingForm;
      hideModal();
      if (f) f.submit();
    }
    document.addEventListener('keydown', function(e){
      if (e.key === 'Escape') hideModal();
    });
  </script>

  <script>
  // ============================================================
  // Offline-Warteschlange (localStorage) + automatischer Sync
  // ============================================================
  (function(){
    const TOKEN = "{{ token or '' }}";
    const PENDING_PREFIX = 'mt_pending_';
    if (!TOKEN) return;

    function listPending(){
      return Object.keys(localStorage)
        .filter(k => k.startsWith(PENDING_PREFIX))
        .map(k => ({key:k, data:JSON.parse(localStorage.getItem(k)||'{}')}));
    }

    function updateBanner(){
      let banner = document.getElementById('sync-banner');
      if (!banner){
        banner = document.createElement('div');
        banner.id = 'sync-banner';
        banner.style.cssText = 'position:sticky;top:0;z-index:20;padding:8px 12px;' +
          'font-size:.9em;text-align:center;border-bottom:2px solid #000;';
        document.body.insertBefore(banner, document.body.firstChild);
      }
      const pending = listPending().length;
      const online = navigator.onLine;
      if (pending > 0){
        banner.style.background = online ? '#063' : '#430';
        banner.style.color = '#fff';
        banner.textContent = `⏳ ${pending} lokal gespeicherte(r) Eintrag/Einträge – ` +
          (online ? 'wird synchronisiert…' : 'offline – wird übertragen, sobald Verbindung besteht.');
      } else if (online) {
        banner.style.background = '#0a2a3a';
        banner.style.color = '#9fd';
        banner.textContent = '✅ Alle Einträge synchronisiert.';
        setTimeout(() => { if (banner && banner.parentNode) banner.remove(); }, 4000);
      } else {
        banner.style.background = '#430';
        banner.style.color = '#fc9';
        banner.textContent = '📡 Offline – neue Einträge werden lokal gespeichert.';
      }
    }

    async function tryFlush(){
      const pending = listPending();
      if (pending.length === 0){ updateBanner(); return; }
      for (const {key, data} of pending){
        try {
          const fd = new FormData();
          for (const [k, v] of Object.entries(data.fields)) fd.append(k, v);
          if (data.image && data.image.dataUrl){
            const blob = await (await fetch(data.image.dataUrl)).blob();
            fd.append('image', blob, data.image.name || 'card.jpg');
          }
          const resp = await fetch('/api/' + TOKEN + '/sync', {
            method:'POST', body: fd
          });
          if (resp.ok){
            const json = await resp.json().catch(()=>({status:'synced'}));
            if (json.status === 'synced' || json.status === 'duplicate'){
              localStorage.removeItem(key);
            } else {
              localStorage.setItem(key, JSON.stringify(Object.assign(data,{
                attempts:(data.attempts||0)+1,
                last_error: json.message || 'Serverfehler'})));
            }
          }
        } catch(e){ /* Netzwerkfehler → Eintrag bleibt */ }
      }
      updateBanner();
    }

    document.addEventListener('submit', async (ev) => {
      const form = ev.target;
      if (!form.action || !form.action.includes('/api/' + TOKEN + '/submit')) return;
      ev.preventDefault();
      const formData = new FormData(form);
      const fields = {};
      let image = null;
      for (const [k, v] of formData.entries()){
        if (v instanceof File){
          if (v.size > 0){
            const dataUrl = await new Promise(res => {
              const fr = new FileReader();
              fr.onload = () => res(fr.result);
              fr.readAsDataURL(v);
            });
            image = {name: v.name, dataUrl};
          }
        } else { fields[k] = v; }
      }
      if (!fields.request_id){
        fields.request_id = 'off_' + Math.random().toString(36).slice(2) + Date.now();
      }
      const entry = {fields, image, attempts: 0, savedAt: Date.now()};
      localStorage.setItem(PENDING_PREFIX + fields.request_id, JSON.stringify(entry));
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
    updateBanner();
    tryFlush();
  })();
  </script>
</body>
</html>
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
  <h3>👋 Willkommen, {{ username }}{% if is_admin %} (Administrator){% endif %}</h3>
  <p>Dies ist die geschützte Weboberfläche. Die vollständige
     Admin-Funktionalität folgt in einer späteren Phase.</p>
</div>
<div class="card">
  <h3>Deine Berechtigungen</h3>
  <ul style="margin:0 0 8px 18px;padding:0;color:var(--fg-muted);">
    {% for p in perms %}<li><code>{{ p }}</code></li>{% endfor %}
  </ul>
  <form method="post" action="/logout" style="margin-top:16px;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="alt">Abmelden</button>
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
  <p>Dein Zugang wurde deaktiviert. Du kannst aktuell keine
     Kontakte erfassen oder deinen Anwesenheitsstatus ändern.</p>
  <p>Bitte wende dich an die Standverantwortlichen am Haupt-Laptop.</p>
</div>
"""


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
    target = CARDS_DIR / f"{req_id}.jpg"
    if target.exists():
        return str(target)

    file_storage.stream.seek(0)
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except Exception as e:
        raise ValueError(f"Bild nicht lesbar: {e}")

    try:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and
                                          "transparency" in img.info):
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

    tmp = CARDS_DIR / f".{req_id}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        img.save(tmp, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
        import os
        os.replace(tmp, target)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Bild konnte nicht gespeichert werden: {e}")

    return str(target)


def create_app(db):
    app = Flask(__name__)
    app.secret_key = (
        db.get_setting("web_secret_key") or uuid.uuid4().hex
    )
    logger.info("Flask secret_key-Quelle: %s",
                "DB" if db.get_setting("web_secret_key") else "random (Fallback!)")
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
                or request.path.startswith("/api/")
                or request.path.startswith("/static/")):
            return None
        if request.path in ("/", "/login"):
            return None
        if request.path.startswith("/admin") or request.path == "/logout":
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
                logger.warning(
                    "CSRF-Fehler: path=%s session_token=%r form_token=%r",
                    request.path, token, form_token,
                )
                return (
                    '<div class="err" style="margin:20px;padding:16px;'
                    'border-radius:10px;background:#a30;color:#fff;">'
                    '<b>CSRF-Token ungültig oder abgelaufen.</b><br>'
                    'Bitte lade die Seite neu und versuche es erneut.'
                    '</div>',
                    400,
                )
        return None

    def _active_fair_day():
        return db.get_active_fair_day()

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
            logger.exception("Adresse/Webseite konnten nicht gespeichert "
                             "werden (contact_id=%s)", contact_id)

    @app.route("/")
    def index():
        return _page(db, body=(
            '<div class="card"><h3>Messe Tracker Pro</h3>'
            '<p>Bitte scanne den persönlichen QR-Code deines Mitarbeiters.'
            '</p>'
            '<p style="margin-top:14px;">'
            '<a href="/login" class="link">→ Admin-Login</a></p>'
            '</div>'))

    @app.route("/login", methods=["GET", "POST"])
    def web_login():
        error = ""
        if request.method == "POST":
            try:
                user, token = auth.login(
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    ip=request.remote_addr or "",
                    user_agent=(request.headers.get("User-Agent", "") or "")[:200])
                session.clear()
                session["session_token"] = token
                session.permanent = True

                nxt = request.args.get("next") or "/admin"
                if not (nxt.startswith("/")
                        and not nxt.startswith("//")
                        and not nxt.startswith("/login")
                        and not nxt.startswith("/logout")):
                    nxt = "/admin"
                return redirect(nxt)
            except AuthError as e:
                error = str(e)
                logger.info("Web-Login fehlgeschlagen: %s", e)

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
        perms = sorted(auth.permissions_for(g.web_user))
        return _page(db, body=render_template_string(
            WEB_ADMIN_BODY,
            username=g.web_user["username"],
            is_admin=g.web_user.get("is_admin", False),
            perms=perms))

    @app.route("/scan/<token>")
    def scan_page(token):
        emp, err = _active_employee(db, token)
        if err:
            return err

        ad = _active_fair_day()
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
        return _page(db, emp=emp, fair_name=fair_name, body=body, token=token)

    @app.route("/api/<token>/submit", methods=["POST"])
    def api_submit(token):
        emp, err = _active_employee(db, token)
        if err:
            return err

        ad = _active_fair_day()
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

        image_path = None
        req_id = request.form.get("request_id") or uuid.uuid4().hex
        if has_photo:
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                return _error_page(db, emp, token,
                                   "Dateityp nicht erlaubt. Erlaubt sind: "
                                   f"{', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}."), 400
            ok, img_err = _validate_image(file)
            if not ok:
                return _error_page(db, emp, token,
                                   f"Die hochgeladene Datei ist kein gültiges "
                                   f"Bild ({img_err})."), 400
            try:
                image_path = _save_upload(file, req_id)
            except Exception as e:
                return _error_page(db, emp, token,
                                   f"Foto konnte nicht gespeichert werden: {e}"), 500

        if has_fields and image_path:
            try:
                contact_id, card, created = db.create_contact_with_card(
                    fair_id=ad["fair_id"], source="Smartphone",
                    employee_id=emp["id"], fair_day_id=ad["id"],
                    name=name, company=company, position=position,
                    phone=phone, email=email, status=status, notes=notes,
                    image_path=image_path,
                    original_filename=file.filename,
                    external_id=req_id)
            except Exception as e:
                return _error_page(db, emp, token,
                                   f"Speichern fehlgeschlagen: {e}"), 500

            _store_extras(contact_id, address, website)
            return _page(db, emp=emp, token=token, body=(
                '<div class="ok">✔ Kontakt gespeichert (mit Foto).</div>'
                f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))

        if image_path:
            try:
                card, created = db.enqueue_card(
                    fair_id=ad["fair_id"], image_path=image_path,
                    fair_day_id=ad["id"], employee_id=emp["id"],
                    original_filename=file.filename, external_id=req_id)
            except Exception as e:
                return _error_page(db, emp, token,
                                   f"Foto konnte nicht gespeichert werden: {e}"), 500

            if created:
                msg = (f'✔ Visitenkarte in Warteschlange '
                       f'(ID {card["id"]}). Sie wird am Laptop erkannt '
                       f'und geprüft.')
            else:
                msg = f'✔ Karte war bereits vorhanden (ID {card["id"]}).'
            return _page(db, emp=emp, token=token, body=(
                f'<div class="ok">{msg}</div>'
                f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))

        try:
            contact_id = db.create_contact(
                fair_id=ad["fair_id"], source="Smartphone",
                employee_id=emp["id"], fair_day_id=ad["id"],
                name=name, company=company, position=position,
                phone=phone, email=email, status=status, notes=notes,
                external_id=req_id)
        except Exception as e:
            return _error_page(db, emp, token,
                               f"Speichern fehlgeschlagen: {e}"), 500

        _store_extras(contact_id, address, website)
        return _page(db, emp=emp, token=token, body=(
            '<div class="ok">✔ Kontakt gespeichert.</div>'
            f'<p><a href="/scan/{token}" class="link">← Zurück</a></p>'))

    @app.route("/api/<token>/sync", methods=["POST"])
    def api_sync(token):
        """Idempotenter JSON-Endpunkt für die Offline-Warteschlange."""
        emp, err = _active_employee(db, token)
        if err:
            page, code = err
            return (json.dumps({"status": "error",
                                "message": "Token ungültig."}),
                    code, {"Content-Type": "application/json"})

        ad = _active_fair_day()
        if not ad:
            return (json.dumps({"status": "error",
                                "message": "Kein aktiver Messetag."}),
                    400, {"Content-Type": "application/json"})

        req_id = (request.form.get("request_id") or "").strip()
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
                "card_id": existing_card["id"]
                           if existing_card else None,
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
            if has_fields and image_path:
                contact_id, _card, _created = db.create_contact_with_card(
                    fair_id=ad["fair_id"], source="Smartphone",
                    employee_id=emp["id"], fair_day_id=ad["id"],
                    name=name, company=company, position=position,
                    phone=phone, email=email, status=status, notes=notes,
                    image_path=image_path,
                    original_filename=file.filename, external_id=req_id)
                _store_extras(contact_id, address, website)
                return (json.dumps({"status": "synced",
                                    "contact_id": contact_id}),
                        200, {"Content-Type": "application/json"})

            if image_path:
                card, _created = db.enqueue_card(
                    fair_id=ad["fair_id"], image_path=image_path,
                    fair_day_id=ad["id"], employee_id=emp["id"],
                    original_filename=file.filename, external_id=req_id)
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
        except Exception as e:
            logger.exception("Sync-Fehler: %s", e)
            return (json.dumps({"status": "error",
                                "message": str(e)}),
                    500, {"Content-Type": "application/json"})

    @app.route("/api/<token>/attendance", methods=["POST"])
    def api_attendance(token):
        emp, err = _active_employee(db, token)
        if err:
            return err

        ad = _active_fair_day()
        if not ad:
            return _error_page(db, emp, token,
                               "Kein aktiver Messetag."), 400

        et = request.form.get("event_type")
        if et not in ("enter", "leave"):
            logger.warning("Ungültiger event_type=%r von Token %s…",
                           et, token[:8])
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

    return app


def start_server(db):
    app = create_app(db)

    def _run():
        try:
            app.run(host=WEB_HOST, port=WEB_PORT, threaded=True,
                    use_reloader=False, debug=False)
        except Exception as e:
            print(f"[WEB SERVER] Fehler beim Start: {e}")

    t = threading.Thread(target=_run, daemon=True, name="FlaskServer")
    t.start()
    return t