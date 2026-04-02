"""
SETUP_RAILWAY.PY — Inicializa datos en Railway al arrancar.
Crea users.json con admin VIP permanente si no existe.
"""

import json
import os
import secrets
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from data_dir import data_path
USERS_PATH = data_path("users.json")

ADMIN_EMAIL = "swatfest2026@gmail.com"
ADMIN_TOKEN = "GN6Xzul7mHyS156YVsRYxLFtkLSbNw_S-41wh6IY69M"


def _hash_password(password):
    """Hash password con bcrypt o fallback pbkdf2."""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        import hashlib, hmac
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return f"pbkdf2:{salt}:{h.hex()}"


def inicializar():
    """Crea users.json con admin VIP permanente si no existe."""

    # Si ya existe y tiene datos, verificar que el admin este presente
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if data:
                # Check if admin exists
                admin_exists = any(
                    u.get("email", "").lower() == ADMIN_EMAIL.lower()
                    for u in data.values()
                )
                if admin_exists:
                    print(f"[SETUP] users.json OK ({len(data)} usuarios, admin presente)")
                    return
                # Admin missing, add it
                print("[SETUP] Admin no encontrado, agregando...")
                _add_admin(data)
                return
        except (json.JSONDecodeError, Exception):
            print("[SETUP] users.json corrupto, recreando...")

    # Create fresh with admin
    _add_admin({})


def _add_admin(users):
    """Agrega el usuario admin VIP permanente."""
    admin_password = os.environ.get("ADMIN_PASSWORD", "NemeBet2026!")
    pw_hash = _hash_password(admin_password)

    users[ADMIN_TOKEN] = {
        "nombre": "Oscar",
        "email": ADMIN_EMAIL,
        "plan": "vip",
        "rol": "admin",
        "token": ADMIN_TOKEN,
        "password_hash": pw_hash,
        "password_set_at": datetime.now().isoformat(),
        "stripe_customer": "admin_permanent",
        "stripe_session": "admin_permanent",
        "created": datetime.now().isoformat(),
        "expires": "2099-12-31T23:59:59",
        "active": True,
        "free_analysis_used": False,
        "max_devices_override": 99,
        "skip_location_check": True,
    }

    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    print(f"[SETUP] Admin VIP creado: {ADMIN_EMAIL}")
    print(f"[SETUP] Plan: VIP permanente (2099)")
    print(f"[SETUP] Password: desde ADMIN_PASSWORD env var")


if __name__ == "__main__":
    inicializar()
