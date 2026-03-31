"""
Predictor de Apuestas de Fútbol - Modelo de Poisson
Predice resultados usando distribución de Poisson con medias de ataque/defensa
ajustadas por factor local/visitante.

Fuentes de datos:
  - national_matches.json: partidos de selecciones (WCQ + Nations League)
  - team_stats.json: estadísticas de clubes (ligas + Champions)
"""

import json
import os
import sys
from math import exp, lgamma
from collections import defaultdict


# ─── Configuración ──────────────────────────────────────────────────────────

MAX_GOALS = 8       # Máximo de goles a considerar en la distribución
FORM_WEIGHT = 0.20  # Peso del factor de forma reciente
RECENCY_WEIGHT = 0.10  # Bonus/penalty por partidos recientes vs antiguos

# ─── Funciones auxiliares ───────────────────────────────────────────────────

def poisson_pmf(k, lam):
    """Probabilidad de Poisson: P(X=k) dado lambda."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    from math import log
    return exp(k * log(max(lam, 1e-10)) - lam - lgamma(k + 1))


def prob_to_odds(prob_pct):
    """Convierte probabilidad (%) a cuotas decimales europeas."""
    if prob_pct <= 0:
        return 99.99
    return round(100 / prob_pct, 2)


def load_corner_stats(path="corner_stats.json"):
    """Carga estadísticas de córners si están disponibles."""
    full_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)


def predict_corners(home_team, away_team, corner_stats, avg_total=10.5):
    """
    Predice córners usando Poisson con medias de córners por equipo.
    Si no hay datos de córners, usa estimaciones basadas en promedios de ligas europeas.
    Media típica: ~10.5 córners totales por partido en selecciones UEFA.
    """
    # Defaults basados en promedios de selecciones europeas
    DEFAULT_HOME_CF = 5.5  # Córners a favor local
    DEFAULT_AWAY_CF = 4.5  # Córners a favor visitante
    DEFAULT_HOME_CA = 4.5  # Córners en contra local
    DEFAULT_AWAY_CA = 5.5  # Córners en contra visitante

    home_cf = DEFAULT_HOME_CF
    home_ca = DEFAULT_HOME_CA
    away_cf = DEFAULT_AWAY_CF
    away_ca = DEFAULT_AWAY_CA
    has_data = False

    if corner_stats:
        # Buscar equipo por nombre exacto o parcial
        def find_in_corners(name):
            if name in corner_stats:
                return corner_stats[name]
            for k, v in corner_stats.items():
                if name.lower() in k.lower() or k.lower() in name.lower():
                    return v
            return None

        h_data = find_in_corners(home_team)
        a_data = find_in_corners(away_team)

        if h_data:
            home_cf = h_data["home"]["avg_corners_for"]
            home_ca = h_data["home"]["avg_corners_against"]
            has_data = True
        if a_data:
            away_cf = a_data["away"]["avg_corners_for"]
            away_ca = a_data["away"]["avg_corners_against"]
            has_data = True

    # Lambda de córners: promedio de lo que genera el equipo + lo que concede el rival
    lambda_home_corners = (home_cf + away_ca) / 2
    lambda_away_corners = (away_cf + home_ca) / 2
    lambda_total = lambda_home_corners + lambda_away_corners

    # Probabilidades Over/Under córners usando Poisson
    p_over_85 = 0
    p_over_95 = 0
    p_over_105 = 0
    for hc in range(25):
        for ac in range(25):
            p = poisson_pmf(hc, lambda_home_corners) * poisson_pmf(ac, lambda_away_corners)
            total = hc + ac
            if total > 8.5:
                p_over_85 += p
            if total > 9.5:
                p_over_95 += p
            if total > 10.5:
                p_over_105 += p

    return {
        "has_corner_data": has_data,
        "exp_home_corners": round(lambda_home_corners, 1),
        "exp_away_corners": round(lambda_away_corners, 1),
        "exp_total_corners": round(lambda_total, 1),
        "p_over_8_5": round(p_over_85 * 100, 1),
        "p_under_8_5": round((1 - p_over_85) * 100, 1),
        "p_over_9_5": round(p_over_95 * 100, 1),
        "p_under_9_5": round((1 - p_over_95) * 100, 1),
        "p_over_10_5": round(p_over_105 * 100, 1),
        "p_under_10_5": round((1 - p_over_105) * 100, 1),
    }


# ─── Carga y cálculo de estadísticas de selecciones ────────────────────────

def load_national_matches(path="national_matches.json"):
    """Carga partidos de selecciones nacionales scrapeados de Wikipedia."""
    full_path = os.path.join(os.path.dirname(__file__), path)
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)


def compute_national_stats(matches):
    """Calcula estadísticas por selección a partir de los partidos."""
    teams = defaultdict(lambda: {
        "matches_played": 0,
        "wins": 0, "draws": 0, "losses": 0,
        "goals_scored": 0, "goals_conceded": 0,
        "home": {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0},
        "away": {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0},
        "recent_matches": [],
    })

    sorted_matches = sorted(matches, key=lambda x: x["date"])

    for match in sorted_matches:
        home = match["home_team"]
        away = match["away_team"]
        hg = match["home_goals"]
        ag = match["away_goals"]
        date = match["date"]

        # Equipo local
        t = teams[home]
        t["matches_played"] += 1
        t["goals_scored"] += hg
        t["goals_conceded"] += ag
        t["home"]["played"] += 1
        t["home"]["gf"] += hg
        t["home"]["ga"] += ag
        if hg > ag:
            t["wins"] += 1; t["home"]["wins"] += 1; result_h = "W"
        elif hg == ag:
            t["draws"] += 1; t["home"]["draws"] += 1; result_h = "D"
        else:
            t["losses"] += 1; t["home"]["losses"] += 1; result_h = "L"
        t["recent_matches"].append({"date": date, "result": result_h, "gf": hg, "ga": ag, "venue": "home", "vs": away})

        # Equipo visitante
        t = teams[away]
        t["matches_played"] += 1
        t["goals_scored"] += ag
        t["goals_conceded"] += hg
        t["away"]["played"] += 1
        t["away"]["gf"] += ag
        t["away"]["ga"] += hg
        if ag > hg:
            t["wins"] += 1; t["away"]["wins"] += 1; result_a = "W"
        elif ag == hg:
            t["draws"] += 1; t["away"]["draws"] += 1; result_a = "D"
        else:
            t["losses"] += 1; t["away"]["losses"] += 1; result_a = "L"
        t["recent_matches"].append({"date": date, "result": result_a, "gf": ag, "ga": hg, "venue": "away", "vs": home})

    # Convertir a formato con promedios
    stats = {}
    for name, data in teams.items():
        mp = data["matches_played"]
        if mp == 0:
            continue
        hp = max(data["home"]["played"], 1)
        ap = max(data["away"]["played"], 1)

        # Forma: últimos 5 partidos
        last5 = data["recent_matches"][-5:]
        form_seq = "".join(m["result"] for m in last5)
        form_pts = sum(3 if m["result"] == "W" else 1 if m["result"] == "D" else 0 for m in last5)
        form_max = len(last5) * 3
        form_pct = (form_pts / form_max * 100) if form_max > 0 else 50.0

        stats[name] = {
            "team": name,
            "matches_played": mp,
            "wins": data["wins"], "draws": data["draws"], "losses": data["losses"],
            "avg_goals_scored": data["goals_scored"] / mp,
            "avg_goals_conceded": data["goals_conceded"] / mp,
            "home": {
                "played": data["home"]["played"],
                "avg_gf": data["home"]["gf"] / hp,
                "avg_ga": data["home"]["ga"] / hp,
                "win_rate": data["home"]["wins"] / hp * 100,
            },
            "away": {
                "played": data["away"]["played"],
                "avg_gf": data["away"]["gf"] / ap,
                "avg_ga": data["away"]["ga"] / ap,
                "win_rate": data["away"]["wins"] / ap * 100,
            },
            "form_last_5": {
                "sequence": form_seq,
                "points": form_pts,
                "percentage": round(form_pct, 1),
            },
            "recent_matches": data["recent_matches"][-5:],
        }

    return stats


def compute_league_averages(stats):
    """Calcula promedios globales para normalización."""
    total_gf = sum(t["avg_goals_scored"] * t["matches_played"] for t in stats.values())
    total_mp = sum(t["matches_played"] for t in stats.values())

    avg_gf = total_gf / total_mp if total_mp > 0 else 1.40
    avg_ga = avg_gf  # Simétrico

    # Ventaja local
    home_gf = sum(t["home"]["avg_gf"] * t["home"]["played"] for t in stats.values())
    home_mp = sum(t["home"]["played"] for t in stats.values())
    away_gf = sum(t["away"]["avg_gf"] * t["away"]["played"] for t in stats.values())
    away_mp = sum(t["away"]["played"] for t in stats.values())

    home_avg = home_gf / home_mp if home_mp > 0 else avg_gf
    away_avg = away_gf / away_mp if away_mp > 0 else avg_gf
    home_advantage = home_avg / away_avg if away_avg > 0 else 1.25

    return avg_gf, avg_ga, home_advantage


# ─── Ratings de equipos ────────────────────────────────────────────────────

def get_team_ratings(team_name, stats, avg_gf, avg_ga):
    """Calcula ratings de ataque y defensa normalizados."""
    if team_name not in stats:
        return None

    team = stats[team_name]

    attack = team["avg_goals_scored"] / avg_gf if avg_gf > 0 else 1.0
    defense = team["avg_goals_conceded"] / avg_ga if avg_ga > 0 else 1.0
    home_attack = team["home"]["avg_gf"] / avg_gf if avg_gf > 0 else 1.0
    home_defense = team["home"]["avg_ga"] / avg_ga if avg_ga > 0 else 1.0
    away_attack = team["away"]["avg_gf"] / avg_gf if avg_gf > 0 else 1.0
    away_defense = team["away"]["avg_ga"] / avg_ga if avg_ga > 0 else 1.0

    form_pct = team["form_last_5"]["percentage"] / 100.0
    form_factor = 1.0 + FORM_WEIGHT * (form_pct - 0.5)

    return {
        "attack": attack, "defense": defense,
        "home_attack": home_attack, "home_defense": home_defense,
        "away_attack": away_attack, "away_defense": away_defense,
        "form_factor": form_factor,
        "matches_played": team["matches_played"],
    }


# ─── Modelo de Poisson ─────────────────────────────────────────────────────

def predict_match(home_team, away_team, stats, avg_gf, avg_ga, home_advantage):
    """Predice un partido usando modelo de Poisson bivariado independiente."""
    home_ratings = get_team_ratings(home_team, stats, avg_gf, avg_ga)
    away_ratings = get_team_ratings(away_team, stats, avg_gf, avg_ga)

    home_has_data = home_ratings is not None
    away_has_data = away_ratings is not None

    if not home_ratings:
        home_ratings = {"attack": 0.85, "defense": 1.10, "home_attack": 0.95,
                        "home_defense": 1.05, "away_attack": 0.75, "away_defense": 1.15,
                        "form_factor": 1.0, "matches_played": 0}
    if not away_ratings:
        away_ratings = {"attack": 0.85, "defense": 1.10, "home_attack": 0.95,
                        "home_defense": 1.05, "away_attack": 0.75, "away_defense": 1.15,
                        "form_factor": 1.0, "matches_played": 0}

    # Lambda local = ataque_local × defensa_visitante_fuera × media × ventaja_local × forma
    lambda_home = (
        home_ratings["home_attack"]
        * away_ratings["away_defense"]
        * avg_gf
        * home_advantage
        * home_ratings["form_factor"]
    )

    # Lambda visitante = ataque_visitante_fuera × defensa_local_casa × media × forma
    lambda_away = (
        away_ratings["away_attack"]
        * home_ratings["home_defense"]
        * avg_gf
        * away_ratings["form_factor"]
    )

    lambda_home = max(0.3, min(lambda_home, 5.0))
    lambda_away = max(0.2, min(lambda_away, 4.5))

    # Matriz de probabilidades
    score_matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            score_matrix[(h, a)] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)

    total = sum(score_matrix.values())

    p_home_win = sum(p for (h, a), p in score_matrix.items() if h > a) / total
    p_draw = sum(p for (h, a), p in score_matrix.items() if h == a) / total
    p_away_win = sum(p for (h, a), p in score_matrix.items() if h < a) / total
    p_btts_yes = sum(p for (h, a), p in score_matrix.items() if h > 0 and a > 0) / total
    p_over_25 = sum(p for (h, a), p in score_matrix.items() if h + a > 2.5) / total
    p_over_15 = sum(p for (h, a), p in score_matrix.items() if h + a > 1.5) / total

    sorted_scores = sorted(score_matrix.items(), key=lambda x: x[1], reverse=True)
    top_scores = [(f"{h}-{a}", p / total * 100) for (h, a), p in sorted_scores[:5]]

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_has_data": home_has_data,
        "away_has_data": away_has_data,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "exp_home_goals": round(lambda_home, 2),
        "exp_away_goals": round(lambda_away, 2),
        "p_home_win": round(p_home_win * 100, 1),
        "p_draw": round(p_draw * 100, 1),
        "p_away_win": round(p_away_win * 100, 1),
        "p_btts_yes": round(p_btts_yes * 100, 1),
        "p_btts_no": round((1 - p_btts_yes) * 100, 1),
        "p_over_25": round(p_over_25 * 100, 1),
        "p_under_25": round((1 - p_over_25) * 100, 1),
        "p_over_15": round(p_over_15 * 100, 1),
        "top_scores": top_scores,
    }


# ─── Presentación ──────────────────────────────────────────────────────────

def print_team_profile(name, stats):
    """Imprime perfil resumido de un equipo."""
    if name not in stats:
        return
    t = stats[name]
    mp = t["matches_played"]
    form = t["form_last_5"]
    print(f"    {name}: {mp}PJ  {t['wins']}V-{t['draws']}E-{t['losses']}D  "
          f"GF:{t['avg_goals_scored']:.2f}/p  GA:{t['avg_goals_conceded']:.2f}/p  "
          f"Forma:{form['sequence']} ({form['percentage']}%)")
    print(f"      Local: {t['home']['avg_gf']:.2f}gf/{t['home']['avg_ga']:.2f}ga por partido  "
          f"Visitante: {t['away']['avg_gf']:.2f}gf/{t['away']['avg_ga']:.2f}ga por partido")
    if t.get("recent_matches"):
        recent = t["recent_matches"][-3:]
        recent_str = "  ".join(
            f"{m['result']} {m['gf']}-{m['ga']} vs {m['vs'][:12]} ({m['venue'][0].upper()})"
            for m in recent
        )
        print(f"      Últimos: {recent_str}")


def print_prediction(pred, stats):
    """Imprime predicción de un partido con formato claro."""
    home = pred["home_team"]
    away = pred["away_team"]
    warn_home = " *" if not pred["home_has_data"] else ""
    warn_away = " *" if not pred["away_has_data"] else ""

    print(f"\n{'═' * 75}")
    print(f"  {home}{warn_home}  vs  {away}{warn_away}")
    print(f"{'═' * 75}")

    if not pred["home_has_data"] or not pred["away_has_data"]:
        missing = [n for n, has in [(home, pred["home_has_data"]), (away, pred["away_has_data"])] if not has]
        print(f"  ⚠  Sin datos históricos: {', '.join(missing)}")

    # Perfiles de equipo
    print_team_profile(home, stats)
    print_team_profile(away, stats)

    print(f"\n  Goles esperados:  {home} {pred['exp_home_goals']:.2f}  -  {pred['exp_away_goals']:.2f} {away}")
    print(f"  (λ_home={pred['lambda_home']:.3f}  λ_away={pred['lambda_away']:.3f})")

    print(f"\n  ┌─────────────────────────────────────────────────────────────────┐")
    print(f"  │  MERCADO 1X2                                                    │")
    print(f"  │  Local (1):  {pred['p_home_win']:5.1f}%   (cuota {prob_to_odds(pred['p_home_win']):5.2f})            │")
    print(f"  │  Empate (X): {pred['p_draw']:5.1f}%   (cuota {prob_to_odds(pred['p_draw']):5.2f})            │")
    print(f"  │  Visit  (2): {pred['p_away_win']:5.1f}%   (cuota {prob_to_odds(pred['p_away_win']):5.2f})            │")
    print(f"  ├─────────────────────────────────────────────────────────────────┤")
    print(f"  │  BTTS (Ambos marcan)                                            │")
    print(f"  │  Sí:  {pred['p_btts_yes']:5.1f}%   (cuota {prob_to_odds(pred['p_btts_yes']):5.2f})                    │")
    print(f"  │  No:  {pred['p_btts_no']:5.1f}%   (cuota {prob_to_odds(pred['p_btts_no']):5.2f})                    │")
    print(f"  ├─────────────────────────────────────────────────────────────────┤")
    print(f"  │  OVER / UNDER                                                   │")
    print(f"  │  Over  1.5:  {pred['p_over_15']:5.1f}%   (cuota {prob_to_odds(pred['p_over_15']):5.2f})            │")
    print(f"  │  Over  2.5:  {pred['p_over_25']:5.1f}%   (cuota {prob_to_odds(pred['p_over_25']):5.2f})            │")
    print(f"  │  Under 2.5:  {pred['p_under_25']:5.1f}%   (cuota {prob_to_odds(pred['p_under_25']):5.2f})            │")
    print(f"  ├─────────────────────────────────────────────────────────────────┤")
    print(f"  │  SCORES MÁS PROBABLES                                           │")
    for score, prob in pred["top_scores"]:
        bar = "█" * int(prob / 2)
        print(f"  │    {score:>5s}  {prob:5.1f}%  {bar:<25s}                │")

    # Córners
    if "corners" in pred:
        c = pred["corners"]
        src = "datos reales" if c["has_corner_data"] else "estimación"
        print(f"  ├─────────────────────────────────────────────────────────────────┤")
        print(f"  │  CÓRNERS ({src:<15s})                                      │")
        print(f"  │  Esperados:  {home} {c['exp_home_corners']:.1f}  -  {c['exp_away_corners']:.1f} {away}  (Total: {c['exp_total_corners']:.1f})    │")
        print(f"  │  Over  8.5:  {c['p_over_8_5']:5.1f}%   (cuota {prob_to_odds(c['p_over_8_5']):5.2f})            │")
        print(f"  │  Over  9.5:  {c['p_over_9_5']:5.1f}%   (cuota {prob_to_odds(c['p_over_9_5']):5.2f})            │")
        print(f"  │  Over 10.5:  {c['p_over_10_5']:5.1f}%   (cuota {prob_to_odds(c['p_over_10_5']):5.2f})            │")

    print(f"  └─────────────────────────────────────────────────────────────────┘")


def determine_bet_suggestion(pred):
    """Sugiere apuestas con mejor valor."""
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

    return " + ".join(suggestions) if suggestions else "Sin valor claro"


def print_summary_table(predictions):
    """Imprime tabla resumen de todos los partidos."""
    print(f"\n{'=' * 105}")
    print(f"  RESUMEN DE PREDICCIONES - FINALES PLAYOFF WCQ UEFA - 31 MARZO 2026")
    print(f"{'=' * 105}")

    print(f"\n  {'Partido':<35s} │ {'1':>6s} {'X':>6s} {'2':>6s} │ {'BTTS':>5s} │ {'O2.5':>5s} {'U2.5':>5s} │ {'Córners':>7s} │ {'Score':>5s} │ {'Apuesta sugerida':<22s}")
    print(f"  {'─' * 35}─┼─{'─' * 6}─{'─' * 6}─{'─' * 6}─┼─{'─' * 5}─┼─{'─' * 5}─{'─' * 5}─┼─{'─' * 7}─┼─{'─' * 5}─┼─{'─' * 22}")

    for p in predictions:
        match_str = f"{p['home_team'][:17]} vs {p['away_team'][:15]}"
        top_score = p["top_scores"][0][0] if p["top_scores"] else "?"
        suggestion = determine_bet_suggestion(p)
        corners_str = f"{p['corners']['exp_total_corners']:.1f}" if "corners" in p else "N/A"
        print(f"  {match_str:<35s} │ {p['p_home_win']:5.1f}% {p['p_draw']:5.1f}% {p['p_away_win']:5.1f}% │ {p['p_btts_yes']:4.1f}% │ {p['p_over_25']:4.1f}% {p['p_under_25']:4.1f}% │ {corners_str:>7s} │ {top_score:>5s} │ {suggestion:<22s}")

    print()


def find_team(name, stats):
    """Busca un equipo por nombre exacto o parcial."""
    if name in stats:
        return name
    name_lower = name.lower()
    for team_name in stats:
        if name_lower in team_name.lower() or team_name.lower() in name_lower:
            return team_name
    return name


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 75)
    print("  PREDICTOR DE APUESTAS - MODELO DE POISSON v2")
    print("  Datos: WCQ UEFA 2026 + Nations League 2024-25 (Wikipedia)")
    print("=" * 75)

    # Cargar partidos de selecciones
    print("\nCargando partidos de selecciones nacionales...")
    nat_matches = load_national_matches()
    print(f"  {len(nat_matches)} partidos cargados")

    # Calcular estadísticas
    print("Calculando estadísticas por selección...")
    stats = compute_national_stats(nat_matches)
    print(f"  {len(stats)} selecciones con datos")

    # Promedios
    avg_gf, avg_ga, home_adv = compute_league_averages(stats)
    print(f"\n  Media goles/partido:      {avg_gf:.3f}")
    print(f"  Ventaja local calculada:  {home_adv:.3f}x")

    # Partidos a predecir (Finales Playoff WCQ UEFA - 31 Marzo 2026)
    matches_to_predict = [
        ("Bosnia-Herzegovina", "Italy"),
        ("Czechia", "Denmark"),
        ("Kosovo", "Turkey"),
        ("Sweden", "Poland"),
    ]

    # Cargar datos de córners (si existen)
    corner_stats = load_corner_stats()
    if corner_stats:
        print(f"  Datos de córners cargados: {len(corner_stats)} equipos")
    else:
        print(f"  Datos de córners: no disponibles (usando estimaciones)")
        print(f"  → Ejecuta fetch_corners.py con API-Football key para datos reales")

    print(f"\n  Prediciendo {len(matches_to_predict)} partidos (Finales Playoff WCQ)...")

    predictions = []
    for home, away in matches_to_predict:
        home_resolved = find_team(home, stats)
        away_resolved = find_team(away, stats)
        pred = predict_match(home_resolved, away_resolved, stats, avg_gf, avg_ga, home_adv)
        pred["home_team"] = home
        pred["away_team"] = away
        # Añadir predicción de córners
        pred["corners"] = predict_corners(home_resolved, away_resolved, corner_stats)
        predictions.append(pred)
        print_prediction(pred, stats)

    print_summary_table(predictions)

    # Guardar
    out_path = os.path.join(os.path.dirname(__file__), "predictions.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Predicciones guardadas en: {out_path}")

    print(f"\n  DISCLAIMER: Estas predicciones son orientativas basadas en un modelo")
    print(f"  estadístico. No constituyen consejo financiero ni de apuestas.\n")


if __name__ == "__main__":
    main()
