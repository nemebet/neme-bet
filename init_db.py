"""
INIT_DB.PY — Inicializa archivos de datos si no existen.
Railway ejecuta esto al arrancar.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = {
    "users.json": {},
    "results_db.json": [],
    "resultados.json": [],
    "picks_del_dia.json": None,
    "calibration.json": {},
    "learned_weights.json": {},
    "scheduler_log.json": [],
    "push_subscriptions.json": [],
}


def init():
    created = 0
    for fname, default in FILES.items():
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default if default is not None else {}, f)
            print(f"  [INIT] Created {fname}")
            created += 1

    # Create directories
    for d in ["uploads", "backups"]:
        dp = os.path.join(BASE_DIR, d)
        os.makedirs(dp, exist_ok=True)

    print(f"  [INIT] {created} files created")
    return created


if __name__ == "__main__":
    init()
