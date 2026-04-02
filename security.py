"""
SECURITY.PY — Capa de seguridad completa para NEME BET
═════════════════════════════════════════════════════
Rate limiting, encryption, monitoring, backups, honeypot.
"""

import json
import os
import time
import zipfile
import logging
import secrets
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECURITY_LOG = os.path.join(BASE_DIR, "security.log")
ERROR_LOG = os.path.join(BASE_DIR, "error.log")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BLOCKED_IPS_PATH = os.path.join(BASE_DIR, "blocked_ips.json")

os.makedirs(BACKUP_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════

sec_logger = logging.getLogger("security")
sec_handler = logging.FileHandler(SECURITY_LOG)
sec_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
sec_logger.addHandler(sec_handler)
sec_logger.setLevel(logging.INFO)

err_logger = logging.getLogger("errors")
err_handler = logging.FileHandler(ERROR_LOG)
err_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
err_logger.addHandler(err_handler)
err_logger.setLevel(logging.ERROR)

# Error counter for alert threshold
_error_times = []


def log_security(event, ip="", details=""):
    sec_logger.info(f"{event} | IP={ip} | {details}")


def log_error(error, context=""):
    err_logger.error(f"{error} | {context}")
    _error_times.append(time.time())
    # Clean old entries
    cutoff = time.time() - 600  # 10 minutes
    _error_times[:] = [t for t in _error_times if t > cutoff]
    if len(_error_times) > 5:
        _alert_admin(f"NEME BET: {len(_error_times)} errores en 10 min")


def _alert_admin(message):
    try:
        from email_service import _send
        _send("swatfest2026@gmail.com", "ALERTA NEME BET", f"""
        <div style="font-family:sans-serif;background:#0A0A0A;color:#FF4757;padding:20px;border-radius:12px">
            <h2>Alerta de seguridad</h2>
            <p>{message}</p>
            <p style="color:#888;font-size:12px">{datetime.now().isoformat()}</p>
        </div>""")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  IP BLOCKING (login brute force)
# ═══════════════════════════════════════════════════════════════════════════

_login_attempts = defaultdict(list)  # ip -> [timestamps]


def _load_blocked():
    if os.path.exists(BLOCKED_IPS_PATH):
        try:
            with open(BLOCKED_IPS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_blocked(blocked):
    with open(BLOCKED_IPS_PATH, "w", encoding="utf-8") as f:
        json.dump(blocked, f, indent=2)


def record_failed_login(ip):
    now = time.time()
    _login_attempts[ip].append(now)
    # Keep last 30 minutes only
    _login_attempts[ip] = [t for t in _login_attempts[ip] if t > now - 1800]

    log_security("FAILED_LOGIN", ip, f"Attempts: {len(_login_attempts[ip])}")

    if len(_login_attempts[ip]) >= 10:
        blocked = _load_blocked()
        blocked[ip] = {
            "blocked_at": datetime.now().isoformat(),
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
            "reason": "10+ failed login attempts",
        }
        _save_blocked(blocked)
        log_security("IP_BLOCKED", ip, "10+ failed logins -> 1h block")
        _login_attempts[ip] = []


def is_ip_blocked(ip):
    blocked = _load_blocked()
    entry = blocked.get(ip)
    if not entry:
        return False
    expires = entry.get("expires", "")
    if expires and datetime.fromisoformat(expires) < datetime.now():
        del blocked[ip]
        _save_blocked(blocked)
        return False
    return True


def record_successful_login(ip, email):
    _login_attempts.pop(ip, None)
    log_security("LOGIN_OK", ip, f"email={email}")


# ═══════════════════════════════════════════════════════════════════════════
#  HONEYPOT
# ═══════════════════════════════════════════════════════════════════════════

def check_honeypot(form_data):
    """Returns True if honeypot was triggered (is a bot)."""
    hp_value = form_data.get("website_url", "")  # Hidden field
    if hp_value:
        ip = "unknown"
        log_security("HONEYPOT_TRIGGERED", ip, f"value={hp_value[:50]}")
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  INPUT SANITIZATION
# ═══════════════════════════════════════════════════════════════════════════

def sanitize(text, max_length=500):
    """Sanitize user input: strip tags, limit length."""
    if not text:
        return ""
    import re
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(text))
    # Remove null bytes
    clean = clean.replace('\x00', '')
    # Limit length
    clean = clean[:max_length].strip()
    return clean


# ═══════════════════════════════════════════════════════════════════════════
#  DATA ENCRYPTION (users.json)
# ═══════════════════════════════════════════════════════════════════════════

def _get_fernet():
    from cryptography.fernet import Fernet
    key_path = os.path.join(BASE_DIR, ".fernet_key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        with open(key_path, "wb") as f:
            f.write(key)
    return Fernet(key)


def encrypt_file(path):
    """Encrypt a JSON file in place."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "rb") as f:
            data = f.read()
        if data.startswith(b"gAAAAA"):  # Already encrypted
            return
        fernet = _get_fernet()
        encrypted = fernet.encrypt(data)
        with open(path, "wb") as f:
            f.write(encrypted)
    except Exception as e:
        log_error(f"Encryption failed: {e}", path)


def decrypt_file(path):
    """Decrypt a file and return content as string."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(b"gAAAAA"):  # Not encrypted, return as-is
            return data.decode("utf-8")
        fernet = _get_fernet()
        return fernet.decrypt(data).decode("utf-8")
    except Exception as e:
        log_error(f"Decryption failed: {e}", path)
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  BACKUPS
# ═══════════════════════════════════════════════════════════════════════════

FILES_TO_BACKUP = [
    "users.json", "results_db.json", "picks_del_dia.json",
    "calibration.json", "learned_weights.json", "resultados.json",
]


def create_backup():
    """Create daily backup of critical data files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    zip_name = f"backup_{timestamp}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_name)

    backed_up = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in FILES_TO_BACKUP:
            fpath = os.path.join(BASE_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, fname)
                backed_up += 1

    log_security("BACKUP_CREATED", details=f"{zip_name} ({backed_up} files)")

    # Keep only last 7 backups
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_")])
    while len(backups) > 7:
        oldest = backups.pop(0)
        os.remove(os.path.join(BACKUP_DIR, oldest))
        log_security("BACKUP_DELETED", details=f"Old: {oldest}")

    return zip_path


def restore_latest():
    """Restore from latest backup if data corruption detected."""
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_")])
    if not backups:
        return False

    latest = os.path.join(BACKUP_DIR, backups[-1])
    with zipfile.ZipFile(latest, "r") as zf:
        zf.extractall(BASE_DIR)

    log_security("BACKUP_RESTORED", details=backups[-1])
    return True


def verify_data_integrity():
    """Check if critical files are valid JSON."""
    corrupted = []
    for fname in FILES_TO_BACKUP:
        fpath = os.path.join(BASE_DIR, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, Exception):
            corrupted.append(fname)
            log_error(f"Data corruption: {fname}")

    if corrupted:
        log_security("CORRUPTION_DETECTED", details=str(corrupted))
        restore_latest()

    return corrupted


# ═══════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════

def get_health_status():
    """Comprehensive health check of all modules."""
    status = {"status": "ok", "timestamp": datetime.now().isoformat(), "modules": {}}

    # App
    status["modules"]["flask"] = "ok"

    # Data files
    for fname in ["resultados.json", "results_db.json", "picks_del_dia.json"]:
        fpath = os.path.join(BASE_DIR, fname)
        status["modules"][fname] = "ok" if os.path.exists(fpath) else "missing"

    # Stripe
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    status["modules"]["stripe"] = "configured" if stripe_key else "not_configured"

    # Football API
    fd_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    status["modules"]["football_data"] = "configured" if fd_key else "not_configured"

    # Backups
    backups = [f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_")] if os.path.exists(BACKUP_DIR) else []
    status["modules"]["backups"] = f"{len(backups)} available"

    # Errors
    recent_errors = len([t for t in _error_times if t > time.time() - 3600])
    status["modules"]["errors_1h"] = recent_errors
    if recent_errors > 5:
        status["status"] = "degraded"

    return status


# ═══════════════════════════════════════════════════════════════════════════
#  FLASK INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

def init_security(app):
    """Initialize security middleware on Flask app."""

    # Rate limiting
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(
            get_remote_address,
            app=app,
            default_limits=["100 per minute"],
            storage_uri="memory://",
        )
        # Stricter limit on login
        limiter.limit("10 per minute")(app.view_functions.get("login_page", lambda: None))
        print("[SECURITY] Rate limiter active")
    except ImportError:
        print("[SECURITY] flask-limiter not available")

    # Security headers
    try:
        from flask_talisman import Talisman
        csp = {
            'default-src': "'self'",
            'script-src': "'self' 'unsafe-inline' https://js.stripe.com",
            'style-src': "'self' 'unsafe-inline'",
            'img-src': "'self' data: https:",
            'connect-src': "'self' https://api.stripe.com",
            'frame-src': "https://js.stripe.com https://hooks.stripe.com",
        }
        Talisman(app, content_security_policy=csp,
                 force_https=False,  # Railway handles HTTPS
                 session_cookie_secure=True,
                 session_cookie_http_only=True)
        print("[SECURITY] Talisman headers active")
    except ImportError:
        print("[SECURITY] flask-talisman not available")

    # Error handler
    @app.errorhandler(Exception)
    def handle_error(e):
        log_error(str(e), "unhandled_exception")
        from flask import render_template_string
        return render_template_string(
            '<div style="background:#0A0A0A;color:#FF4757;padding:40px;text-align:center;font-family:sans-serif">'
            '<h1>Error</h1><p>Algo salio mal. Intenta de nuevo.</p>'
            '<a href="/" style="color:#1AE89B">Volver al inicio</a></div>'
        ), 500

    # Request logging
    @app.before_request
    def before_req():
        from flask import request as req
        ip = req.headers.get("X-Forwarded-For", req.remote_addr or "")
        if "," in ip:
            ip = ip.split(",")[0].strip()
        if is_ip_blocked(ip):
            from flask import abort
            abort(403)

    print("[SECURITY] Security layer initialized")
