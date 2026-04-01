"""
CALIBRATION.PY — Sistema de Calibracion y Autoaprendizaje para NEME BET v5
═══════════════════════════════════════════════════════════════════════════
Modulos:
  4a. Captura automatica de resultados (football-data.org)
  4b. Calibracion automatica por mercado, liga y tipo de partido
  4c. Memoria de errores con analisis de variables fallidas
"""

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
import time
from datetime import datetime, timedelta
from math import log
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "results_db.json")
CAL_PATH = os.path.join(BASE_DIR, "calibration.json")
ERRORS_PATH = os.path.join(BASE_DIR, "error_memory.json")
WEIGHTS_PATH = os.path.join(BASE_DIR, "learned_weights.json")

def _load_env():
    env = {}
    p = os.path.join(BASE_DIR, ".env")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

ENV = _load_env()
FD_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", ENV.get("FOOTBALL_DATA_API_KEY", ""))
FD_BASE = "https://api.football-data.org/v4"

_last_req = 0
def _fd_get(ep, params=None):
    global _last_req
    elapsed = time.time() - _last_req
    if elapsed < 6.5:
        time.sleep(6.5 - elapsed)
    _last_req = time.time()
    url = f"{FD_BASE}/{ep}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", FD_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}

def _load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try: return json.load(f)
            except: pass
    return default if default is not None else []

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
#  4a. RESULTS DATABASE — Captura y almacenamiento
# ═══════════════════════════════════════════════════════════════════════════

def save_prediction(prediction, match_time=None):
    """Guarda prediccion en results_db.json para tracking posterior."""
    db = _load_json(DB_PATH, [])
    home = prediction.get("home", prediction.get("home_team", "?"))
    away = prediction.get("away", prediction.get("away_team", "?"))

    entry = {
        "id": f"{home}_vs_{away}_{datetime.now().strftime('%Y%m%d_%H%M')}",
        "home": home, "away": away,
        "predicted_at": datetime.now().isoformat(),
        "match_time": match_time,
        "check_after": (datetime.now() + timedelta(hours=6)).isoformat(),
        "p1": prediction.get("p1", prediction.get("p_home_win", 0)),
        "px": prediction.get("px", prediction.get("p_draw", 0)),
        "p2": prediction.get("p2", prediction.get("p_away_win", 0)),
        "o25": prediction.get("o25", prediction.get("p_over_25", 0)),
        "u25": prediction.get("u25", prediction.get("p_under_25", 0)),
        "btts_y": prediction.get("btts_y", prediction.get("p_btts_yes", 0)),
        "o15": prediction.get("o15", prediction.get("p_over_15", 0)),
        "lh": prediction.get("lh", prediction.get("lambda_home", 0)),
        "la": prediction.get("la", prediction.get("lambda_away", 0)),
        "elo_h": prediction.get("elo_h", 1500),
        "elo_a": prediction.get("elo_a", 1500),
        "h_form": prediction.get("h_form", ""),
        "a_form": prediction.get("a_form", ""),
        # Resultado real (se llena despues)
        "result": None,
        "home_goals": None, "away_goals": None,
        "verified": False,
        "accuracy": None,
    }
    db.append(entry)
    _save_json(DB_PATH, db)
    return entry["id"]


def fetch_result_auto(entry):
    """Intenta obtener resultado real de football-data.org."""
    home, away = entry["home"], entry["away"]
    # Buscar en partidos recientes terminados
    # Intentamos buscar por nombre de equipo
    data = _fd_get("matches", {"status": "FINISHED", "limit": 50})
    for m in data.get("matches", []):
        h = m.get("homeTeam", {}).get("name", "")
        a = m.get("awayTeam", {}).get("name", "")
        if (home.lower() in h.lower() or h.lower() in home.lower()) and \
           (away.lower() in a.lower() or a.lower() in away.lower()):
            sc = m.get("score", {}).get("fullTime", {})
            hg, ag = sc.get("home"), sc.get("away")
            if hg is not None and ag is not None:
                return {"home_goals": hg, "away_goals": ag,
                        "source": "football-data.org", "match_id": m.get("id")}
    return None


def check_pending_results():
    """Revisa predicciones pendientes y busca resultados automaticamente."""
    db = _load_json(DB_PATH, [])
    updated = 0
    now = datetime.now()

    for entry in db:
        if entry.get("verified"):
            continue
        check_after = entry.get("check_after", "")
        if check_after:
            try:
                check_dt = datetime.fromisoformat(check_after)
                if now < check_dt:
                    continue
            except: pass

        result = fetch_result_auto(entry)
        if result:
            entry["home_goals"] = result["home_goals"]
            entry["away_goals"] = result["away_goals"]
            entry["result"] = result
            entry["verified"] = True
            entry["verified_at"] = now.isoformat()
            entry["accuracy"] = _calc_accuracy(entry)
            updated += 1

    if updated > 0:
        _save_json(DB_PATH, db)
    return updated


def add_result_manual(match_query, hg, ag):
    """Agrega resultado manualmente."""
    db = _load_json(DB_PATH, [])
    for entry in reversed(db):
        if entry.get("verified"):
            continue
        label = f"{entry['home']} vs {entry['away']}".lower()
        if match_query.lower() in label:
            entry["home_goals"] = hg
            entry["away_goals"] = ag
            entry["verified"] = True
            entry["verified_at"] = datetime.now().isoformat()
            entry["result"] = {"home_goals": hg, "away_goals": ag, "source": "manual"}
            entry["accuracy"] = _calc_accuracy(entry)
            _save_json(DB_PATH, db)
            return entry
    return None


def _calc_accuracy(entry):
    """Calcula acierto detallado por mercado."""
    hg, ag = entry["home_goals"], entry["away_goals"]
    if hg is None or ag is None:
        return None

    p1, px, p2 = entry["p1"], entry["px"], entry["p2"]
    real = "1" if hg > ag else ("X" if hg == ag else "2")
    pred = "1" if p1 > max(px, p2) else ("X" if px > p2 else "2")

    total = hg + ag
    acc = {
        "1x2_pred": pred, "1x2_real": real, "1x2_ok": pred == real,
        "o25_pred": entry["o25"] > 50, "o25_real": total > 2.5,
        "o25_ok": (entry["o25"] > 50) == (total > 2.5),
        "btts_pred": entry["btts_y"] > 50, "btts_real": hg > 0 and ag > 0,
        "btts_ok": (entry["btts_y"] > 50) == (hg > 0 and ag > 0),
        "o15_pred": entry["o15"] > 50, "o15_real": total > 1.5,
        "o15_ok": (entry["o15"] > 50) == (total > 1.5),
        "score_ok": False,
    }

    markets_ok = sum([acc["1x2_ok"], acc["o25_ok"], acc["btts_ok"], acc["o15_ok"]])
    acc["pct"] = round(markets_ok / 4 * 100, 1)
    return acc


# ═══════════════════════════════════════════════════════════════════════════
#  4b. CALIBRATION — Ajuste automatico por mercado y contexto
# ═══════════════════════════════════════════════════════════════════════════

def calibrate():
    """Analiza todo el historial verificado y genera calibracion."""
    db = _load_json(DB_PATH, [])
    verified = [e for e in db if e.get("verified") and e.get("accuracy")]

    if len(verified) < 3:
        return {"status": "need_data", "n": len(verified), "min": 3}

    # Buckets de calibracion: agrupar por rango de probabilidad
    buckets = defaultdict(lambda: {"predicted": 0, "actual": 0, "n": 0})
    market_acc = defaultdict(lambda: {"ok": 0, "total": 0})
    errors_detail = []

    for e in verified:
        acc = e["accuracy"]
        hg, ag = e["home_goals"], e["away_goals"]

        # 1X2 calibration buckets (10% intervals)
        for label, prob in [("1", e["p1"]), ("X", e["px"]), ("2", e["p2"])]:
            bucket = int(prob // 10) * 10
            key = f"1x2_{bucket}-{bucket+10}"
            buckets[key]["predicted"] += prob
            real = "1" if hg > ag else ("X" if hg == ag else "2")
            buckets[key]["actual"] += (100 if label == real else 0)
            buckets[key]["n"] += 1

        # Market accuracy
        for mkt, ok_key in [("1x2", "1x2_ok"), ("o25", "o25_ok"),
                            ("btts", "btts_ok"), ("o15", "o15_ok")]:
            market_acc[mkt]["total"] += 1
            if acc.get(ok_key):
                market_acc[mkt]["ok"] += 1

        # Track errors for memory
        if not acc.get("1x2_ok"):
            errors_detail.append({
                "match": f"{e['home']} vs {e['away']}",
                "date": e.get("predicted_at", "")[:10],
                "predicted": acc["1x2_pred"],
                "actual": acc["1x2_real"],
                "p1": e["p1"], "px": e["px"], "p2": e["p2"],
                "result": f"{hg}-{ag}",
                "elo_diff": e.get("elo_h", 1500) - e.get("elo_a", 1500),
                "analysis": _analyze_error(e, acc),
            })

    # Calculate calibration factors
    cal = {
        "updated": datetime.now().isoformat(),
        "samples": len(verified),
        "buckets": {},
        "market_accuracy": {},
        "correction_factors": {},
    }

    for key, b in buckets.items():
        if b["n"] > 0:
            avg_pred = b["predicted"] / b["n"]
            avg_real = b["actual"] / b["n"]
            cal["buckets"][key] = {
                "avg_predicted": round(avg_pred, 1),
                "avg_actual": round(avg_real, 1),
                "gap": round(avg_pred - avg_real, 1),
                "n": b["n"],
            }

    for mkt, data in market_acc.items():
        pct = round(data["ok"] / data["total"] * 100, 1) if data["total"] > 0 else 0
        cal["market_accuracy"][mkt] = {"accuracy": pct, "n": data["total"]}

    # Correction factors: if model says 80% but real is 60%, factor = 0.75
    for mkt, data in market_acc.items():
        if data["total"] >= 3:
            acc_pct = data["ok"] / data["total"]
            # Ideally accuracy should match confidence. If we're overconfident, scale down.
            cal["correction_factors"][mkt] = round(min(acc_pct / 0.65, 1.05), 3)

    _save_json(CAL_PATH, cal)

    # Save errors to memory
    _update_error_memory(errors_detail)

    # Apply corrections to learned weights
    _apply_calibration(cal)

    return {"status": "calibrated", "n": len(verified), "cal": cal,
            "errors": len(errors_detail)}


def _analyze_error(entry, acc):
    """Analiza por que fallo una prediccion."""
    reasons = []
    hg, ag = entry["home_goals"], entry["away_goals"]

    if acc["1x2_pred"] == "1" and acc["1x2_real"] != "1":
        if entry["p1"] > 60:
            reasons.append("Favorito sobreestimado (>60% pero no gano)")
        if entry.get("h_form", "").count("L") >= 2:
            reasons.append("Forma local mala no capturada suficiente")

    if acc["1x2_pred"] != "X" and acc["1x2_real"] == "X":
        reasons.append("Empate no previsto — posible sesgo anti-empate")

    if not acc["o25_ok"]:
        if acc["o25_pred"] and not acc["o25_real"]:
            reasons.append(f"Overpredijo goles (lambda {entry.get('lh',0):.1f}-{entry.get('la',0):.1f} pero real {hg}-{ag})")
        elif not acc["o25_pred"] and acc["o25_real"]:
            reasons.append(f"Underpredijo goles (real {hg}-{ag})")

    if not reasons:
        reasons.append("Error general de calibracion")

    return "; ".join(reasons)


def _update_error_memory(errors):
    """Actualiza memoria de errores, mantiene ultimos 20."""
    memory = _load_json(ERRORS_PATH, [])
    memory.extend(errors)
    memory = memory[-20:]  # Keep last 20
    _save_json(ERRORS_PATH, memory)


def _apply_calibration(cal):
    """Aplica factores de calibracion a los pesos aprendidos."""
    weights = _load_json(WEIGHTS_PATH, {})
    if not weights:
        weights = {
            "version": 1, "w_poisson": 0.40, "w_dixon_coles": 0.30, "w_elo": 0.30,
            "home_advantage": 1.10, "injury_baja": 0.04, "injury_duda": 0.02,
            "injury_max": 0.20, "form_impact": 400,
            "draw_bias": 0.0, "over_bias": 0.0, "btts_bias": 0.0,
            "samples": 0, "accuracy_1x2": None, "accuracy_ou": None,
            "accuracy_btts": None, "brier_score": None,
        }

    ma = cal.get("market_accuracy", {})

    if "1x2" in ma:
        weights["accuracy_1x2"] = ma["1x2"]["accuracy"]
    if "o25" in ma:
        weights["accuracy_ou"] = ma["o25"]["accuracy"]
        # If over-predicting overs, reduce lambdas slightly
        if ma["o25"]["accuracy"] < 45 and ma["o25"]["n"] >= 5:
            weights["over_bias"] = max(weights.get("over_bias", 0) - 0.02, -0.10)
    if "btts" in ma:
        weights["accuracy_btts"] = ma["btts"]["accuracy"]

    # Check draw bias from buckets
    draw_buckets = {k: v for k, v in cal.get("buckets", {}).items()
                    if k.startswith("1x2_") and "20-30" in k}
    for k, v in draw_buckets.items():
        if v["n"] >= 3 and v["gap"] > 5:
            weights["draw_bias"] = min(weights.get("draw_bias", 0) + 0.01, 0.05)

    weights["samples"] = cal.get("samples", 0)
    weights["version"] = weights.get("version", 1) + 1
    weights["updated"] = datetime.now().isoformat()
    _save_json(WEIGHTS_PATH, weights)


# ═══════════════════════════════════════════════════════════════════════════
#  4c. DASHBOARD DATA
# ═══════════════════════════════════════════════════════════════════════════

def get_dashboard():
    """Genera datos para el dashboard de rendimiento."""
    db = _load_json(DB_PATH, [])
    verified = [e for e in db if e.get("verified") and e.get("accuracy")]
    cal = _load_json(CAL_PATH, {})
    errors = _load_json(ERRORS_PATH, [])
    weights = _load_json(WEIGHTS_PATH, {})

    now = datetime.now()

    # Accuracy by time window
    def acc_window(days):
        cutoff = (now - timedelta(days=days)).isoformat()
        window = [e for e in verified if e.get("predicted_at", "") >= cutoff]
        if not window:
            return None
        ok = sum(1 for e in window if e["accuracy"].get("1x2_ok"))
        return round(ok / len(window) * 100, 1)

    # Accuracy by market
    market_data = {}
    for mkt in ["1x2", "o25", "btts", "o15"]:
        ok_key = f"{mkt}_ok"
        total = sum(1 for e in verified if ok_key in e.get("accuracy", {}))
        correct = sum(1 for e in verified if e.get("accuracy", {}).get(ok_key))
        market_data[mkt] = {
            "accuracy": round(correct / total * 100, 1) if total > 0 else None,
            "n": total,
        }

    return {
        "total_predictions": len(db),
        "verified": len(verified),
        "pending": len(db) - len(verified),
        "acc_7d": acc_window(7),
        "acc_30d": acc_window(30),
        "acc_all": acc_window(9999),
        "markets": market_data,
        "calibration": cal,
        "recent_errors": errors[-5:],
        "weights": weights,
        "last_calibration": cal.get("updated"),
    }
