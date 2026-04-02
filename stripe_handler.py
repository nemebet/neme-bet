"""
STRIPE_HANDLER.PY — Integracion de pagos con Stripe para NEME BET
"""

import json
import os
import secrets
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, "users.json")

PLANS = {
    "basico": {"name": "Basico", "price_monthly": 9.99, "picks_limit": 3, "min_confidence": 65},
    "pro": {"name": "Pro", "price_monthly": 24.99, "picks_limit": 999, "min_confidence": 75},
    "vip": {"name": "VIP", "price_monthly": 49.99, "picks_limit": 999, "min_confidence": 65},
}


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


def create_checkout_session(plan_key, success_url, cancel_url):
    """Crea sesion de checkout en Stripe."""
    stripe = _get_stripe()
    price_env_key = f"STRIPE_PRICE_{plan_key.upper()}"
    price_id = os.environ.get(price_env_key, "")

    if not price_id:
        return None, f"Precio no configurado: {price_env_key}"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"plan": plan_key},
        )
        return session, None
    except Exception as e:
        return None, str(e)


def handle_checkout_success(session_id):
    """Procesa pago exitoso: crea usuario con token."""
    stripe = _get_stripe()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return None

    email = session.get("customer_email") or session.get("customer_details", {}).get("email", "")
    plan = session.get("metadata", {}).get("plan", "basico")
    customer_id = session.get("customer", "")

    if not email:
        # Try to get from subscription
        sub_id = session.get("subscription", "")
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            customer = stripe.Customer.retrieve(sub.customer)
            email = customer.get("email", f"user_{secrets.token_hex(4)}")

    token = secrets.token_urlsafe(32)
    users = _load_users()

    users[token] = {
        "email": email,
        "plan": plan,
        "token": token,
        "stripe_customer": customer_id,
        "stripe_session": session_id,
        "created": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=31)).isoformat(),
        "active": True,
    }

    _save_users(users)

    # Send welcome email
    try:
        from email_service import send_welcome
        send_welcome(email, token, plan)
    except Exception:
        pass

    return users[token]


def handle_webhook(payload, sig_header):
    """Procesa webhook de Stripe."""
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
    """Retorna el plan del usuario."""
    user = verify_token(token)
    if not user:
        return None
    return user.get("plan", "basico")
