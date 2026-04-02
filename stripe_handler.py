"""
STRIPE_HANDLER.PY — Pagos Stripe + gestion de usuarios para NEME BET
"""

import json
import os
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from data_dir import data_path
USERS_PATH = data_path("users.json")

PLANS = {
    "free_trial": {"name": "Gratuito", "price_monthly": 0, "picks_limit": 1,
                   "min_conf": 55, "max_conf": 59, "markets": ["1x2"]},
    "basico": {"name": "Basico", "price_monthly": 9.99, "picks_limit": 3,
               "min_conf": 60, "max_conf": 64, "markets": ["1x2"]},
    "pro": {"name": "Pro", "price_monthly": 24.99, "picks_limit": 999,
            "min_conf": 65, "max_conf": 75, "markets": ["1x2", "btts", "ou", "corners"]},
    "vip": {"name": "VIP", "price_monthly": 49.99, "picks_limit": 999,
            "min_conf": 76, "max_conf": 100, "markets": ["1x2", "btts", "ou", "corners", "scanner", "lineups"]},
}


def filtrar_por_plan(analisis, plan):
    """Filtra analisis segun nivel de confianza del plan."""
    p = PLANS.get(plan, PLANS["free_trial"])
    min_c, max_c = p["min_conf"], p["max_conf"]
    limit = p["picks_limit"]
    filtered = [a for a in analisis if min_c <= a.get("prob", 0) <= max_c]
    return filtered[:limit]


def get_plan_badge(prob):
    """Retorna badge visual segun nivel de confianza."""
    if prob >= 76:
        return {"label": "VIP", "color": "#F5A623", "bg": "rgba(245,166,35,0.15)", "icon": "star"}
    elif prob >= 65:
        return {"label": "Pro", "color": "#1AE89B", "bg": "rgba(26,232,155,0.15)", "icon": ""}
    elif prob >= 60:
        return {"label": "Basico", "color": "#4A9EFF", "bg": "rgba(74,158,255,0.15)", "icon": ""}
    else:
        return {"label": "Gratuito", "color": "#888", "bg": "rgba(136,136,136,0.1)", "icon": ""}


def _get_stripe():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


def _load_users():
    if os.path.exists(USERS_PATH):
        with open(USERS_PATH, encoding="utf-8") as f:
            try: return json.load(f)
            except: return {}
    return {}


def _save_users(users):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
#  PASSWORD HASHING (bcrypt with fallback to hashlib)
# ═══════════════════════════════════════════════════════════════

def hash_password(password):
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return f"pbkdf2:{salt}:{h.hex()}"


def check_password(password, hashed):
    try:
        import bcrypt
        if hashed.startswith("$2"):
            return bcrypt.checkpw(password.encode(), hashed.encode())
    except ImportError:
        pass

    if hashed.startswith("pbkdf2:"):
        _, salt, stored = hashed.split(":", 2)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(h.hex(), stored)

    return False


# ═══════════════════════════════════════════════════════════════
#  USER LOOKUP
# ═══════════════════════════════════════════════════════════════

def find_user_by_email(email):
    """Busca usuario por email. Retorna (token_key, user_dict) o (None, None)."""
    users = _load_users()
    email_lower = email.lower().strip()
    for token_key, user in users.items():
        if user.get("email", "").lower().strip() == email_lower:
            return token_key, user
    return None, None


def find_user_by_token(token):
    """Busca usuario por token original."""
    users = _load_users()
    user = users.get(token)
    if user:
        return token, user
    return None, None


# ═══════════════════════════════════════════════════════════════
#  LOGIN WITH PASSWORD
# ═══════════════════════════════════════════════════════════════

def login_with_password(email, password):
    """Login con email + password. Retorna user dict o None."""
    token_key, user = find_user_by_email(email)
    if not user:
        return None

    if not user.get("active", False):
        return None

    expires = user.get("expires", "")
    if expires:
        try:
            if datetime.fromisoformat(expires) < datetime.now():
                user["active"] = False
                users = _load_users()
                users[token_key] = user
                _save_users(users)
                return None
        except Exception:
            pass

    pw_hash = user.get("password_hash", "")
    if not pw_hash:
        return None  # No password set yet — must use token first

    if not check_password(password, pw_hash):
        return None

    return user


# ═══════════════════════════════════════════════════════════════
#  ACTIVATE WITH TOKEN (first time — set password)
# ═══════════════════════════════════════════════════════════════

def activate_with_token(token, password):
    """Primera vez: valida token y guarda password. Retorna user o None."""
    users = _load_users()
    user = users.get(token)
    if not user:
        return None

    if not user.get("active", False):
        return None

    expires = user.get("expires", "")
    if expires:
        try:
            if datetime.fromisoformat(expires) < datetime.now():
                return None
        except Exception:
            pass

    user["password_hash"] = hash_password(password)
    user["password_set_at"] = datetime.now().isoformat()
    users[token] = user
    _save_users(users)
    return user


# ═══════════════════════════════════════════════════════════════
#  PASSWORD RESET
# ═══════════════════════════════════════════════════════════════

def create_reset_token(email):
    """Crea token de reset que expira en 1 hora."""
    token_key, user = find_user_by_email(email)
    if not user:
        return None

    reset_token = secrets.token_urlsafe(32)
    users = _load_users()
    users[token_key]["reset_token"] = reset_token
    users[token_key]["reset_expires"] = (datetime.now() + timedelta(hours=1)).isoformat()
    _save_users(users)
    return reset_token


def reset_password(reset_token, new_password):
    """Cambia password con reset token. Retorna True/False."""
    users = _load_users()
    for token_key, user in users.items():
        if user.get("reset_token") == reset_token:
            expires = user.get("reset_expires", "")
            if expires:
                try:
                    if datetime.fromisoformat(expires) < datetime.now():
                        return False  # Expired
                except Exception:
                    pass

            user["password_hash"] = hash_password(new_password)
            user["reset_token"] = None
            user["reset_expires"] = None
            user["password_set_at"] = datetime.now().isoformat()
            users[token_key] = user
            _save_users(users)
            return True
    return False


# ═══════════════════════════════════════════════════════════════
#  SESSION INVALIDATION
# ═══════════════════════════════════════════════════════════════

def invalidate_all_sessions(email):
    """Genera nuevo session_secret para invalidar todas las sesiones."""
    token_key, user = find_user_by_email(email)
    if not user:
        return False
    users = _load_users()
    users[token_key]["session_secret"] = secrets.token_hex(16)
    _save_users(users)
    return True


# ═══════════════════════════════════════════════════════════════
#  EXISTING FUNCTIONS (kept for compatibility)
# ═══════════════════════════════════════════════════════════════

def verify_token(token):
    """Verifica que un token sea valido y activo."""
    users = _load_users()
    user = users.get(token)
    if not user:
        return None
    if not user.get("active", False):
        return None
    expires = user.get("expires", "")
    if expires and datetime.fromisoformat(expires) < datetime.now():
        user["active"] = False
        _save_users(users)
        return None
    return user


def get_user_plan(token):
    user = verify_token(token)
    if not user:
        return None
    return user.get("plan", "basico")


def create_checkout_session(plan_key, success_url, cancel_url):
    stripe = _get_stripe()
    price_id = os.environ.get(f"STRIPE_PRICE_{plan_key.upper()}", "")
    if not price_id:
        return None, f"Precio no configurado: STRIPE_PRICE_{plan_key.upper()}"
    try:
        sess = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"plan": plan_key},
        )
        return sess, None
    except Exception as e:
        return None, str(e)


def handle_checkout_success(session_id):
    stripe = _get_stripe()
    try:
        sess = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return None

    email = sess.get("customer_email") or sess.get("customer_details", {}).get("email", "")
    plan = sess.get("metadata", {}).get("plan", "basico")
    customer_id = sess.get("customer", "")

    if not email:
        sub_id = sess.get("subscription", "")
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            customer = stripe.Customer.retrieve(sub.customer)
            email = customer.get("email", f"user_{secrets.token_hex(4)}")

    token = secrets.token_urlsafe(32)
    users = _load_users()
    users[token] = {
        "email": email, "plan": plan, "token": token,
        "stripe_customer": customer_id,
        "stripe_session": session_id,
        "created": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=31)).isoformat(),
        "active": True,
    }
    _save_users(users)

    try:
        from email_service import send_welcome
        send_welcome(email, token, plan)
    except Exception:
        pass

    return users[token]


def handle_webhook(payload, sig_header):
    stripe = _get_stripe()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return False
    if event["type"] == "customer.subscription.deleted":
        customer_id = event["data"]["object"].get("customer", "")
        users = _load_users()
        for token, user in users.items():
            if user.get("stripe_customer") == customer_id:
                user["active"] = False
                user["cancelled_at"] = datetime.now().isoformat()
        _save_users(users)
    return True
