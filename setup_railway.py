"""
SETUP_RAILWAY.PY — Inicializa datos en Railway al arrancar.
Crea users.json con usuario de prueba si no existe.
"""

import json
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, "users.json")

TEST_TOKEN = "GN6Xzul7mHyS156YVsRYxLFtkLSbNw_S-41wh6IY69M"


def inicializar():
    """Crea users.json con usuario de prueba si no existe."""
    if os.path.exists(USERS_PATH):
        # Verify file is valid JSON and not empty
        try:
            with open(USERS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if data:  # File exists and has data
                print(f"[SETUP] users.json OK ({len(data)} usuarios)")
                return
        except (json.JSONDecodeError, Exception):
            print("[SETUP] users.json corrupto, recreando...")

    # Create with test user
    users = {
        TEST_TOKEN: {
            "email": "swatfest2026@gmail.com",
            "plan": "pro",
            "token": TEST_TOKEN,
            "stripe_customer": "test_user",
            "stripe_session": "test_session",
            "created": datetime.now().isoformat(),
            "expires": "2026-05-01T00:00:00",
            "active": True,
        }
    }

    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    print(f"[SETUP] users.json creado con usuario de prueba")
    print(f"[SETUP] Email: swatfest2026@gmail.com | Plan: pro | Token: {TEST_TOKEN[:20]}...")


if __name__ == "__main__":
    inicializar()
