"""
Predictor de Apuestas v3 — Modelo Ensemble Avanzado
════════════════════════════════════════════════════

Componentes:
  1. Poisson ponderado temporalmente (decaimiento exponencial)
  2. Dixon-Coles correction (ajuste resultados bajos)
  3. ELO rating (fuerza relativa real)
  4. Factor de motivación (presión eliminatoria)
  5. Ajuste por bajas (jugadores clave ausentes)
  6. Córners con estilo de juego
  7. Ensemble: 40% Poisson + 30% Dixon-Coles + 30% ELO
"""

import json
import os
import sys
from math import exp, lgamma, log, sqrt
from collections import defaultdict
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

MAX_GOALS = 8
REFERENCE_DATE = "2026-03-31"  # Fecha de los partidos a predecir

# Pesos del ensemble
W_POISSON = 0.40
W_DIXON_COLES = 0.30
W_ELO = 0.30

# Dixon-Coles: parámetro rho (dependencia para scores bajos)
DC_RHO = -0.13  # Valor típico: entre -0.10 y -0.20

# Decaimiento temporal: half-life en días
DECAY_HALF_LIFE = 365  # Un partido de hace 1 año pesa ~50%

# ELO config
ELO_INITIAL = 1500
ELO_K = 40  # Factor K para selecciones (FIFA usa ~40-60)
ELO_HOME_ADVANTAGE = 100  # Puntos de ventaja local

# ═══════════════════════════════════════════════════════════════════════════
#  BAJAS DE JUGADORES CLAVE (impacto manual)
# ═══════════════════════════════════════════════════════════════════════════

# {equipo: [(jugador, impacto_ataque, impacto_defensa)]}
# Impacto en goles esperados: negativo = debilita
KEY_ABSENCES = {
    "Italy": [
        ("Barella", -0.15, -0.05),      # Centrocampista clave, conecta juego
    ],
    "Bosnia-Herzegovina": [
        ("Dzeko", -0.25, 0.0),           # Retirado de selección, referente ofensivo
    ],
    "Denmark": [
        ("Eriksen", -0.20, 0.0),         # Menor protagonismo, irregular
    ],
    "Kosovo": [],
    "Czechia": [],
    "Turkey": [],
    "Sweden": [
        ("Isak", -0.30, 0.0),            # Lesionado, goleador principal
    ],
    "Poland": [
        ("Lewandowski", -0.10, 0.0),     # 37 años, menor impacto físico
    ],
}

# ═══════════════════════════════════════════════════════════════════════════
#  FACTOR DE MOTIVACIÓN
# ═══════════════════════════════════════════════════════════════════════════

# Equipos que nunca han estado en un Mundial o tienen motivación extra
# Factor multiplicador sobre lambda de ataque en casa
MOTIVATION_FACTORS = {
    "Kosovo":              1.15,  # Nunca en un Mundial, país joven, histórico
    "Bosnia-Herzegovina":  1.10,  # Solo 1 Mundial (2014), gran oportunidad
    "Czechia":             1.05,  # No van desde 2006, generación necesitada
    "Sweden":              1.05,  # No fueron en 2022, quieren volver
    "Italy":               1.00,  # Trauma de no ir en 2018 y 2022, pero favoritos
    "Denmark":             1.00,  # Ya clasificados a últimos Mundiales
    "Turkey":              1.08,  # No van desde 2002, 24 años de espera
    "Poland":              1.00,  # Fueron en 2022, menos presión
}


# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIONES BASE
# ═══════════════════════════════════════════════════════════════════════════

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(k * log(max(lam, 1e-10)) - lam - lgamma(k + 1))


def prob_to_odds(prob_pct):
    if prob_pct <= 0:
        return 99.99
    return round(100 / prob_pct, 2)


def days_between(date_str, ref_date_str):
    d1 = datetime.strptime(date_str[:10], "%Y-%m-%d")
    d2 = datetime.strptime(ref_date_str[:10], "%Y-%m-%d")
    return abs((d2 - d1).days)


def decay_weight(date_str, ref_date=REFERENCE_DATE):
    """Peso de decaimiento exponencial. Hace 2 años ≈ 0.30, hace 1 mes ≈ 1.0."""
    days = days_between(date_str, ref_date)
    return exp(-log(2) * days / DECAY_HALF_LIFE)


# ═══════════════════════════════════════════════════════════════════════════
#  1. SISTEMA ELO
# ═══════════════════════════════════════════════════════════════════════════

def compute_elo_ratings(matches):
    """Calcula ratings ELO para cada selección basado en resultados históricos."""
    elo = defaultdict(lambda: ELO_INITIAL)
    history = defaultdict(list)  # team -> [(date, elo)]

    sorted_matches = sorted(matches, key=lambda x: x["date"])

    for m in sorted_matches:
        home = m["home_team"]
        away = m["away_team"]
        hg = m["home_goals"]
        ag = m["away_goals"]

        r_home = elo[home]
        r_away = elo[away]

        # Expectativas (con ventaja local)
        e_home = 1.0 / (1.0 + 10 ** ((r_away - r_home - ELO_HOME_ADVANTAGE) / 400))
        e_away = 1.0 - e_home

        # Resultado real
        if hg > ag:
            s_home, s_away = 1.0, 0.0
        elif hg == ag:
            s_home, s_away = 0.5, 0.5
        else:
            s_home, s_away = 0.0, 1.0

        # Factor de goles (magnitud de victoria amplifica cambio)
        goal_diff = abs(hg - ag)
        if goal_diff <= 1:
            g_factor = 1.0
        elif goal_diff == 2:
            g_factor = 1.5
        else:
            g_factor = (11 + goal_diff) / 8

        # Actualizar ELO
        elo[home] += ELO_K * g_factor * (s_home - e_home)
        elo[away] += ELO_K * g_factor * (s_away - e_away)

        history[home].append((m["date"], elo[home]))
        history[away].append((m["date"], elo[away]))

    return dict(elo), history


def elo_expected_goals(elo_home, elo_away, avg_gf, home_advantage_factor):
    """Convierte diferencia ELO en goles esperados."""
    diff = elo_home - elo_away + ELO_HOME_ADVANTAGE
    # Mapear diferencia ELO a ratio de fuerza
    strength_ratio = 10 ** (diff / 400)
    total_expected = avg_gf * 2  # Total goles esperados en el partido

    lambda_home = total_expected * strength_ratio / (1 + strength_ratio)
    lambda_away = total_expected / (1 + strength_ratio)

    return max(0.3, min(lambda_home, 4.5)), max(0.2, min(lambda_away, 4.0))


# ═══════════════════════════════════════════════════════════════════════════
#  2. PONDERACIÓN TEMPORAL
# ═══════════════════════════════════════════════════════════════════════════

def compute_weighted_stats(matches, ref_date=REFERENCE_DATE):
    """Estadísticas con ponderación temporal: partidos recientes pesan más."""
    teams = defaultdict(lambda: {
        "w_gf": 0, "w_ga": 0, "w_total": 0,
        "w_home_gf": 0, "w_home_ga": 0, "w_home_total": 0,
        "w_away_gf": 0, "w_away_ga": 0, "w_away_total": 0,
        "matches": [],
    })

    for m in sorted(matches, key=lambda x: x["date"]):
        w = decay_weight(m["date"], ref_date)
        home = m["home_team"]
        away = m["away_team"]
        hg = m["home_goals"]
        ag = m["away_goals"]

        # Local
        t = teams[home]
        t["w_gf"] += hg * w
        t["w_ga"] += ag * w
        t["w_total"] += w
        t["w_home_gf"] += hg * w
        t["w_home_ga"] += ag * w
        t["w_home_total"] += w
        t["matches"].append({"date": m["date"], "gf": hg, "ga": ag, "venue": "home", "vs": away, "weight": w})

        # Visitante
        t = teams[away]
        t["w_gf"] += ag * w
        t["w_ga"] += hg * w
        t["w_total"] += w
        t["w_away_gf"] += ag * w
        t["w_away_ga"] += hg * w
        t["w_away_total"] += w
        t["matches"].append({"date": m["date"], "gf": ag, "ga": hg, "venue": "away", "vs": home, "weight": w})

    stats = {}
    for name, d in teams.items():
        if d["w_total"] < 0.1:
            continue
        stats[name] = {
            "avg_gf": d["w_gf"] / d["w_total"],
            "avg_ga": d["w_ga"] / d["w_total"],
            "home_avg_gf": d["w_home_gf"] / max(d["w_home_total"], 0.01),
            "home_avg_ga": d["w_home_ga"] / max(d["w_home_total"], 0.01),
            "away_avg_gf": d["w_away_gf"] / max(d["w_away_total"], 0.01),
            "away_avg_ga": d["w_away_ga"] / max(d["w_away_total"], 0.01),
            "effective_matches": d["w_total"],
        }

    return stats


# ═══════════════════════════════════════════════════════════════════════════
#  3. DIXON-COLES CORRECTION
# ═══════════════════════════════════════════════════════════════════════════

def dixon_coles_tau(h_goals, a_goals, lambda_h, lambda_a, rho=DC_RHO):
    """
    Factor de corrección τ de Dixon-Coles para resultados bajos.
    Ajusta la subestimación de 0-0, 1-0, 0-1, 1-1 en Poisson independiente.
    """
    if h_goals == 0 and a_goals == 0:
        return 1.0 - lambda_h * lambda_a * rho
    elif h_goals == 0 and a_goals == 1:
        return 1.0 + lambda_h * rho
    elif h_goals == 1 and a_goals == 0:
        return 1.0 + lambda_a * rho
    elif h_goals == 1 and a_goals == 1:
        return 1.0 - rho
    else:
        return 1.0


def build_dixon_coles_matrix(lambda_h, lambda_a, rho=DC_RHO):
    """Construye matriz de probabilidades con corrección Dixon-Coles."""
    matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p_indep = poisson_pmf(h, lambda_h) * poisson_pmf(a, lambda_a)
            tau = dixon_coles_tau(h, a, lambda_h, lambda_a, rho)
            matrix[(h, a)] = p_indep * max(tau, 0.001)  # Evitar negativos

    # Normalizar
    total = sum(matrix.values())
    if total > 0:
        matrix = {k: v / total for k, v in matrix.items()}

    return matrix


# ═══════════════════════════════════════════════════════════════════════════
#  4. AJUSTE POR BAJAS
# ═══════════════════════════════════════════════════════════════════════════

def apply_absences(team_name, lambda_attack, lambda_defense):
    """Ajusta lambdas por jugadores clave ausentes."""
    absences = KEY_ABSENCES.get(team_name, [])
    attack_impact = sum(a[1] for a in absences)
    defense_impact = sum(a[2] for a in absences)

    lambda_attack = max(0.3, lambda_attack + attack_impact)
    # Para defensa: impacto positivo = concede más goles (peor defensa)
    lambda_defense_adj = defense_impact  # Se suma al lambda del rival

    return lambda_attack, lambda_defense_adj


# ═══════════════════════════════════════════════════════════════════════════
#  5. CÓRNERS CON ESTILO DE JUEGO
# ═══════════════════════════════════════════════════════════════════════════

def load_corner_stats(path="corner_stats.json"):
    full_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)


def find_in_corners(name, corner_stats):
    if not corner_stats:
        return None
    if name in corner_stats:
        return corner_stats[name]
    for k, v in corner_stats.items():
        if name.lower() in k.lower() or k.lower() in name.lower():
            return v
    return None


def compute_wing_play_index(corner_data):
    """
    Índice de estilo de juego por bandas.
    Equipos con alta ratio córners_favor / goles_marcados
    tienden a atacar más por bandas y generar más córners.
    """
    if not corner_data:
        return 1.0
    cf = corner_data["avg_corners_for"]
    # Ratio córners/partido normalizada (media ≈ 5.0)
    return cf / 5.0


def predict_corners_v3(home_team, away_team, corner_stats):
    """Córners con ajuste por estilo de juego."""
    DEFAULT_CF = 5.0
    DEFAULT_CA = 5.0

    h_data = find_in_corners(home_team, corner_stats)
    a_data = find_in_corners(away_team, corner_stats)
    has_data = h_data is not None or a_data is not None

    # Wing play index modifica la generación de córners
    home_wpi = compute_wing_play_index(h_data)
    away_wpi = compute_wing_play_index(a_data)

    home_cf = h_data["home"]["avg_corners_for"] if h_data else DEFAULT_CF
    home_ca = h_data["home"]["avg_corners_against"] if h_data else DEFAULT_CA
    away_cf = a_data["away"]["avg_corners_for"] if a_data else DEFAULT_CF
    away_ca = a_data["away"]["avg_corners_against"] if a_data else DEFAULT_CA

    # Lambda = (córners a favor * wing_play_index + córners que concede el rival) / 2
    lambda_hc = (home_cf * home_wpi + away_ca) / 2
    lambda_ac = (away_cf * away_wpi + home_ca) / 2

    # Probabilidades
    p_over = {8.5: 0, 9.5: 0, 10.5: 0}
    for hc in range(25):
        for ac in range(25):
            p = poisson_pmf(hc, lambda_hc) * poisson_pmf(ac, lambda_ac)
            total = hc + ac
            for line in p_over:
                if total > line:
                    p_over[line] += p

    return {
        "has_corner_data": has_data,
        "exp_home_corners": round(lambda_hc, 1),
        "exp_away_corners": round(lambda_ac, 1),
        "exp_total_corners": round(lambda_hc + lambda_ac, 1),
        "home_wing_play_idx": round(home_wpi, 2),
        "away_wing_play_idx": round(away_wpi, 2),
        "p_over_8_5": round(p_over[8.5] * 100, 1),
        "p_over_9_5": round(p_over[9.5] * 100, 1),
        "p_over_10_5": round(p_over[10.5] * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  6. MODELO ENSEMBLE
# ═══════════════════════════════════════════════════════════════════════════

def extract_market_probs(matrix):
    """Extrae probabilidades de mercados de una matriz de scores."""
    total = sum(matrix.values())
    if total == 0:
        return {"1": 1/3, "X": 1/3, "2": 1/3, "btts": 0.5, "o25": 0.5, "o15": 0.5}

    p1 = sum(p for (h, a), p in matrix.items() if h > a) / total
    px = sum(p for (h, a), p in matrix.items() if h == a) / total
    p2 = sum(p for (h, a), p in matrix.items() if h < a) / total
    btts = sum(p for (h, a), p in matrix.items() if h > 0 and a > 0) / total
    o25 = sum(p for (h, a), p in matrix.items() if h + a > 2.5) / total
    o15 = sum(p for (h, a), p in matrix.items() if h + a > 1.5) / total

    return {"1": p1, "X": px, "2": p2, "btts": btts, "o25": o25, "o15": o15}


def ensemble_predict(home_team, away_team, weighted_stats, elo_ratings,
                     matches, avg_gf, home_adv, corner_stats):
    """
    Modelo ensemble que combina 3 sub-modelos.
    """
    # ─── Estadísticas ponderadas temporalmente ────────
    h_stats = weighted_stats.get(home_team)
    a_stats = weighted_stats.get(away_team)

    if not h_stats:
        h_stats = {"avg_gf": 1.2, "avg_ga": 1.5, "home_avg_gf": 1.3, "home_avg_ga": 1.4,
                    "away_avg_gf": 1.0, "away_avg_ga": 1.6, "effective_matches": 0}
    if not a_stats:
        a_stats = {"avg_gf": 1.2, "avg_ga": 1.5, "home_avg_gf": 1.3, "home_avg_ga": 1.4,
                    "away_avg_gf": 1.0, "away_avg_ga": 1.6, "effective_matches": 0}

    # ─── Lambda base (Poisson ponderado) ──────────────
    # Ataque/defensa relativos a la media ponderada
    w_total_gf = sum(s["avg_gf"] * s["effective_matches"] for s in weighted_stats.values())
    w_total_mp = sum(s["effective_matches"] for s in weighted_stats.values())
    w_avg_gf = w_total_gf / w_total_mp if w_total_mp > 0 else avg_gf

    h_att = h_stats["home_avg_gf"] / w_avg_gf if w_avg_gf > 0 else 1.0
    h_def = h_stats["home_avg_ga"] / w_avg_gf if w_avg_gf > 0 else 1.0
    a_att = a_stats["away_avg_gf"] / w_avg_gf if w_avg_gf > 0 else 1.0
    a_def = a_stats["away_avg_ga"] / w_avg_gf if w_avg_gf > 0 else 1.0

    lambda_h = h_att * a_def * w_avg_gf * home_adv
    lambda_a = a_att * h_def * w_avg_gf

    # ─── Motivación ───────────────────────────────────
    mot_h = MOTIVATION_FACTORS.get(home_team, 1.0)
    mot_a = MOTIVATION_FACTORS.get(away_team, 1.0)
    lambda_h *= mot_h
    lambda_a *= mot_a

    # ─── Bajas ────────────────────────────────────────
    lambda_h, def_adj_h = apply_absences(home_team, lambda_h, 0)
    lambda_a, def_adj_a = apply_absences(away_team, lambda_a, 0)
    lambda_a += def_adj_h  # Las bajas defensivas del local benefician al visitante
    lambda_h += def_adj_a  # Las bajas defensivas del visitante benefician al local

    lambda_h = max(0.3, min(lambda_h, 5.0))
    lambda_a = max(0.2, min(lambda_a, 4.5))

    # ─── Sub-modelo 1: Poisson puro (ponderado) ──────
    poisson_matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            poisson_matrix[(h, a)] = poisson_pmf(h, lambda_h) * poisson_pmf(a, lambda_a)
    # Normalizar
    ptotal = sum(poisson_matrix.values())
    poisson_matrix = {k: v / ptotal for k, v in poisson_matrix.items()}

    # ─── Sub-modelo 2: Dixon-Coles ───────────────────
    dc_matrix = build_dixon_coles_matrix(lambda_h, lambda_a, DC_RHO)

    # ─── Sub-modelo 3: ELO-based Poisson ─────────────
    elo_h = elo_ratings.get(home_team, ELO_INITIAL)
    elo_a = elo_ratings.get(away_team, ELO_INITIAL)
    elo_lambda_h, elo_lambda_a = elo_expected_goals(elo_h, elo_a, w_avg_gf, home_adv)

    # Aplicar motivación y bajas también al modelo ELO
    elo_lambda_h *= mot_h
    elo_lambda_a *= mot_a
    elo_lambda_h, elo_def_adj_h = apply_absences(home_team, elo_lambda_h, 0)
    elo_lambda_a, elo_def_adj_a = apply_absences(away_team, elo_lambda_a, 0)
    elo_lambda_a += elo_def_adj_h
    elo_lambda_h += elo_def_adj_a
    elo_lambda_h = max(0.3, min(elo_lambda_h, 5.0))
    elo_lambda_a = max(0.2, min(elo_lambda_a, 4.5))

    elo_matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            elo_matrix[(h, a)] = poisson_pmf(h, elo_lambda_h) * poisson_pmf(a, elo_lambda_a)
    etotal = sum(elo_matrix.values())
    elo_matrix = {k: v / etotal for k, v in elo_matrix.items()}

    # ─── Ensemble: promediar matrices con pesos ──────
    ensemble_matrix = {}
    for key in poisson_matrix:
        ensemble_matrix[key] = (
            W_POISSON * poisson_matrix[key]
            + W_DIXON_COLES * dc_matrix[key]
            + W_ELO * elo_matrix[key]
        )

    # Normalizar ensemble
    ens_total = sum(ensemble_matrix.values())
    ensemble_matrix = {k: v / ens_total for k, v in ensemble_matrix.items()}

    # ─── Extraer probabilidades ──────────────────────
    ens = extract_market_probs(ensemble_matrix)
    poi = extract_market_probs(poisson_matrix)
    dc = extract_market_probs(dc_matrix)
    elo_p = extract_market_probs(elo_matrix)

    # Top scores del ensemble
    sorted_scores = sorted(ensemble_matrix.items(), key=lambda x: x[1], reverse=True)
    top_scores = [(f"{h}-{a}", p * 100) for (h, a), p in sorted_scores[:5]]

    # Córners
    corners = predict_corners_v3(home_team, away_team, corner_stats)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "elo_home": round(elo_h),
        "elo_away": round(elo_a),
        "motivation_home": mot_h,
        "motivation_away": mot_a,
        "absences_home": KEY_ABSENCES.get(home_team, []),
        "absences_away": KEY_ABSENCES.get(away_team, []),
        # Lambdas
        "lambda_h_poisson": round(lambda_h, 3),
        "lambda_a_poisson": round(lambda_a, 3),
        "lambda_h_elo": round(elo_lambda_h, 3),
        "lambda_a_elo": round(elo_lambda_a, 3),
        # Sub-modelos
        "poisson": poi,
        "dixon_coles": dc,
        "elo_model": elo_p,
        # ENSEMBLE
        "p_home_win": round(ens["1"] * 100, 1),
        "p_draw": round(ens["X"] * 100, 1),
        "p_away_win": round(ens["2"] * 100, 1),
        "p_btts_yes": round(ens["btts"] * 100, 1),
        "p_btts_no": round((1 - ens["btts"]) * 100, 1),
        "p_over_25": round(ens["o25"] * 100, 1),
        "p_under_25": round((1 - ens["o25"]) * 100, 1),
        "p_over_15": round(ens["o15"] * 100, 1),
        "top_scores": top_scores,
        "corners": corners,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  PRESENTACIÓN
# ═══════════════════════════════════════════════════════════════════════════

def print_ensemble_prediction(pred):
    home = pred["home_team"]
    away = pred["away_team"]

    print(f"\n{'═' * 85}")
    print(f"  {home}  vs  {away}")
    print(f"{'═' * 85}")

    # Metadata
    print(f"  ELO: {home} {pred['elo_home']}  vs  {away} {pred['elo_away']}  "
          f"(diff: {pred['elo_home'] - pred['elo_away']:+d})")
    print(f"  Motivación: {home} {pred['motivation_home']:.2f}x  {away} {pred['motivation_away']:.2f}x")

    if pred["absences_home"]:
        abs_str = ", ".join(f"{a[0]}({a[1]:+.2f}atk)" for a in pred["absences_home"])
        print(f"  Bajas {home}: {abs_str}")
    if pred["absences_away"]:
        abs_str = ", ".join(f"{a[0]}({a[1]:+.2f}atk)" for a in pred["absences_away"])
        print(f"  Bajas {away}: {abs_str}")

    # Lambdas
    print(f"\n  Goles esperados (Poisson):  {pred['lambda_h_poisson']:.2f} - {pred['lambda_a_poisson']:.2f}")
    print(f"  Goles esperados (ELO):      {pred['lambda_h_elo']:.2f} - {pred['lambda_a_elo']:.2f}")

    # Sub-modelos comparados
    poi = pred["poisson"]
    dc = pred["dixon_coles"]
    elo = pred["elo_model"]

    print(f"\n  ┌────────────────┬─────────┬──────────────┬──────────┬────────────┐")
    print(f"  │  Sub-modelo     │  Peso   │  1     X    2 │   BTTS   │   O2.5     │")
    print(f"  ├────────────────┼─────────┼──────────────┼──────────┼────────────┤")
    print(f"  │  Poisson        │  40%    │ {poi['1']*100:4.1f} {poi['X']*100:4.1f} {poi['2']*100:4.1f} │  {poi['btts']*100:4.1f}%  │  {poi['o25']*100:4.1f}%    │")
    print(f"  │  Dixon-Coles    │  30%    │ {dc['1']*100:4.1f} {dc['X']*100:4.1f} {dc['2']*100:4.1f} │  {dc['btts']*100:4.1f}%  │  {dc['o25']*100:4.1f}%    │")
    print(f"  │  ELO            │  30%    │ {elo['1']*100:4.1f} {elo['X']*100:4.1f} {elo['2']*100:4.1f} │  {elo['btts']*100:4.1f}%  │  {elo['o25']*100:4.1f}%    │")
    print(f"  ├────────────────┼─────────┼──────────────┼──────────┼────────────┤")
    print(f"  │  ENSEMBLE       │ 100%    │ {pred['p_home_win']:4.1f} {pred['p_draw']:4.1f} {pred['p_away_win']:4.1f} │  {pred['p_btts_yes']:4.1f}%  │  {pred['p_over_25']:4.1f}%    │")
    print(f"  └────────────────┴─────────┴──────────────┴──────────┴────────────┘")

    # Mercados principales
    print(f"\n  ┌─────────────────────────────────────────────────────────────────────┐")
    print(f"  │  MERCADO 1X2                                                        │")
    print(f"  │  Local (1):  {pred['p_home_win']:5.1f}%   (cuota {prob_to_odds(pred['p_home_win']):5.2f})                │")
    print(f"  │  Empate (X): {pred['p_draw']:5.1f}%   (cuota {prob_to_odds(pred['p_draw']):5.2f})                │")
    print(f"  │  Visit  (2): {pred['p_away_win']:5.1f}%   (cuota {prob_to_odds(pred['p_away_win']):5.2f})                │")
    print(f"  ├─────────────────────────────────────────────────────────────────────┤")
    print(f"  │  BTTS: Sí {pred['p_btts_yes']:5.1f}% ({prob_to_odds(pred['p_btts_yes']):5.2f})  No {pred['p_btts_no']:5.1f}% ({prob_to_odds(pred['p_btts_no']):5.2f})            │")
    print(f"  │  O1.5: {pred['p_over_15']:5.1f}%  O2.5: {pred['p_over_25']:5.1f}% ({prob_to_odds(pred['p_over_25']):5.2f})  U2.5: {pred['p_under_25']:5.1f}% ({prob_to_odds(pred['p_under_25']):5.2f})  │")
    print(f"  ├─────────────────────────────────────────────────────────────────────┤")
    print(f"  │  SCORES MÁS PROBABLES                                               │")
    for score, prob in pred["top_scores"]:
        bar = "█" * int(prob / 2)
        print(f"  │    {score:>5s}  {prob:5.1f}%  {bar:<25s}                    │")

    c = pred["corners"]
    src = "real" if c["has_corner_data"] else "est."
    print(f"  ├─────────────────────────────────────────────────────────────────────┤")
    print(f"  │  CÓRNERS ({src}) — WPI: {home[:10]} {c['home_wing_play_idx']:.2f}  {away[:10]} {c['away_wing_play_idx']:.2f}        │")
    print(f"  │  Esperados: {c['exp_home_corners']:.1f} - {c['exp_away_corners']:.1f}  (Total: {c['exp_total_corners']:.1f})                          │")
    print(f"  │  O8.5: {c['p_over_8_5']:5.1f}%  O9.5: {c['p_over_9_5']:5.1f}%  O10.5: {c['p_over_10_5']:5.1f}%                      │")
    print(f"  └─────────────────────────────────────────────────────────────────────┘")


def determine_bet_suggestion(pred):
    suggestions = []
    if pred["p_home_win"] > 55:
        suggestions.append(f"1 ({pred['p_home_win']:.0f}%)")
    elif pred["p_away_win"] > 55:
        suggestions.append(f"2 ({pred['p_away_win']:.0f}%)")
    elif pred["p_draw"] > 30 and pred["p_home_win"] < 45 and pred["p_away_win"] < 45:
        suggestions.append(f"X ({pred['p_draw']:.0f}%)")

    if pred["p_over_25"] > 60:
        suggestions.append("O2.5")
    elif pred["p_under_25"] > 60:
        suggestions.append("U2.5")

    if pred["p_btts_yes"] > 60:
        suggestions.append("BTTS Sí")
    elif pred["p_btts_no"] > 65:
        suggestions.append("BTTS No")

    c = pred["corners"]
    if c["p_over_10_5"] > 60:
        suggestions.append("O10.5c")
    elif c["p_over_10_5"] < 30:
        suggestions.append("U10.5c")

    return " + ".join(suggestions) if suggestions else "Sin valor claro"


# ═══════════════════════════════════════════════════════════════════════════
#  COMPARACIÓN v2 vs v3
# ═══════════════════════════════════════════════════════════════════════════

def load_v2_predictions(path="predictions.json"):
    """Carga predicciones del modelo v2 para comparación."""
    full_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)


def print_comparison_table(v3_preds, v2_preds):
    """Tabla comparativa v2 (simple) vs v3 (ensemble)."""
    print(f"\n{'═' * 115}")
    print(f"  COMPARACIÓN: MODELO SIMPLE (v2) vs ENSEMBLE AVANZADO (v3)")
    print(f"{'═' * 115}")

    # Build v2 lookup
    v2_map = {}
    if v2_preds:
        for p in v2_preds:
            key = (p["home_team"], p["away_team"])
            v2_map[key] = p

    print(f"\n  {'Partido':<27s} │ {'Modelo':^10s} │ {'1':>6s} {'X':>6s} {'2':>6s} │ {'BTTS':>5s} │ {'O2.5':>5s} │ {'Córn':>5s} │ {'Score':>5s} │ {'Apuesta':<22s}")
    print(f"  {'─' * 27}─┼─{'─' * 10}─┼─{'─' * 20}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 22}")

    for v3 in v3_preds:
        key = (v3["home_team"], v3["away_team"])
        match_str = f"{v3['home_team'][:13]} vs {v3['away_team'][:11]}"
        v2 = v2_map.get(key)

        # v2 row
        if v2:
            v2_score = v2["top_scores"][0][0] if v2.get("top_scores") else "?"
            v2_corners = f"{v2['corners']['exp_total_corners']:.1f}" if v2.get("corners") else "N/A"
            v2_sug = determine_bet_suggestion_v2(v2)
            print(f"  {match_str:<27s} │ {'v2 Simple':^10s} │ {v2['p_home_win']:5.1f}% {v2['p_draw']:5.1f}% {v2['p_away_win']:5.1f}% │ {v2['p_btts_yes']:4.1f}% │ {v2['p_over_25']:4.1f}% │ {v2_corners:>5s} │ {v2_score:>5s} │ {v2_sug:<22s}")

        # v3 row
        v3_score = v3["top_scores"][0][0] if v3.get("top_scores") else "?"
        v3_corners = f"{v3['corners']['exp_total_corners']:.1f}"
        v3_sug = determine_bet_suggestion(v3)
        print(f"  {'':27s} │ {'v3 Ensemb':^10s} │ {v3['p_home_win']:5.1f}% {v3['p_draw']:5.1f}% {v3['p_away_win']:5.1f}% │ {v3['p_btts_yes']:4.1f}% │ {v3['p_over_25']:4.1f}% │ {v3_corners:>5s} │ {v3_score:>5s} │ {v3_sug:<22s}")

        # Delta row
        if v2:
            d1 = v3["p_home_win"] - v2["p_home_win"]
            dx = v3["p_draw"] - v2["p_draw"]
            d2 = v3["p_away_win"] - v2["p_away_win"]
            print(f"  {'':27s} │ {'  Δ delta':^10s} │ {d1:+5.1f}% {dx:+5.1f}% {d2:+5.1f}% │       │       │       │       │")

        print(f"  {'─' * 27}─┼─{'─' * 10}─┼─{'─' * 20}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 5}─┼─{'─' * 22}")


def determine_bet_suggestion_v2(pred):
    """Versión para v2 preds."""
    suggestions = []
    if pred["p_home_win"] > 55:
        suggestions.append(f"1 ({pred['p_home_win']:.0f}%)")
    elif pred["p_away_win"] > 55:
        suggestions.append(f"2 ({pred['p_away_win']:.0f}%)")

    if pred["p_over_25"] > 60:
        suggestions.append("O2.5")
    elif pred["p_under_25"] > 60:
        suggestions.append("U2.5")

    if pred["p_btts_yes"] > 60:
        suggestions.append("BTTS Sí")
    elif pred["p_btts_no"] > 65:
        suggestions.append("BTTS No")

    return " + ".join(suggestions) if suggestions else "Sin valor claro"


def find_team(name, stats):
    if name in stats:
        return name
    name_lower = name.lower()
    for team_name in stats:
        if name_lower in team_name.lower() or team_name.lower() in name_lower:
            return team_name
    return name


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("═" * 85)
    print("  PREDICTOR DE APUESTAS v3 — MODELO ENSEMBLE AVANZADO")
    print("  Poisson(40%) + Dixon-Coles(30%) + ELO(30%)")
    print("  + Decaimiento temporal + Motivación + Bajas + Córners con estilo")
    print("═" * 85)

    # Cargar datos
    print("\n  Cargando datos...")
    data_path = os.path.join(os.path.dirname(__file__), "national_matches.json")
    with open(data_path, encoding="utf-8") as f:
        matches = json.load(f)
    print(f"  {len(matches)} partidos de selecciones cargados")

    # 1. ELO ratings
    print("\n  Calculando ELO ratings...")
    elo_ratings, elo_history = compute_elo_ratings(matches)
    target_teams = ["Bosnia-Herzegovina", "Italy", "Czechia", "Denmark",
                    "Kosovo", "Turkey", "Sweden", "Poland"]
    for t in target_teams:
        r = elo_ratings.get(t, ELO_INITIAL)
        print(f"    {t:<25s} ELO: {r:.0f}")

    # 2. Estadísticas ponderadas temporalmente
    print("\n  Calculando estadísticas con decaimiento temporal...")
    weighted_stats = compute_weighted_stats(matches)
    print(f"  {len(weighted_stats)} selecciones procesadas")

    # 3. Promedios globales (del modelo simple para referencia)
    from predict import compute_national_stats, compute_league_averages
    simple_stats = compute_national_stats(matches)
    avg_gf, avg_ga, home_adv = compute_league_averages(simple_stats)
    print(f"  Media goles/partido: {avg_gf:.3f}")
    print(f"  Ventaja local: {home_adv:.3f}x")

    # 4. Córners
    corner_stats = load_corner_stats()
    if corner_stats:
        print(f"  Datos de córners: {len(corner_stats)} equipos")

    # 5. Partidos
    matches_to_predict = [
        ("Bosnia-Herzegovina", "Italy"),
        ("Czechia", "Denmark"),
        ("Kosovo", "Turkey"),
        ("Sweden", "Poland"),
    ]

    print(f"\n  Prediciendo {len(matches_to_predict)} partidos con modelo ensemble...")

    v3_predictions = []
    for home, away in matches_to_predict:
        h = find_team(home, weighted_stats)
        a = find_team(away, weighted_stats)
        pred = ensemble_predict(h, a, weighted_stats, elo_ratings, matches,
                                avg_gf, home_adv, corner_stats)
        pred["home_team"] = home
        pred["away_team"] = away
        v3_predictions.append(pred)
        print_ensemble_prediction(pred)

    # 6. Comparación v2 vs v3
    v2_preds = load_v2_predictions()
    print_comparison_table(v3_predictions, v2_preds)

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "predictions_v3.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(v3_predictions, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Predicciones v3 guardadas en: {out_path}")

    print(f"\n  DISCLAIMER: Modelo estadístico avanzado con fines educativos.")
    print(f"  No constituye consejo financiero ni de apuestas.\n")


if __name__ == "__main__":
    main()
