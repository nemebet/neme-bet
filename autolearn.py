"""
AUTOLEARN.PY — Modulo de Autoaprendizaje para NEME BET
══════════════════════════════════════════════════════
Analiza predicciones pasadas vs resultados reales y ajusta
automaticamente los pesos del modelo para mejorar precision.

Funcionalidades:
  1. Calibracion de pesos del ensemble (Poisson/DC/ELO)
  2. Ajuste de home_advantage, injury_impact, form_weight
  3. Deteccion de sesgos sistematicos
  4. Reporte de rendimiento por mercado y liga
"""

import json
import os
from math import log, exp
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIST_PATH = os.path.join(BASE_DIR, "resultados.json")
WEIGHTS_PATH = os.path.join(BASE_DIR, "learned_weights.json")

# Pesos por defecto (v5 original)
DEFAULT_WEIGHTS = {
    "version": 1,
    "updated": None,
    "samples": 0,
    # Ensemble weights
    "w_poisson": 0.40,
    "w_dixon_coles": 0.30,
    "w_elo": 0.30,
    # Adjustments
    "home_advantage": 1.10,
    "form_impact": 400,       # divisor: (form_pct - 50) / form_impact
    "injury_baja": 0.04,      # impacto por baja confirmada
    "injury_duda": 0.02,      # impacto por duda
    "injury_max": 0.20,       # impacto maximo
    # Calibration
    "draw_bias": 0.0,         # ajuste al empate si el modelo lo subestima
    "over_bias": 0.0,         # ajuste a over 2.5
    "btts_bias": 0.0,         # ajuste a BTTS
    # Performance tracking
    "accuracy_1x2": None,
    "accuracy_ou": None,
    "accuracy_btts": None,
    "brier_score": None,
}


def load_weights():
    """Carga pesos aprendidos o retorna defaults."""
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
            # Merge con defaults para nuevos campos
            merged = {**DEFAULT_WEIGHTS, **saved}
            return merged
    return dict(DEFAULT_WEIGHTS)


def save_weights(weights):
    weights["updated"] = datetime.now().isoformat()
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2, ensure_ascii=False)


def load_verified_history():
    """Carga solo las entradas del historial con resultados verificados."""
    if not os.path.exists(HIST_PATH):
        return []
    with open(HIST_PATH, encoding="utf-8") as f:
        try:
            history = json.load(f)
        except json.JSONDecodeError:
            return []

    verified = []
    for entry in history:
        if not entry.get("results"):
            continue
        for pred in entry.get("predictions", []):
            home = pred.get("home", pred.get("home_team", ""))
            away = pred.get("away", pred.get("away_team", ""))
            label = f"{home} vs {away}"
            result = entry["results"].get(label)
            if not result:
                continue
            hg = result.get("hg", result.get("home_goals", 0))
            ag = result.get("ag", result.get("away_goals", 0))
            verified.append({"pred": pred, "hg": hg, "ag": ag})

    return verified


def compute_brier(prob, happened):
    """Brier score para una prediccion individual. Menor = mejor."""
    p = prob / 100.0
    return (p - (1.0 if happened else 0.0)) ** 2


def analyze_performance(verified):
    """Analiza rendimiento detallado del modelo."""
    if not verified:
        return None

    n = len(verified)
    correct_1x2 = 0
    correct_ou = 0
    correct_btts = 0
    brier_scores = []

    # Sesgos
    predicted_home_wins = 0
    actual_home_wins = 0
    predicted_draws = 0
    actual_draws = 0
    predicted_over = 0
    actual_over = 0
    predicted_btts = 0
    actual_btts = 0

    # Errores por sub-modelo
    poi_correct = dc_correct = elo_correct = 0

    for item in verified:
        pred = item["pred"]
        hg, ag = item["hg"], item["ag"]

        p1 = pred.get("p1", pred.get("p_home_win", 33))
        px = pred.get("px", pred.get("p_draw", 33))
        p2 = pred.get("p2", pred.get("p_away_win", 33))
        o25 = pred.get("o25", pred.get("p_over_25", 50))
        btts_y = pred.get("btts_y", pred.get("p_btts_yes", 50))

        # Resultado real
        if hg > ag:
            actual_1x2 = "1"
        elif hg == ag:
            actual_1x2 = "X"
        else:
            actual_1x2 = "2"

        # 1X2
        pred_1x2 = "1" if p1 > max(px, p2) else ("X" if px > p2 else "2")
        if pred_1x2 == actual_1x2:
            correct_1x2 += 1

        # Tracking sesgos
        if p1 > max(px, p2):
            predicted_home_wins += 1
        if actual_1x2 == "1":
            actual_home_wins += 1
        if px > max(p1, p2):
            predicted_draws += 1
        if actual_1x2 == "X":
            actual_draws += 1

        # O/U 2.5
        total_goals = hg + ag
        if (o25 > 50) == (total_goals > 2.5):
            correct_ou += 1
        if o25 > 50:
            predicted_over += 1
        if total_goals > 2.5:
            actual_over += 1

        # BTTS
        actual_btts_val = hg > 0 and ag > 0
        if (btts_y > 50) == actual_btts_val:
            correct_btts += 1
        if btts_y > 50:
            predicted_btts += 1
        if actual_btts_val:
            actual_btts += 1

        # Brier score
        probs = {"1": p1 / 100, "X": px / 100, "2": p2 / 100}
        for outcome, prob in probs.items():
            brier_scores.append(compute_brier(prob * 100, outcome == actual_1x2))

        # Sub-model accuracy
        poi = pred.get("poi", pred.get("sub_poisson", {}))
        dc = pred.get("dc", pred.get("sub_dixon_coles", {}))
        elo = pred.get("elo", pred.get("sub_elo", {}))
        for sub, counter_name in [(poi, "poi"), (dc, "dc"), (elo, "elo")]:
            s1 = sub.get("1", 33)
            sx = sub.get("X", 33)
            s2 = sub.get("2", 33)
            sub_pred = "1" if s1 > max(sx, s2) else ("X" if sx > s2 else "2")
            if sub_pred == actual_1x2:
                if counter_name == "poi": poi_correct += 1
                elif counter_name == "dc": dc_correct += 1
                else: elo_correct += 1

    return {
        "n": n,
        "acc_1x2": round(correct_1x2 / n * 100, 1),
        "acc_ou": round(correct_ou / n * 100, 1),
        "acc_btts": round(correct_btts / n * 100, 1),
        "brier": round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None,
        # Sesgos
        "bias_home": round((predicted_home_wins - actual_home_wins) / n * 100, 1),
        "bias_draw": round((predicted_draws - actual_draws) / n * 100, 1),
        "bias_over": round((predicted_over - actual_over) / n * 100, 1),
        "bias_btts": round((predicted_btts - actual_btts) / n * 100, 1),
        # Sub-model accuracy
        "poi_acc": round(poi_correct / n * 100, 1),
        "dc_acc": round(dc_correct / n * 100, 1),
        "elo_acc": round(elo_correct / n * 100, 1),
    }


def learn(min_samples=5):
    """
    Proceso principal de aprendizaje.
    Analiza historial, detecta sesgos, ajusta pesos.
    Retorna dict con cambios realizados.
    """
    verified = load_verified_history()
    if len(verified) < min_samples:
        return {
            "status": "insufficient_data",
            "samples": len(verified),
            "min_required": min_samples,
            "message": f"Necesito al menos {min_samples} predicciones verificadas. Tienes {len(verified)}."
        }

    perf = analyze_performance(verified)
    weights = load_weights()
    changes = []

    # ── 1. Ajustar pesos del ensemble segun precision de sub-modelos ──
    total_sub_acc = perf["poi_acc"] + perf["dc_acc"] + perf["elo_acc"]
    if total_sub_acc > 0:
        new_w_poi = round(perf["poi_acc"] / total_sub_acc, 3)
        new_w_dc = round(perf["dc_acc"] / total_sub_acc, 3)
        new_w_elo = round(1.0 - new_w_poi - new_w_dc, 3)

        # Suavizar: no cambiar mas de 5% por iteracion
        for key, new_val in [("w_poisson", new_w_poi), ("w_dixon_coles", new_w_dc), ("w_elo", new_w_elo)]:
            old = weights[key]
            delta = new_val - old
            clamped = max(-0.05, min(delta, 0.05))
            adjusted = round(old + clamped, 3)
            adjusted = max(0.10, min(adjusted, 0.60))
            if adjusted != old:
                changes.append(f"{key}: {old} -> {adjusted} (sub-model accuracy)")
                weights[key] = adjusted

        # Renormalizar
        total = weights["w_poisson"] + weights["w_dixon_coles"] + weights["w_elo"]
        weights["w_poisson"] = round(weights["w_poisson"] / total, 3)
        weights["w_dixon_coles"] = round(weights["w_dixon_coles"] / total, 3)
        weights["w_elo"] = round(1.0 - weights["w_poisson"] - weights["w_dixon_coles"], 3)

    # ── 2. Corregir sesgo de empates ──
    if abs(perf["bias_draw"]) > 5:
        # Si predecimos menos empates de los que ocurren -> boost draw
        adj = -perf["bias_draw"] / 100 * 0.3  # Correccion suave
        adj = max(-0.05, min(adj, 0.05))
        old = weights["draw_bias"]
        weights["draw_bias"] = round(old + adj, 4)
        if adj != 0:
            changes.append(f"draw_bias: {old} -> {weights['draw_bias']} (bias={perf['bias_draw']}%)")

    # ── 3. Corregir sesgo de over/under ──
    if abs(perf["bias_over"]) > 5:
        adj = -perf["bias_over"] / 100 * 0.3
        adj = max(-0.05, min(adj, 0.05))
        old = weights["over_bias"]
        weights["over_bias"] = round(old + adj, 4)
        if adj != 0:
            changes.append(f"over_bias: {old} -> {weights['over_bias']} (bias={perf['bias_over']}%)")

    # ── 4. Corregir sesgo BTTS ──
    if abs(perf["bias_btts"]) > 5:
        adj = -perf["bias_btts"] / 100 * 0.3
        adj = max(-0.05, min(adj, 0.05))
        old = weights["btts_bias"]
        weights["btts_bias"] = round(old + adj, 4)
        if adj != 0:
            changes.append(f"btts_bias: {old} -> {weights['btts_bias']} (bias={perf['bias_btts']}%)")

    # ── 5. Ajustar home advantage si hay sesgo de local ──
    if abs(perf["bias_home"]) > 8:
        adj = -perf["bias_home"] / 100 * 0.02
        adj = max(-0.03, min(adj, 0.03))
        old = weights["home_advantage"]
        weights["home_advantage"] = round(old + adj, 3)
        weights["home_advantage"] = max(1.0, min(1.25, weights["home_advantage"]))
        if weights["home_advantage"] != old:
            changes.append(f"home_advantage: {old} -> {weights['home_advantage']}")

    # Guardar metricas
    weights["accuracy_1x2"] = perf["acc_1x2"]
    weights["accuracy_ou"] = perf["acc_ou"]
    weights["accuracy_btts"] = perf["acc_btts"]
    weights["brier_score"] = perf["brier"]
    weights["samples"] = len(verified)
    weights["version"] = weights.get("version", 1) + 1

    save_weights(weights)

    return {
        "status": "learned",
        "samples": len(verified),
        "performance": perf,
        "changes": changes,
        "weights": weights,
    }


def get_performance_report():
    """Genera reporte legible de rendimiento."""
    verified = load_verified_history()
    if not verified:
        return "Sin datos verificados para analizar."

    perf = analyze_performance(verified)
    weights = load_weights()

    lines = [
        f"REPORTE DE RENDIMIENTO NEME BET",
        f"{'=' * 45}",
        f"Muestras verificadas: {perf['n']}",
        f"",
        f"PRECISION POR MERCADO:",
        f"  1X2:   {perf['acc_1x2']}%",
        f"  O/U:   {perf['acc_ou']}%",
        f"  BTTS:  {perf['acc_btts']}%",
        f"  Brier: {perf['brier']} (menor = mejor, <0.25 = bueno)",
        f"",
        f"PRECISION POR SUB-MODELO:",
        f"  Poisson:     {perf['poi_acc']}% (peso: {weights['w_poisson']})",
        f"  Dixon-Coles: {perf['dc_acc']}% (peso: {weights['w_dixon_coles']})",
        f"  ELO:         {perf['elo_acc']}% (peso: {weights['w_elo']})",
        f"",
        f"SESGOS DETECTADOS:",
        f"  Local:  {perf['bias_home']:+.1f}% {'(sobreestima)' if perf['bias_home'] > 0 else '(subestima)'}",
        f"  Empate: {perf['bias_draw']:+.1f}%",
        f"  Over:   {perf['bias_over']:+.1f}%",
        f"  BTTS:   {perf['bias_btts']:+.1f}%",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print("\nNEME BET — Modulo de Autoaprendizaje")
    print("=" * 45)

    result = learn(min_samples=3)
    print(f"\nEstado: {result['status']}")

    if result["status"] == "learned":
        print(f"Muestras: {result['samples']}")
        print(f"\nCambios:")
        for c in result["changes"]:
            print(f"  {c}")
        if not result["changes"]:
            print("  (sin cambios necesarios)")
        print(f"\n{get_performance_report()}")
    else:
        print(result["message"])
