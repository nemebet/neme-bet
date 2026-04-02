"""
PUSH_NOTIFY.PY — Web Push Notifications para NEME BET
═════════════════════════════════════════════════════
Genera claves VAPID y envia notificaciones push reales a Android.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from data_dir import data_path
VAPID_PATH = data_path("vapid_keys.json")
SUBS_PATH = data_path("push_subscriptions.json")


def generate_vapid_keys():
    """Retorna claves VAPID desde env vars, archivo, o genera nuevas."""
    # 1. Environment variables (Railway)
    pub = os.environ.get("VAPID_PUBLIC_KEY", "")
    priv = os.environ.get("VAPID_PRIVATE_KEY", "")
    if pub and priv:
        return {"public_key": pub, "private_key": priv}

    # 2. Local file
    if os.path.exists(VAPID_PATH):
        with open(VAPID_PATH) as f:
            return json.load(f)

    try:
        from pywebpush import webpush
        from py_vapid import Vapid
        vapid = Vapid()
        vapid.generate_keys()
        keys = {
            "private_key": vapid.private_pem(),
            "public_key": vapid.public_key.public_bytes_raw().hex(),
        }
    except ImportError:
        # Fallback: generate with cryptography
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        import base64

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        pub_numbers = private_key.public_key().public_numbers()

        # Encode as uncompressed point
        x = pub_numbers.x.to_bytes(32, 'big')
        y = pub_numbers.y.to_bytes(32, 'big')
        pub_raw = b'\x04' + x + y
        pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b'=').decode()

        priv_raw = private_key.private_numbers().private_value.to_bytes(32, 'big')
        priv_b64 = base64.urlsafe_b64encode(priv_raw).rstrip(b'=').decode()

        keys = {
            "public_key": pub_b64,
            "private_key": priv_b64,
        }

    with open(VAPID_PATH, "w") as f:
        json.dump(keys, f, indent=2)

    return keys


def get_public_key():
    """Retorna la clave publica VAPID para el frontend."""
    keys = generate_vapid_keys()
    return keys["public_key"]


def save_subscription(subscription_info):
    """Guarda suscripcion push de un cliente."""
    subs = []
    if os.path.exists(SUBS_PATH):
        with open(SUBS_PATH, encoding="utf-8") as f:
            try:
                subs = json.load(f)
            except Exception:
                subs = []

    # Dedup by endpoint
    endpoints = {s.get("endpoint") for s in subs}
    if subscription_info.get("endpoint") not in endpoints:
        subs.append(subscription_info)
        with open(SUBS_PATH, "w", encoding="utf-8") as f:
            json.dump(subs, f, indent=2)

    return len(subs)


def send_push(subscription_info, payload):
    """Envia notificacion push a un suscriptor."""
    keys = generate_vapid_keys()

    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=keys["private_key"],
            vapid_claims={"sub": "mailto:nemebet@nemebet.app"},
        )
        return True
    except ImportError:
        # pywebpush not available — notifications stored for polling
        return False
    except Exception as e:
        print(f"Push error: {e}")
        return False
