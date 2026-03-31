"""
Predictor v5 — Ensemble + Contexto Competitivo + Forma de Jugadores
═══════════════════════════════════════════════════════════════════

Nuevo en v5:
  - Datos reales de jugadores (Wikipedia, temporada 2025-26)
  - Rating de XI titular ajustado por calidad de liga
  - Impacto ponderado por posición (portero→delantero)
  - Marcadores peligrosos (xG bonus)
  - Comparación v4 vs v5

Base: v4 (Ensemble + Contexto Competitivo)
"""

import json, os, sys
from math import exp, lgamma, log
from collections import defaultdict
from datetime import datetime

from player_form import (
    SQUAD_DATA, POSITION_WEIGHTS, LEAGUE_QUALITY,
    compute_squad_metrics, print_squad_analysis,
)

# ─── Importar componentes de v4 ─────────────────────────────────────────
from predict_v4 import (
    MAX_GOALS, REFERENCE_DATE, W_POISSON, W_DIXON_COLES, W_ELO,
    DC_RHO, DECAY_HALF_LIFE, ELO_INITIAL, ELO_K, ELO_HOME_ADVANTAGE,
    MATCH_TYPES, TOURNAMENT_LEVELS, WORLD_CUP_HISTORY, KEY_ABSENCES,
    poisson_pmf, prob_to_odds, decay_weight,
    compute_elo_ratings, elo_expected_goals,
    compute_weighted_stats, build_dc_matrix,
    apply_absences, compute_competitive_context,
    load_corner_stats, find_in_corners, predict_corners_v4,
    extract_markets, find_team,
)


def ensemble_predict_v5(home, away, w_stats, elo_ratings, avg_gf, home_adv,
                        corner_stats, match_type, tournament):
    """v5: v4 + capa de forma de jugadores."""

    # ─── Contexto competitivo (de v4) ────────────────────
    ctx = compute_competitive_context(home, away, match_type, tournament)

    h_s = w_stats.get(home) or {"avg_gf":1.2,"avg_ga":1.5,"home_avg_gf":1.3,"home_avg_ga":1.4,"away_avg_gf":1.0,"away_avg_ga":1.6,"effective_matches":0}
    a_s = w_stats.get(away) or {"avg_gf":1.2,"avg_ga":1.5,"home_avg_gf":1.3,"home_avg_ga":1.4,"away_avg_gf":1.0,"away_avg_ga":1.6,"effective_matches":0}

    w_gf_t = sum(s["avg_gf"]*s["effective_matches"] for s in w_stats.values())
    w_mp_t = sum(s["effective_matches"] for s in w_stats.values())
    w_avg = w_gf_t / w_mp_t if w_mp_t > 0 else avg_gf

    # Ratings base
    h_att = h_s["home_avg_gf"] / w_avg if w_avg > 0 else 1.0
    h_def = h_s["home_avg_ga"] / w_avg if w_avg > 0 else 1.0
    a_att = a_s["away_avg_gf"] / w_avg if w_avg > 0 else 1.0
    a_def = a_s["away_avg_ga"] / w_avg if w_avg > 0 else 1.0

    lh = h_att * a_def * w_avg * home_adv
    la = a_att * h_def * w_avg

    # ─── Presión histórica (de v4) ───────────────────────
    hp = ctx["home_pressure"]
    ap = ctx["away_pressure"]
    lh *= hp["attack_mod"] * ap["defense_mod"]
    la *= ap["attack_mod"] * hp["defense_mod"]

    # ─── Goles modifier torneo (de v4) ───────────────────
    lh *= ctx["goals_modifier"]
    la *= ctx["goals_modifier"]

    # ─── Bajas (de v4) ──────────────────────────────────
    lh, d_h = apply_absences(home, lh, 0)
    la, d_a = apply_absences(away, la, 0)
    la += d_h; lh += d_a

    # ─── NUEVO v5: Forma de jugadores ───────────────────
    h_squad = compute_squad_metrics(home)
    a_squad = compute_squad_metrics(away)

    h_form_atk = h_squad["attack_mod"] if h_squad else 1.0
    h_form_def = h_squad["defense_mod"] if h_squad else 1.0
    a_form_atk = a_squad["attack_mod"] if a_squad else 1.0
    a_form_def = a_squad["defense_mod"] if a_squad else 1.0

    h_xg_bonus = h_squad["scorer_xg_bonus"] if h_squad else 0.0
    a_xg_bonus = a_squad["scorer_xg_bonus"] if a_squad else 0.0

    # Aplicar forma al ataque
    lh *= h_form_atk
    la *= a_form_atk

    # Aplicar forma a la defensa (afecta lambda del rival)
    la *= h_form_def   # Si local tiene buena defensa, visitante marca menos
    lh *= a_form_def   # Si visitante tiene buena defensa, local marca menos

    # Aplicar bonus de goleadores
    lh += h_xg_bonus
    la += a_xg_bonus

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
    rho = -0.18 if match_type == "FINAL_DIRECT" else DC_RHO
    dc_m = build_dc_matrix(lh, la, rho)

    # ─── Sub-modelo 3: ELO ──────────────────────────────
    elo_h = elo_ratings.get(home, ELO_INITIAL)
    elo_a = elo_ratings.get(away, ELO_INITIAL)
    elh, ela = elo_expected_goals(elo_h, elo_a, w_avg)
    elh *= hp["attack_mod"] * ap["defense_mod"] * ctx["goals_modifier"] * h_form_atk
    ela *= ap["attack_mod"] * hp["defense_mod"] * ctx["goals_modifier"] * a_form_atk
    elh, ed_h = apply_absences(home, elh, 0)
    ela, ed_a = apply_absences(away, ela, 0)
    ela += ed_h; elh += ed_a
    elh += h_xg_bonus; ela += a_xg_bonus
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

    db = ctx["draw_boost"]
    if db > 0:
        for key in ens_m:
            h, a = key
            if h == a:
                ens_m[key] *= (1 + db * 5)
            else:
                ens_m[key] *= (1 - db)

    ens_t = sum(ens_m.values())
    ens_m = {k: v/ens_t for k, v in ens_m.items()}

    ens = extract_markets(ens_m)
    poi = extract_markets(poi_m)
    dc = extract_markets(dc_m)
    elo_p = extract_markets(elo_m)

    sorted_scores = sorted(ens_m.items(), key=lambda x: x[1], reverse=True)
    top_scores = [(f"{h}-{a}", p*100) for (h,a), p in sorted_scores[:5]]

    corners = predict_corners_v4(home, away, corner_stats, ctx)

    context_narrative = (
        f"FINAL DIRECTA (nivel {ctx['tournament']['level']}/8) — "
        f"{home}: {hp['label']} | {away}: {ap['label']} — "
        f"XI Rating: {h_squad['avg_rating']:.2f} vs {a_squad['avg_rating']:.2f}"
        if h_squad and a_squad else "Sin datos de plantilla"
    )

    return {
        "home_team": home, "away_team": away,
        "elo_home": round(elo_h), "elo_away": round(elo_a),
        "home_pressure": hp, "away_pressure": ap,
        "home_squad": h_squad, "away_squad": a_squad,
        "context": ctx, "context_narrative": context_narrative,
        "home_wc_context": ctx["home_context"],
        "away_wc_context": ctx["away_context"],
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

def print_v5_prediction(p):
    home, away = p["home_team"], p["away_team"]
    hp, ap = p["home_pressure"], p["away_pressure"]
    hs, as_ = p["home_squad"], p["away_squad"]

    print(f"\n{'═' * 90}")
    print(f"  {home}  vs  {away}")
    print(f"  {p['context_narrative']}")
    print(f"{'═' * 90}")

    # Contexto mundialista
    print(f"  ● {home}: {p['home_wc_context']}")
    print(f"  ● {away}: {p['away_wc_context']}")

    # Análisis de plantilla
    if hs:
        print_squad_analysis(hs)
    if as_:
        print_squad_analysis(as_)

    # Metadata
    print(f"\n  ELO: {p['elo_home']} vs {p['elo_away']} ({p['elo_home']-p['elo_away']:+d})")
    print(f"  Presión: {hp['label']} vs {ap['label']}")
    if hs and as_:
        print(f"  Forma XI: {home} {hs['avg_rating']:.2f} (atk ×{hs['attack_mod']:.3f}) vs "
              f"{away} {as_['avg_rating']:.2f} (atk ×{as_['attack_mod']:.3f})")

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
    print(f"  │  ENSEMBLE v5     │ 100%   │ {p['p_home_win']:5.1f} {p['p_draw']:5.1f} {p['p_away_win']:5.1f} │  {p['p_btts_yes']:5.1f}% │  {p['p_over_25']:5.1f}% │")
    print(f"  └─────────────────┴────────┴───────────────────┴──────────┴──────────┘")

    # Mercados
    print(f"\n  1X2: Local {p['p_home_win']:5.1f}% ({prob_to_odds(p['p_home_win']):5.2f})  "
          f"Empate {p['p_draw']:5.1f}% ({prob_to_odds(p['p_draw']):5.2f})  "
          f"Visit {p['p_away_win']:5.1f}% ({prob_to_odds(p['p_away_win']):5.2f})")
    print(f"  BTTS Sí: {p['p_btts_yes']:5.1f}%  |  O2.5: {p['p_over_25']:5.1f}%  U2.5: {p['p_under_25']:5.1f}%")

    print(f"\n  Scores: ", end="")
    print("  ".join(f"{sc} ({pr:.1f}%)" for sc, pr in p["top_scores"][:4]))

    c = p["corners"]
    src = "real" if c["has_corner_data"] else "est."
    print(f"  Córners ({src}): {c['exp_total_corners']:.1f} total  |  O10.5: {c['p_over_10_5']:.1f}%")


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


def print_comparison(v5_preds, v4_preds):
    print(f"\n{'═' * 125}")
    print(f"  COMPARACIÓN: v4 (Contexto) vs v5 (Contexto + Forma Jugadores)")
    print(f"  Impacto de: Rating XI titular | Marcadores peligrosos (xG bonus) | Ajuste liga | Ausentes")
    print(f"{'═' * 125}")

    v4_map = {}
    if v4_preds:
        for p in v4_preds:
            v4_map[(p["home_team"], p["away_team"])] = p

    print(f"\n  {'Partido':<28s} │ {'Ver':^4s} │ {'1':>6s} {'X':>6s} {'2':>6s} │ {'BTTS':>5s} │ {'O2.5':>5s} │ {'Score':>5s} │ {'XI Rtg':>7s} │ {'Goleadores':>12s} │ {'Apuesta':<22s}")
    print(f"  {'─'*28}─┼─{'─'*4}─┼─{'─'*20}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*7}─┼─{'─'*12}─┼─{'─'*22}")

    for v5 in v5_preds:
        key = (v5["home_team"], v5["away_team"])
        m = f"{v5['home_team'][:14]} vs {v5['away_team'][:11]}"
        v4 = v4_map.get(key)
        hs, as_ = v5.get("home_squad"), v5.get("away_squad")

        if v4:
            v4s = v4["top_scores"][0][0] if v4.get("top_scores") else "?"
            print(f"  {m:<28s} │ {'v4':^4s} │ {v4['p_home_win']:5.1f}% {v4['p_draw']:5.1f}% {v4['p_away_win']:5.1f}% │ {v4['p_btts_yes']:4.1f}% │ {v4['p_over_25']:4.1f}% │ {v4s:>5s} │         │              │")

        v5s = v5["top_scores"][0][0] if v5.get("top_scores") else "?"
        h_rtg = f"{hs['avg_rating']:.2f}" if hs else "?"
        a_rtg = f"{as_['avg_rating']:.2f}" if as_ else "?"
        rtg_str = f"{h_rtg}v{a_rtg}"
        h_scorers = len(hs['dangerous_scorers']) if hs else 0
        a_scorers = len(as_['dangerous_scorers']) if as_ else 0
        sc_str = f"{h_scorers}vs{a_scorers} (+{(hs['scorer_xg_bonus'] if hs else 0)+(as_['scorer_xg_bonus'] if as_ else 0):.2f}xG)"
        sug = bet_suggestion(v5)
        print(f"  {'':28s} │ {'v5':^4s} │ {v5['p_home_win']:5.1f}% {v5['p_draw']:5.1f}% {v5['p_away_win']:5.1f}% │ {v5['p_btts_yes']:4.1f}% │ {v5['p_over_25']:4.1f}% │ {v5s:>5s} │ {rtg_str:>7s} │ {sc_str:>12s} │ {sug:<22s}")

        if v4:
            d1 = v5["p_home_win"] - v4["p_home_win"]
            dx = v5["p_draw"] - v4["p_draw"]
            d2 = v5["p_away_win"] - v4["p_away_win"]
            print(f"  {'':28s} │ {'Δ':^4s} │ {d1:+5.1f}% {dx:+5.1f}% {d2:+5.1f}% │       │       │       │         │              │")

        print(f"  {'─'*28}─┼─{'─'*4}─┼─{'─'*20}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*7}─┼─{'─'*12}─┼─{'─'*22}")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("═" * 90)
    print("  PREDICTOR v5 — ENSEMBLE + CONTEXTO + FORMA DE JUGADORES")
    print("  Datos reales Wikipedia 2025-26 | Rating XI ajustado por liga")
    print("  Poisson(40%) + Dixon-Coles(30%) + ELO(30%)")
    print("═" * 90)

    # Datos
    data_path = os.path.join(os.path.dirname(__file__), "national_matches.json")
    with open(data_path, encoding="utf-8") as f:
        matches = json.load(f)
    print(f"\n  {len(matches)} partidos cargados")

    elo = compute_elo_ratings(matches)
    w_stats = compute_weighted_stats(matches)

    from predict import compute_national_stats, compute_league_averages
    simple = compute_national_stats(matches)
    avg_gf, _, home_adv = compute_league_averages(simple)

    corner_stats = load_corner_stats()

    # Análisis de plantillas
    print(f"\n{'─' * 90}")
    print(f"  ANÁLISIS DE FORMA DE JUGADORES — Datos Wikipedia 2025-26")
    print(f"{'─' * 90}")

    targets = ["Bosnia-Herzegovina","Italy","Czechia","Denmark","Kosovo","Turkey","Sweden","Poland"]
    all_squads = {}
    for t in targets:
        sq = compute_squad_metrics(t)
        all_squads[t] = sq
        if sq:
            print_squad_analysis(sq)

    # Rankings
    print(f"\n  ┌──────────────────────────┬────────┬──────────┬──────────┬──────────────────────────┐")
    print(f"  │  Selección               │ Rating │ Atk mod  │ xG bonus │ Goleadores clave         │")
    print(f"  ├──────────────────────────┼────────┼──────────┼──────────┼──────────────────────────┤")
    for t in sorted(targets, key=lambda x: all_squads[x]["avg_rating"] if all_squads[x] else 0, reverse=True):
        sq = all_squads[t]
        if not sq: continue
        scorers = ", ".join(f"{s['name']}({s['goals']})" for s in sq["dangerous_scorers"][:3]) or "—"
        print(f"  │  {t:<24s} │ {sq['avg_rating']:5.2f}  │  ×{sq['attack_mod']:.3f}  │  +{sq['scorer_xg_bonus']:.2f}   │ {scorers:<24s} │")
    print(f"  └──────────────────────────┴────────┴──────────┴──────────┴──────────────────────────┘")

    # Predicciones
    games = [
        ("Bosnia-Herzegovina", "Italy"),
        ("Czechia", "Denmark"),
        ("Kosovo", "Turkey"),
        ("Sweden", "Poland"),
    ]

    print(f"\n{'─' * 90}")
    print(f"  PREDICCIONES v5")
    print(f"{'─' * 90}")

    v5_preds = []
    for home, away in games:
        h = find_team(home, w_stats)
        a = find_team(away, w_stats)
        pred = ensemble_predict_v5(h, a, w_stats, elo, avg_gf, home_adv,
                                   corner_stats, "FINAL_DIRECT", "WCQ_PLAYOFF")
        pred["home_team"] = home
        pred["away_team"] = away
        v5_preds.append(pred)
        print_v5_prediction(pred)

    # Comparar v4 vs v5
    v4_path = os.path.join(os.path.dirname(__file__), "predictions_v4.json")
    v4_preds = None
    if os.path.exists(v4_path):
        with open(v4_path, encoding="utf-8") as f:
            v4_preds = json.load(f)

    print_comparison(v5_preds, v4_preds)

    # Guardar
    out = os.path.join(os.path.dirname(__file__), "predictions_v5.json")
    # Limpiar squad data no serializable
    for p in v5_preds:
        if p.get("home_squad"):
            p["home_squad"] = {k: v for k, v in p["home_squad"].items() if k != "context"}
        if p.get("away_squad"):
            p["away_squad"] = {k: v for k, v in p["away_squad"].items() if k != "context"}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(v5_preds, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Guardado en: {out}")
    print(f"\n  DISCLAIMER: Modelo estadístico con fines educativos. No es consejo de apuestas.\n")

if __name__ == "__main__":
    main()
