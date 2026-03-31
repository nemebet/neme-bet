"""
Predictor de Apuestas v4 — Modelo Ensemble + Contexto Competitivo
═══════════════════════════════════════════════════════════════════

Nuevo en v4:
  - Clasificador de tipo de partido (7 niveles de importancia)
  - Clasificador de nivel de torneo (8 niveles)
  - Ajustes tácticos por contexto (conservadurismo, necesidad de ganar)
  - Presión histórica (penalización por fracasos recientes)
  - Modificadores de córners por tensión táctica
  - Campo CONTEXTO narrativo por partido

Base v3:
  - Poisson(40%) + Dixon-Coles(30%) + ELO(30%)
  - Decaimiento temporal + Motivación + Bajas + Córners con estilo
"""

import json
import os
import sys
from math import exp, lgamma, log
from collections import defaultdict
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN BASE (heredada de v3)
# ═══════════════════════════════════════════════════════════════════════════

MAX_GOALS = 8
REFERENCE_DATE = "2026-03-31"

W_POISSON = 0.40
W_DIXON_COLES = 0.30
W_ELO = 0.30

DC_RHO = -0.13
DECAY_HALF_LIFE = 365

ELO_INITIAL = 1500
ELO_K = 40
ELO_HOME_ADVANTAGE = 100

# ═══════════════════════════════════════════════════════════════════════════
#  1. CLASIFICADOR DE TIPO DE PARTIDO
# ═══════════════════════════════════════════════════════════════════════════

MATCH_TYPES = {
    "FRIENDLY":                 {"factor": 1.00, "label": "Amistoso"},
    "QUALIFIER_NORMAL":         {"factor": 1.05, "label": "Clasificatorio normal"},
    "QUALIFIER_DECISIVE":       {"factor": 1.10, "label": "Clasificatorio decisivo"},
    "PLAYOFF_FIRST_LEG":        {"factor": 1.15, "label": "Playoff ida"},
    "PLAYOFF_SECOND_ADVANTAGE": {"factor": 0.90, "label": "Playoff vuelta (ventaja)"},
    "PLAYOFF_SECOND_BEHIND":    {"factor": 1.20, "label": "Playoff vuelta (desventaja)"},
    "FINAL_DIRECT":             {"factor": 1.25, "label": "Final directa clasificatoria"},
}

# ═══════════════════════════════════════════════════════════════════════════
#  2. CLASIFICADOR DE NIVEL DE TORNEO
# ═══════════════════════════════════════════════════════════════════════════

TOURNAMENT_LEVELS = {
    "FRIENDLY_FIFA":         {"level": 1, "label": "Amistoso FIFA",             "draw_boost": 0.00, "goals_mod": 1.00},
    "NATIONS_LEAGUE_GROUP":  {"level": 2, "label": "Nations League grupo",      "draw_boost": 0.00, "goals_mod": 1.00},
    "NATIONS_LEAGUE_FINAL4": {"level": 3, "label": "Nations League Final Four", "draw_boost": 0.02, "goals_mod": 0.95},
    "WCQ_GROUP":             {"level": 4, "label": "Clasificatorio Mundial",    "draw_boost": 0.01, "goals_mod": 0.98},
    "WCQ_PLAYOFF":           {"level": 5, "label": "Playoff Mundial",           "draw_boost": 0.04, "goals_mod": 0.92},
    "EURO_GROUP":            {"level": 6, "label": "Eurocopa grupo",            "draw_boost": 0.02, "goals_mod": 0.95},
    "EURO_KNOCKOUT":         {"level": 7, "label": "Eurocopa eliminatoria",     "draw_boost": 0.05, "goals_mod": 0.90},
    "WORLD_CUP_FINAL":       {"level": 8, "label": "Final Mundial",             "draw_boost": 0.06, "goals_mod": 0.88},
}

# ═══════════════════════════════════════════════════════════════════════════
#  3. PRESIÓN HISTÓRICA POR EQUIPO
# ═══════════════════════════════════════════════════════════════════════════

# Historial mundialista: cuántos mundiales consecutivos sin clasificar
# Más de 2 = penalización por presión; 0 = sin presión extra
WORLD_CUP_HISTORY = {
    "Bosnia-Herzegovina": {
        "wc_appearances": 1,           # Solo 2014
        "consecutive_missed": 2,       # 2018, 2022
        "last_wc": 2014,
        "pressure_type": "hungry",     # Motivación > presión
        "context": "Solo 1 Mundial en su historia (2014). Juegan en casa con público volcado. Motivación máxima, la presión juega a favor.",
    },
    "Italy": {
        "wc_appearances": 18,
        "consecutive_missed": 2,       # 2018 y 2022 NO clasificados
        "last_wc": 2014,
        "pressure_type": "negative",   # Presión paralizante (trauma)
        "context": "Tetracampeona del mundo pero 2 Mundiales seguidos sin clasificar. Presión extrema negativa — el trauma de 2018 y 2022 pesa. Visitante en eliminatoria directa.",
    },
    "Czechia": {
        "wc_appearances": 10,
        "consecutive_missed": 4,       # 2010, 2014, 2018, 2022
        "last_wc": 2006,
        "pressure_type": "moderate",
        "context": "No van al Mundial desde 2006 (20 años). Generación con hambre pero sin trauma específico. Juegan en casa, ventaja local importante.",
    },
    "Denmark": {
        "wc_appearances": 6,
        "consecutive_missed": 0,       # Fueron en 2022
        "last_wc": 2022,
        "pressure_type": "relaxed",
        "context": "Fueron al Mundial 2022 y semifinalistas Euro 2020. Sin presión excesiva, juegan libres como visitantes.",
    },
    "Kosovo": {
        "wc_appearances": 0,           # NUNCA
        "consecutive_missed": 0,       # Miembro FIFA desde 2016
        "last_wc": None,
        "pressure_type": "historic",   # Momento histórico, toda la nación
        "context": "NUNCA han ido a un Mundial. Miembros FIFA desde 2016. Este partido es histórico para todo el país. Motivación desbordante, el estadio será un infierno.",
    },
    "Turkey": {
        "wc_appearances": 2,
        "consecutive_missed": 5,       # 2006-2022
        "last_wc": 2002,
        "pressure_type": "desperate",
        "context": "No van desde 2002 (24 años). Semifinalistas mundialistas ese año, luego 5 mundiales sin clasificar. Desesperación mezclada con talento actual.",
    },
    "Sweden": {
        "wc_appearances": 12,
        "consecutive_missed": 1,       # Solo 2022
        "last_wc": 2018,
        "pressure_type": "motivated",
        "context": "Cuartofinalistas en 2018 pero no fueron en 2022. Juegan en casa con Isak lesionado, necesitan al público. Motivación alta sin exceso de presión.",
    },
    "Poland": {
        "wc_appearances": 9,
        "consecutive_missed": 0,       # Fueron en 2022
        "last_wc": 2022,
        "pressure_type": "relaxed",
        "context": "Fueron al Mundial 2022 con Lewandowski. Menos presión que el rival, pueden jugar más libres como visitantes. Lewandowski a sus 37 años puede ser su último intento.",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  4. BAJAS DE JUGADORES CLAVE
# ═══════════════════════════════════════════════════════════════════════════

KEY_ABSENCES = {
    "Italy":               [("Barella", -0.15, -0.05)],
    "Bosnia-Herzegovina":  [("Dzeko", -0.25, 0.0)],
    "Denmark":             [("Eriksen", -0.20, 0.0)],
    "Kosovo":              [],
    "Czechia":             [],
    "Turkey":              [],
    "Sweden":              [("Isak", -0.30, 0.0)],
    "Poland":              [("Lewandowski", -0.10, 0.0)],
}

# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIONES BASE
# ═══════════════════════════════════════════════════════════════════════════

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(k * log(max(lam, 1e-10)) - lam - lgamma(k + 1))

def prob_to_odds(p):
    return round(100 / p, 2) if p > 0 else 99.99

def decay_weight(date_str, ref_date=REFERENCE_DATE):
    d1 = datetime.strptime(date_str[:10], "%Y-%m-%d")
    d2 = datetime.strptime(ref_date[:10], "%Y-%m-%d")
    days = abs((d2 - d1).days)
    return exp(-log(2) * days / DECAY_HALF_LIFE)

# ═══════════════════════════════════════════════════════════════════════════
#  ELO
# ═══════════════════════════════════════════════════════════════════════════

def compute_elo_ratings(matches):
    elo = defaultdict(lambda: ELO_INITIAL)
    for m in sorted(matches, key=lambda x: x["date"]):
        home, away = m["home_team"], m["away_team"]
        hg, ag = m["home_goals"], m["away_goals"]
        e_h = 1.0 / (1.0 + 10 ** ((elo[away] - elo[home] - ELO_HOME_ADVANTAGE) / 400))
        s_h = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        gd = abs(hg - ag)
        g = 1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        elo[home] += ELO_K * g * (s_h - e_h)
        elo[away] += ELO_K * g * ((1 - s_h) - (1 - e_h))
    return dict(elo)

def elo_expected_goals(elo_h, elo_a, avg_gf):
    diff = elo_h - elo_a + ELO_HOME_ADVANTAGE
    sr = 10 ** (diff / 400)
    total = avg_gf * 2
    return max(0.3, min(total * sr / (1 + sr), 4.5)), max(0.2, min(total / (1 + sr), 4.0))

# ═══════════════════════════════════════════════════════════════════════════
#  ESTADÍSTICAS PONDERADAS TEMPORALMENTE
# ═══════════════════════════════════════════════════════════════════════════

def compute_weighted_stats(matches):
    teams = defaultdict(lambda: {
        "w_gf": 0, "w_ga": 0, "w_total": 0,
        "w_home_gf": 0, "w_home_ga": 0, "w_home_total": 0,
        "w_away_gf": 0, "w_away_ga": 0, "w_away_total": 0,
    })
    for m in matches:
        w = decay_weight(m["date"])
        home, away = m["home_team"], m["away_team"]
        hg, ag = m["home_goals"], m["away_goals"]
        t = teams[home]
        t["w_gf"] += hg*w; t["w_ga"] += ag*w; t["w_total"] += w
        t["w_home_gf"] += hg*w; t["w_home_ga"] += ag*w; t["w_home_total"] += w
        t = teams[away]
        t["w_gf"] += ag*w; t["w_ga"] += hg*w; t["w_total"] += w
        t["w_away_gf"] += ag*w; t["w_away_ga"] += hg*w; t["w_away_total"] += w

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
#  DIXON-COLES
# ═══════════════════════════════════════════════════════════════════════════

def dixon_coles_tau(h, a, lh, la, rho=DC_RHO):
    if h == 0 and a == 0: return 1.0 - lh * la * rho
    if h == 0 and a == 1: return 1.0 + lh * rho
    if h == 1 and a == 0: return 1.0 + la * rho
    if h == 1 and a == 1: return 1.0 - rho
    return 1.0

def build_dc_matrix(lh, la, rho=DC_RHO):
    m = {}
    for h in range(MAX_GOALS+1):
        for a in range(MAX_GOALS+1):
            m[(h,a)] = poisson_pmf(h, lh) * poisson_pmf(a, la) * max(dixon_coles_tau(h, a, lh, la, rho), 0.001)
    t = sum(m.values())
    return {k: v/t for k, v in m.items()} if t > 0 else m

# ═══════════════════════════════════════════════════════════════════════════
#  BAJAS
# ═══════════════════════════════════════════════════════════════════════════

def apply_absences(team, lam_att, lam_def_adj):
    absences = KEY_ABSENCES.get(team, [])
    att_impact = sum(a[1] for a in absences)
    def_impact = sum(a[2] for a in absences)
    return max(0.3, lam_att + att_impact), def_impact

# ═══════════════════════════════════════════════════════════════════════════
#  5. CONTEXTO COMPETITIVO — EL CORAZÓN DE V4
# ═══════════════════════════════════════════════════════════════════════════

def compute_competitive_context(home_team, away_team, match_type_key, tournament_key):
    """
    Calcula todos los modificadores de contexto competitivo.
    Retorna un dict con ajustes a aplicar sobre las lambdas y probabilidades.
    """
    mt = MATCH_TYPES[match_type_key]
    tl = TOURNAMENT_LEVELS[tournament_key]
    h_hist = WORLD_CUP_HISTORY.get(home_team, {})
    a_hist = WORLD_CUP_HISTORY.get(away_team, {})

    # ─── Modificador de goles por nivel de torneo ────────
    # Partidos de mayor nivel = menos goles (más conservadores)
    goals_modifier = tl["goals_mod"]

    # ─── Boost al empate en eliminatorias ────────────────
    draw_boost = tl["draw_boost"]

    # ─── Presión histórica ───────────────────────────────
    # Afecta la estabilidad del equipo bajo presión
    def pressure_modifier(hist):
        ptype = hist.get("pressure_type", "relaxed")
        missed = hist.get("consecutive_missed", 0)

        if ptype == "historic":
            # Nunca han ido — motivación pura, sin trauma
            return {"attack_mod": 1.12, "defense_mod": 0.97, "label": "HISTÓRICO"}
        elif ptype == "hungry":
            # Han ido pocas veces — hambre de más
            return {"attack_mod": 1.08, "defense_mod": 0.98, "label": "HAMBRIENTO"}
        elif ptype == "desperate":
            # Muchos mundiales sin ir — desesperación
            return {"attack_mod": 1.10, "defense_mod": 1.05, "label": "DESESPERADO"}
        elif ptype == "negative":
            # Fracasos recientes pesan — se agarrotan
            penalty = 0.02 * missed  # 2% por cada mundial consecutivo fallido
            return {"attack_mod": 1.0 - penalty, "defense_mod": 1.0 + penalty, "label": "PRESIÓN NEGATIVA"}
        elif ptype == "motivated":
            return {"attack_mod": 1.05, "defense_mod": 1.0, "label": "MOTIVADO"}
        else:  # relaxed
            return {"attack_mod": 1.0, "defense_mod": 1.0, "label": "RELAJADO"}

    h_pressure = pressure_modifier(h_hist)
    a_pressure = pressure_modifier(a_hist)

    # ─── Ajuste "necesidad de ganar" en final directa ────
    # En FINAL_DIRECT: ambos NECESITAN ganar → más tensión táctica
    tactical_tension = 1.0
    corners_tension_mod = 1.0
    if match_type_key == "FINAL_DIRECT":
        tactical_tension = 1.15   # Más faltas, más interrupciones
        corners_tension_mod = 1.08  # Más córners por presión ofensiva forzada
        # Pero los goles bajan (conservadurismo inicial)
        goals_modifier *= 0.95

    # ─── Contexto narrativo ──────────────────────────────
    h_context = h_hist.get("context", "Sin contexto específico.")
    a_context = a_hist.get("context", "Sin contexto específico.")

    return {
        "match_type": mt,
        "tournament": tl,
        "goals_modifier": goals_modifier,
        "draw_boost": draw_boost,
        "home_pressure": h_pressure,
        "away_pressure": a_pressure,
        "tactical_tension": tactical_tension,
        "corners_tension_mod": corners_tension_mod,
        "home_context": h_context,
        "away_context": a_context,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  CÓRNERS CON ESTILO + CONTEXTO
# ═══════════════════════════════════════════════════════════════════════════

def load_corner_stats(path="corner_stats.json"):
    full_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)

def find_in_corners(name, cs):
    if not cs: return None
    if name in cs: return cs[name]
    for k, v in cs.items():
        if name.lower() in k.lower() or k.lower() in name.lower():
            return v
    return None

def predict_corners_v4(home, away, corner_stats, ctx):
    DEF = 5.0
    h_data = find_in_corners(home, corner_stats)
    a_data = find_in_corners(away, corner_stats)
    has_data = h_data is not None or a_data is not None

    # Wing play index
    h_wpi = (h_data["avg_corners_for"] / 5.0) if h_data else 1.0
    a_wpi = (a_data["avg_corners_for"] / 5.0) if a_data else 1.0

    h_cf = h_data["home"]["avg_corners_for"] if h_data else DEF
    h_ca = h_data["home"]["avg_corners_against"] if h_data else DEF
    a_cf = a_data["away"]["avg_corners_for"] if a_data else DEF
    a_ca = a_data["away"]["avg_corners_against"] if a_data else DEF

    lambda_hc = (h_cf * h_wpi + a_ca) / 2
    lambda_ac = (a_cf * a_wpi + h_ca) / 2

    # Aplicar modificador de tensión táctica del contexto
    tension = ctx["corners_tension_mod"]
    lambda_hc *= tension
    lambda_ac *= tension

    p_over = {8.5: 0, 9.5: 0, 10.5: 0}
    for hc in range(25):
        for ac in range(25):
            p = poisson_pmf(hc, lambda_hc) * poisson_pmf(ac, lambda_ac)
            t = hc + ac
            for line in p_over:
                if t > line:
                    p_over[line] += p

    return {
        "has_corner_data": has_data,
        "exp_home_corners": round(lambda_hc, 1),
        "exp_away_corners": round(lambda_ac, 1),
        "exp_total_corners": round(lambda_hc + lambda_ac, 1),
        "home_wpi": round(h_wpi, 2),
        "away_wpi": round(a_wpi, 2),
        "tension_mod": tension,
        "p_over_8_5": round(p_over[8.5] * 100, 1),
        "p_over_9_5": round(p_over[9.5] * 100, 1),
        "p_over_10_5": round(p_over[10.5] * 100, 1),
    }

# ═══════════════════════════════════════════════════════════════════════════
#  UTILIDADES DE MERCADO
# ═══════════════════════════════════════════════════════════════════════════

def extract_markets(matrix):
    t = sum(matrix.values())
    if t == 0:
        return {"1": 1/3, "X": 1/3, "2": 1/3, "btts": 0.5, "o25": 0.5, "o15": 0.5}
    return {
        "1":    sum(p for (h,a),p in matrix.items() if h > a) / t,
        "X":    sum(p for (h,a),p in matrix.items() if h == a) / t,
        "2":    sum(p for (h,a),p in matrix.items() if h < a) / t,
        "btts": sum(p for (h,a),p in matrix.items() if h > 0 and a > 0) / t,
        "o25":  sum(p for (h,a),p in matrix.items() if h + a > 2.5) / t,
        "o15":  sum(p for (h,a),p in matrix.items() if h + a > 1.5) / t,
    }

# ═══════════════════════════════════════════════════════════════════════════
#  6. MODELO ENSEMBLE v4 CON CONTEXTO
# ═══════════════════════════════════════════════════════════════════════════

def ensemble_predict_v4(home, away, w_stats, elo_ratings, avg_gf, home_adv,
                        corner_stats, match_type, tournament):
    """Ensemble v4: v3 base + capa de contexto competitivo."""

    # ─── Contexto competitivo ────────────────────────────
    ctx = compute_competitive_context(home, away, match_type, tournament)

    h_s = w_stats.get(home) or {"avg_gf":1.2,"avg_ga":1.5,"home_avg_gf":1.3,"home_avg_ga":1.4,"away_avg_gf":1.0,"away_avg_ga":1.6,"effective_matches":0}
    a_s = w_stats.get(away) or {"avg_gf":1.2,"avg_ga":1.5,"home_avg_gf":1.3,"home_avg_ga":1.4,"away_avg_gf":1.0,"away_avg_ga":1.6,"effective_matches":0}

    # Media ponderada global
    w_gf_total = sum(s["avg_gf"]*s["effective_matches"] for s in w_stats.values())
    w_mp_total = sum(s["effective_matches"] for s in w_stats.values())
    w_avg = w_gf_total / w_mp_total if w_mp_total > 0 else avg_gf

    # Ratings base
    h_att = h_s["home_avg_gf"] / w_avg if w_avg > 0 else 1.0
    h_def = h_s["home_avg_ga"] / w_avg if w_avg > 0 else 1.0
    a_att = a_s["away_avg_gf"] / w_avg if w_avg > 0 else 1.0
    a_def = a_s["away_avg_ga"] / w_avg if w_avg > 0 else 1.0

    # Lambdas base
    lh = h_att * a_def * w_avg * home_adv
    la = a_att * h_def * w_avg

    # ─── Aplicar presión histórica ───────────────────────
    hp = ctx["home_pressure"]
    ap = ctx["away_pressure"]
    lh *= hp["attack_mod"]
    la *= hp["defense_mod"]  # Si el local tiene mala defensa bajo presión
    la *= ap["attack_mod"]
    lh *= ap["defense_mod"]

    # ─── Aplicar modificador de goles por nivel torneo ───
    lh *= ctx["goals_modifier"]
    la *= ctx["goals_modifier"]

    # ─── Bajas ───────────────────────────────────────────
    lh, d_h = apply_absences(home, lh, 0)
    la, d_a = apply_absences(away, la, 0)
    la += d_h
    lh += d_a

    lh = max(0.3, min(lh, 5.0))
    la = max(0.2, min(la, 4.5))

    # ─── Sub-modelo 1: Poisson ───────────────────────────
    poi_m = {}
    for h in range(MAX_GOALS+1):
        for a in range(MAX_GOALS+1):
            poi_m[(h,a)] = poisson_pmf(h, lh) * poisson_pmf(a, la)
    pt = sum(poi_m.values())
    poi_m = {k: v/pt for k, v in poi_m.items()}

    # ─── Sub-modelo 2: Dixon-Coles ──────────────────────
    # En finales directas, usar rho más negativo (más empates/resultados bajos)
    rho = DC_RHO
    if match_type == "FINAL_DIRECT":
        rho = -0.18  # Más correlación en resultados bajos
    dc_m = build_dc_matrix(lh, la, rho)

    # ─── Sub-modelo 3: ELO ──────────────────────────────
    elo_h = elo_ratings.get(home, ELO_INITIAL)
    elo_a = elo_ratings.get(away, ELO_INITIAL)
    elh, ela = elo_expected_goals(elo_h, elo_a, w_avg)
    # Aplicar contexto al ELO también
    elh *= hp["attack_mod"] * ap["defense_mod"] * ctx["goals_modifier"]
    ela *= ap["attack_mod"] * hp["defense_mod"] * ctx["goals_modifier"]
    elh, ed_h = apply_absences(home, elh, 0)
    ela, ed_a = apply_absences(away, ela, 0)
    ela += ed_h; elh += ed_a
    elh = max(0.3, min(elh, 5.0))
    ela = max(0.2, min(ela, 4.5))

    elo_m = {}
    for h in range(MAX_GOALS+1):
        for a in range(MAX_GOALS+1):
            elo_m[(h,a)] = poisson_pmf(h, elh) * poisson_pmf(a, ela)
    et = sum(elo_m.values())
    elo_m = {k: v/et for k, v in elo_m.items()}

    # ─── Ensemble ────────────────────────────────────────
    ens_m = {}
    for key in poi_m:
        ens_m[key] = W_POISSON*poi_m[key] + W_DIXON_COLES*dc_m[key] + W_ELO*elo_m[key]

    # Aplicar draw_boost del nivel de torneo
    db = ctx["draw_boost"]
    if db > 0:
        for key in ens_m:
            h, a = key
            if h == a:
                ens_m[key] *= (1 + db * 5)  # Boost empates
            else:
                ens_m[key] *= (1 - db)       # Reducir ligeramente otros

    # Normalizar
    ens_t = sum(ens_m.values())
    ens_m = {k: v/ens_t for k, v in ens_m.items()}

    # Extraer mercados
    ens = extract_markets(ens_m)
    poi = extract_markets(poi_m)
    dc = extract_markets(dc_m)
    elo_p = extract_markets(elo_m)

    sorted_scores = sorted(ens_m.items(), key=lambda x: x[1], reverse=True)
    top_scores = [(f"{h}-{a}", p*100) for (h,a), p in sorted_scores[:5]]

    # Córners con contexto
    corners = predict_corners_v4(home, away, corner_stats, ctx)

    # Narrativa de contexto
    context_narrative = (
        f"FINAL DIRECTA (nivel {ctx['tournament']['level']}/8) — "
        f"{home}: {hp['label']} | {away}: {ap['label']} — "
        f"Goles ×{ctx['goals_modifier']:.2f} | Empate boost +{db*100:.0f}% | "
        f"Dixon-Coles ρ={rho:.2f}"
    )

    return {
        "home_team": home,
        "away_team": away,
        "elo_home": round(elo_h), "elo_away": round(elo_a),
        "home_pressure": hp, "away_pressure": ap,
        "context": ctx,
        "context_narrative": context_narrative,
        "home_wc_context": ctx["home_context"],
        "away_wc_context": ctx["away_context"],
        "absences_home": KEY_ABSENCES.get(home, []),
        "absences_away": KEY_ABSENCES.get(away, []),
        "lambda_h": round(lh, 3), "lambda_a": round(la, 3),
        "lambda_h_elo": round(elh, 3), "lambda_a_elo": round(ela, 3),
        "sub_poisson": poi, "sub_dc": dc, "sub_elo": elo_p,
        "p_home_win": round(ens["1"]*100, 1),
        "p_draw": round(ens["X"]*100, 1),
        "p_away_win": round(ens["2"]*100, 1),
        "p_btts_yes": round(ens["btts"]*100, 1),
        "p_btts_no": round((1-ens["btts"])*100, 1),
        "p_over_25": round(ens["o25"]*100, 1),
        "p_under_25": round((1-ens["o25"])*100, 1),
        "p_over_15": round(ens["o15"]*100, 1),
        "top_scores": top_scores,
        "corners": corners,
    }

# ═══════════════════════════════════════════════════════════════════════════
#  PRESENTACIÓN
# ═══════════════════════════════════════════════════════════════════════════

def print_v4_prediction(p):
    home, away = p["home_team"], p["away_team"]
    hp, ap = p["home_pressure"], p["away_pressure"]

    print(f"\n{'═' * 90}")
    print(f"  {home}  vs  {away}")
    print(f"  CONTEXTO: {p['context_narrative']}")
    print(f"{'═' * 90}")

    # World Cup context
    print(f"  ● {home}: {p['home_wc_context']}")
    print(f"  ● {away}: {p['away_wc_context']}")

    # Metadata compacta
    print(f"\n  ELO: {p['elo_home']} vs {p['elo_away']} ({p['elo_home']-p['elo_away']:+d})")
    print(f"  Presión: {home} → {hp['label']} (atk ×{hp['attack_mod']:.2f} def ×{hp['defense_mod']:.2f})")
    print(f"  Presión: {away} → {ap['label']} (atk ×{ap['attack_mod']:.2f} def ×{ap['defense_mod']:.2f})")

    if p["absences_home"]:
        print(f"  Bajas {home}: {', '.join(f'{a[0]}({a[1]:+.2f})' for a in p['absences_home'])}")
    if p["absences_away"]:
        print(f"  Bajas {away}: {', '.join(f'{a[0]}({a[1]:+.2f})' for a in p['absences_away'])}")

    print(f"\n  λ Poisson: {p['lambda_h']:.2f} - {p['lambda_a']:.2f}  |  λ ELO: {p['lambda_h_elo']:.2f} - {p['lambda_a_elo']:.2f}")

    # Sub-modelos
    poi, dc, elo = p["sub_poisson"], p["sub_dc"], p["sub_elo"]
    print(f"\n  ┌─────────────────┬────────┬───────────────────┬──────────┬──────────┐")
    print(f"  │  Sub-modelo      │  Peso  │   1     X     2   │   BTTS   │   O2.5   │")
    print(f"  ├─────────────────┼────────┼───────────────────┼──────────┼──────────┤")
    print(f"  │  Poisson         │  40%   │ {poi['1']*100:5.1f} {poi['X']*100:5.1f} {poi['2']*100:5.1f} │  {poi['btts']*100:5.1f}% │  {poi['o25']*100:5.1f}% │")
    print(f"  │  Dixon-Coles     │  30%   │ {dc['1']*100:5.1f} {dc['X']*100:5.1f} {dc['2']*100:5.1f} │  {dc['btts']*100:5.1f}% │  {dc['o25']*100:5.1f}% │")
    print(f"  │  ELO             │  30%   │ {elo['1']*100:5.1f} {elo['X']*100:5.1f} {elo['2']*100:5.1f} │  {elo['btts']*100:5.1f}% │  {elo['o25']*100:5.1f}% │")
    print(f"  ├─────────────────┼────────┼───────────────────┼──────────┼──────────┤")
    print(f"  │  ENSEMBLE v4     │ 100%   │ {p['p_home_win']:5.1f} {p['p_draw']:5.1f} {p['p_away_win']:5.1f} │  {p['p_btts_yes']:5.1f}% │  {p['p_over_25']:5.1f}% │")
    print(f"  └─────────────────┴────────┴───────────────────┴──────────┴──────────┘")

    # Mercados
    print(f"\n  ┌───────────────────────────────────────────────────────────────────────┐")
    print(f"  │  1X2: Local {p['p_home_win']:5.1f}% ({prob_to_odds(p['p_home_win']):5.2f})  "
          f"Empate {p['p_draw']:5.1f}% ({prob_to_odds(p['p_draw']):5.2f})  "
          f"Visit {p['p_away_win']:5.1f}% ({prob_to_odds(p['p_away_win']):5.2f})  │")
    print(f"  │  BTTS Sí: {p['p_btts_yes']:5.1f}% ({prob_to_odds(p['p_btts_yes']):5.2f})   No: {p['p_btts_no']:5.1f}% ({prob_to_odds(p['p_btts_no']):5.2f})                          │")
    print(f"  │  O1.5: {p['p_over_15']:5.1f}%   O2.5: {p['p_over_25']:5.1f}% ({prob_to_odds(p['p_over_25']):5.2f})   U2.5: {p['p_under_25']:5.1f}% ({prob_to_odds(p['p_under_25']):5.2f})               │")
    print(f"  ├───────────────────────────────────────────────────────────────────────┤")
    for sc, pr in p["top_scores"]:
        bar = "█" * int(pr/2)
        print(f"  │  {sc:>5s}  {pr:5.1f}%  {bar:<30s}                      │")

    c = p["corners"]
    src = "real" if c["has_corner_data"] else "est."
    print(f"  ├───────────────────────────────────────────────────────────────────────┤")
    print(f"  │  CÓRNERS ({src}, tensión ×{c['tension_mod']:.2f})  WPI: {home[:8]} {c['home_wpi']:.2f} / {away[:8]} {c['away_wpi']:.2f}       │")
    print(f"  │  Esperados: {c['exp_home_corners']:.1f} - {c['exp_away_corners']:.1f}  (Total: {c['exp_total_corners']:.1f})                                │")
    print(f"  │  O8.5: {c['p_over_8_5']:5.1f}%   O9.5: {c['p_over_9_5']:5.1f}%   O10.5: {c['p_over_10_5']:5.1f}%                            │")
    print(f"  └───────────────────────────────────────────────────────────────────────┘")


def bet_suggestion(p):
    s = []
    if p["p_home_win"] > 55: s.append(f"1 ({p['p_home_win']:.0f}%)")
    elif p["p_away_win"] > 55: s.append(f"2 ({p['p_away_win']:.0f}%)")
    elif p["p_draw"] > 30 and p["p_home_win"] < 45 and p["p_away_win"] < 45:
        s.append(f"X ({p['p_draw']:.0f}%)")
    if p["p_over_25"] > 60: s.append("O2.5")
    elif p["p_under_25"] > 60: s.append("U2.5")
    if p["p_btts_yes"] > 60: s.append("BTTS Sí")
    elif p["p_btts_no"] > 65: s.append("BTTS No")
    c = p["corners"]
    if c["p_over_10_5"] > 60: s.append("O10.5c")
    elif c["p_over_10_5"] < 30: s.append("U10.5c")
    return " + ".join(s) if s else "Sin valor claro"


def print_comparison(v4_preds, v3_preds):
    print(f"\n{'═' * 120}")
    print(f"  COMPARACIÓN: v3 (Ensemble) vs v4 (Ensemble + Contexto Competitivo)")
    print(f"  Impacto de: Presión histórica | Nivel torneo | Goles ×modifier | Empate boost | Dixon-Coles ρ ajustado")
    print(f"{'═' * 120}")

    v3_map = {}
    if v3_preds:
        for p in v3_preds:
            v3_map[(p["home_team"], p["away_team"])] = p

    print(f"\n  {'Partido':<28s} │ {'Ver':^5s} │ {'1':>6s} {'X':>6s} {'2':>6s} │ {'BTTS':>5s} │ {'O2.5':>5s} │ {'Crn':>4s} │ {'Score':>5s} │ {'Contexto clave':<30s}")
    print(f"  {'─'*28}─┼─{'─'*5}─┼─{'─'*20}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*4}─┼─{'─'*5}─┼─{'─'*30}")

    for v4 in v4_preds:
        key = (v4["home_team"], v4["away_team"])
        m = f"{v4['home_team'][:14]} vs {v4['away_team'][:11]}"
        v3 = v3_map.get(key)

        if v3:
            v3s = v3["top_scores"][0][0] if v3.get("top_scores") else "?"
            v3c = f"{v3['corners']['exp_total_corners']:.0f}" if v3.get("corners") else "?"
            print(f"  {m:<28s} │ {'v3':^5s} │ {v3['p_home_win']:5.1f}% {v3['p_draw']:5.1f}% {v3['p_away_win']:5.1f}% │ {v3['p_btts_yes']:4.1f}% │ {v3['p_over_25']:4.1f}% │ {v3c:>4s} │ {v3s:>5s} │")

        v4s = v4["top_scores"][0][0] if v4.get("top_scores") else "?"
        v4c = f"{v4['corners']['exp_total_corners']:.0f}"
        hp = v4["home_pressure"]["label"]
        ap = v4["away_pressure"]["label"]
        ctx_short = f"{hp} vs {ap}"
        sug = bet_suggestion(v4)
        print(f"  {'':28s} │ {'v4':^5s} │ {v4['p_home_win']:5.1f}% {v4['p_draw']:5.1f}% {v4['p_away_win']:5.1f}% │ {v4['p_btts_yes']:4.1f}% │ {v4['p_over_25']:4.1f}% │ {v4c:>4s} │ {v4s:>5s} │ {ctx_short:<30s}")

        if v3:
            d1 = v4["p_home_win"] - v3["p_home_win"]
            dx = v4["p_draw"] - v3["p_draw"]
            d2 = v4["p_away_win"] - v3["p_away_win"]
            print(f"  {'':28s} │ {'Δ':^5s} │ {d1:+5.1f}% {dx:+5.1f}% {d2:+5.1f}% │       │       │      │       │ → {sug:<28s}")

        print(f"  {'─'*28}─┼─{'─'*5}─┼─{'─'*20}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*4}─┼─{'─'*5}─┼─{'─'*30}")

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def find_team(name, stats):
    if name in stats: return name
    nl = name.lower()
    for tn in stats:
        if nl in tn.lower() or tn.lower() in nl: return tn
    return name

def main():
    print("═" * 90)
    print("  PREDICTOR DE APUESTAS v4 — ENSEMBLE + CONTEXTO COMPETITIVO")
    print("  Poisson(40%) + Dixon-Coles(30%) + ELO(30%)")
    print("  + Presión histórica | Nivel torneo | Tensión táctica | Córners contextuales")
    print("═" * 90)

    # Cargar datos
    print("\n  Cargando datos...")
    data_path = os.path.join(os.path.dirname(__file__), "national_matches.json")
    with open(data_path, encoding="utf-8") as f:
        matches = json.load(f)
    print(f"  {len(matches)} partidos cargados")

    # ELO
    print("\n  ELO ratings:")
    elo = compute_elo_ratings(matches)
    targets = ["Bosnia-Herzegovina","Italy","Czechia","Denmark","Kosovo","Turkey","Sweden","Poland"]
    for t in targets:
        print(f"    {t:<25s} {elo.get(t, ELO_INITIAL):.0f}")

    # Weighted stats
    print("\n  Estadísticas con decaimiento temporal...")
    w_stats = compute_weighted_stats(matches)

    # Averages
    from predict import compute_national_stats, compute_league_averages
    simple = compute_national_stats(matches)
    avg_gf, _, home_adv = compute_league_averages(simple)
    print(f"  Media goles: {avg_gf:.3f}  |  Ventaja local: {home_adv:.3f}x")

    # Córners
    corner_stats = load_corner_stats()
    if corner_stats:
        print(f"  Córners: {len(corner_stats)} equipos con datos reales")

    # Partidos — TODOS son FINAL_DIRECT + WCQ_PLAYOFF
    games = [
        ("Bosnia-Herzegovina", "Italy"),
        ("Czechia", "Denmark"),
        ("Kosovo", "Turkey"),
        ("Sweden", "Poland"),
    ]

    print(f"\n  Tipo: FINAL DIRECTA CLASIFICATORIA (Playoff WCQ, nivel 5/8)")
    print(f"  Ajustes activos: goles ×0.87 | empate +4% boost | ρ Dixon-Coles = -0.18")
    print(f"  Tensión córners ×1.08 | Presión histórica por equipo")

    v4_preds = []
    for home, away in games:
        h = find_team(home, w_stats)
        a = find_team(away, w_stats)
        pred = ensemble_predict_v4(h, a, w_stats, elo, avg_gf, home_adv,
                                   corner_stats, "FINAL_DIRECT", "WCQ_PLAYOFF")
        pred["home_team"] = home
        pred["away_team"] = away
        v4_preds.append(pred)
        print_v4_prediction(pred)

    # Comparar v3 vs v4
    v3_path = os.path.join(os.path.dirname(__file__), "predictions_v3.json")
    v3_preds = None
    if os.path.exists(v3_path):
        with open(v3_path, encoding="utf-8") as f:
            v3_preds = json.load(f)

    print_comparison(v4_preds, v3_preds)

    # Guardar
    out = os.path.join(os.path.dirname(__file__), "predictions_v4.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(v4_preds, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Guardado en: {out}")
    print(f"\n  DISCLAIMER: Modelo estadístico con fines educativos. No es consejo de apuestas.\n")

if __name__ == "__main__":
    main()
