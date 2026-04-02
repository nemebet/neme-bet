"""
SESSION_GUARD.PY — Anti-comparticion de cuenta para NEME BET
═══════════════════════════════════════════════════════════
Sesion unica, deteccion de ubicaciones, limite de dispositivos.
"""

import json
import os
import secrets
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from data_dir import data_path
from stripe_handler import _load_users, _save_users, PLANS

SHARING_LOG_PATH = data_path("sharing_log.json")


def get_location_from_ip(ip):
    """Obtiene ubicacion aproximada de una IP via ip-api.com (gratis)."""
    if not ip or ip in ("127.0.0.1", "localhost", ""):
        return "Local"
    try:
        # Clean forwarded IPs
        if "," in ip:
            ip = ip.split(",")[0].strip()
        url = f"http://ip-api.com/json/{ip}?fields=city,country,countryCode"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            city = data.get("city", "")
            country = data.get("country", "")
            return f"{city}, {country}" if city else country or "Desconocida"
    except Exception:
        return "Desconocida"


def get_client_ip(request):
    """Extrae IP real del request (soporta proxies/Railway)."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    if "," in ip:
        ip = ip.split(",")[0].strip()
    return ip


def get_device_name(user_agent):
    """Extrae nombre amigable del dispositivo."""
    ua = (user_agent or "").lower()
    if "iphone" in ua: return "iPhone"
    if "ipad" in ua: return "iPad"
    if "android" in ua:
        if "mobile" in ua: return "Android (movil)"
        return "Android (tablet)"
    if "windows" in ua: return "Windows PC"
    if "macintosh" in ua: return "Mac"
    if "linux" in ua: return "Linux PC"
    return "Navegador web"


def get_max_devices(plan, user=None):
    """Limite de dispositivos por plan. Admin = sin limite."""
    if user and user.get("max_devices_override"):
        return user["max_devices_override"]
    if plan == "vip":
        return 2
    return 1


# ═══════════════════════════════════════════════════════════════
#  SESSION MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def create_session(email, request):
    """Crea nueva sesion. Invalida anteriores si excede limite."""
    users = _load_users()
    token_key = None
    user = None

    for tk, u in users.items():
        if u.get("email", "").lower() == email.lower():
            token_key = tk
            user = u
            break

    if not user:
        return None, "Usuario no encontrado"

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    location = get_location_from_ip(ip)
    device = get_device_name(ua)
    plan = user.get("plan", "free_trial")
    max_devices = get_max_devices(plan, user)

    # New session token
    new_session = secrets.token_urlsafe(32)

    # Current active sessions
    sessions = user.get("active_sessions", [])

    # Check for suspicious location change (skip for admin)
    suspicious = False
    if sessions and not user.get("skip_location_check"):
        last = sessions[-1]
        last_country = last.get("location", "").split(",")[-1].strip()
        current_country = location.split(",")[-1].strip()
        last_time = last.get("created", "")

        if last_country and current_country and last_country != current_country:
            if last_time:
                try:
                    dt = datetime.fromisoformat(last_time)
                    if (datetime.now() - dt).total_seconds() < 3600:
                        suspicious = True
                        _log_sharing(email, "SUSPICIOUS_LOCATION",
                                     f"{last_country} -> {current_country} in <1h")
                except Exception:
                    pass

    # Build new session entry
    session_entry = {
        "session_token": new_session,
        "ip": ip,
        "device": device,
        "location": location,
        "user_agent": ua[:100],
        "created": datetime.now().isoformat(),
        "last_active": datetime.now().isoformat(),
    }

    # Enforce device limit: keep only latest (max_devices - 1), add new
    if len(sessions) >= max_devices:
        # Remove oldest sessions
        sessions = sessions[-(max_devices - 1):]

    sessions.append(session_entry)

    user["active_sessions"] = sessions
    user["session_token"] = new_session
    user["ultimo_login"] = datetime.now().isoformat()
    user["ultima_ip"] = ip
    user["ultimo_dispositivo"] = device
    user["ubicacion"] = location

    users[token_key] = user
    _save_users(users)

    # Send alert if suspicious
    if suspicious:
        _send_location_alert(email, location)

    return new_session, None


def validate_session(email, session_token):
    """Verifica que la sesion sea valida y activa."""
    if not email or not session_token:
        return False, None

    users = _load_users()
    for tk, user in users.items():
        if user.get("email", "").lower() != email.lower():
            continue

        sessions = user.get("active_sessions", [])

        # Check if this session_token exists in active sessions
        for s in sessions:
            if s.get("session_token") == session_token:
                # Update last_active
                s["last_active"] = datetime.now().isoformat()
                users[tk] = user
                _save_users(users)
                return True, user

        # Session not found = was invalidated
        return False, None

    return False, None


def close_session(email, session_token=None):
    """Cierra una sesion especifica o todas."""
    users = _load_users()
    for tk, user in users.items():
        if user.get("email", "").lower() != email.lower():
            continue

        if session_token:
            # Close specific session
            user["active_sessions"] = [
                s for s in user.get("active_sessions", [])
                if s.get("session_token") != session_token
            ]
        else:
            # Close all
            user["active_sessions"] = []
            user["session_token"] = None

        users[tk] = user
        _save_users(users)
        return True
    return False


def get_active_devices(email):
    """Retorna lista de dispositivos activos del usuario."""
    users = _load_users()
    for tk, user in users.items():
        if user.get("email", "").lower() == email.lower():
            return user.get("active_sessions", [])
    return []


# ═══════════════════════════════════════════════════════════════
#  SHARING DETECTION (for admin)
# ═══════════════════════════════════════════════════════════════

def _log_sharing(email, event_type, details):
    logs = []
    if os.path.exists(SHARING_LOG_PATH):
        try:
            with open(SHARING_LOG_PATH, encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append({
        "email": email,
        "type": event_type,
        "details": details,
        "time": datetime.now().isoformat(),
    })
    logs = logs[-100:]

    with open(SHARING_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


def get_sharing_alerts():
    """Retorna alertas de comparticion para el admin."""
    if not os.path.exists(SHARING_LOG_PATH):
        return []
    with open(SHARING_LOG_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def get_multi_ip_users(hours=24):
    """Usuarios con multiples IPs en las ultimas N horas."""
    users = _load_users()
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    suspects = []

    for tk, user in users.items():
        sessions = user.get("active_sessions", [])
        recent = [s for s in sessions if s.get("created", "") > cutoff]
        ips = set(s.get("ip", "") for s in recent if s.get("ip"))
        if len(ips) > 1:
            suspects.append({
                "email": user.get("email", "?"),
                "plan": user.get("plan", "?"),
                "ips": list(ips),
                "devices": [s.get("device", "?") for s in recent],
                "locations": list(set(s.get("location", "") for s in recent)),
            })

    return suspects


def _send_location_alert(email, new_location):
    """Envia alerta de ubicacion inusual."""
    try:
        from email_service import _send, _wrap, _btn
        APP_URL = os.environ.get("APP_URL", "https://web-production-940b9.up.railway.app")
        html = _wrap(f'''
        <h2 style="color:#F5A623;text-align:center">Acceso desde ubicacion inusual</h2>
        <p style="color:#ccc;text-align:center">Se inicio sesion en tu cuenta desde: <strong>{new_location}</strong></p>
        <p style="color:#888;text-align:center;font-size:13px">Si fuiste tu, ignora este mensaje. Si no reconoces esta ubicacion, cambia tu contrasena inmediatamente.</p>
        {_btn("Cambiar contrasena", f"{APP_URL}/login")}
        ''')
        _send(email, "NEME BET — Acceso desde ubicacion inusual", html)
    except Exception:
        pass
