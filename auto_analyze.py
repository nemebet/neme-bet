"""
AUTO_ANALYZE.PY — Analisis automatico diario para NEME BET
══════════════════════════════════════════════════════════
Toma partidos de partidos_hoy.json y corre el modelo ensemble completo.
Filtra picks con >75% de confianza.
"""

import json
import os
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from data_dir import data_path
INPUT_PATH = data_path("partidos_hoy.json")
PICKS_PATH = data_path("picks_del_dia.json")

# Import prediction engine
sys.path.insert(0, BASE_DIR)


def analyze_today():
    """Analiza todos los partidos relevantes del dia."""
    print(f"\n[AUTO-ANALYZE] {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if not os.path.exists(INPUT_PATH):
        print("  No hay partidos_hoy.json — ejecuta besoccer_scraper primero")
        return None

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    matches = data.get("matches_relevant", [])
    if not matches:
        matches = data.get("matches_all", [])[:10]

    if not matches:
        print("  Sin partidos para analizar")
        return None

    print(f"  {len(matches)} partidos a analizar")

    # Import webapp prediction pipeline
    from webapp import find_team, fetch_matches, compute_stats, fetch_news, predict, get_picks
    from webapp import ELO_INITIAL

    predictions = []

    for m in matches:
        home_name = m["home"]
        away_name = m["away"]
        print(f"  Analizando: {home_name} vs {away_name}...")

        h_info = find_team(home_name)
        a_info = find_team(away_name)

        if not h_info or not a_info:
            print(f"    Equipo no encontrado, saltando")
            continue

        # Fetch data
        h_matches = fetch_matches(h_info["id"], 15)
        a_matches = fetch_matches(a_info["id"], 15)

        h_stats = compute_stats(h_matches, h_info["id"])
        a_stats = compute_stats(a_matches, a_info["id"])

        h_elo = int(ELO_INITIAL + h_stats["gd"] * 150)
        a_elo = int(ELO_INITIAL + a_stats["gd"] * 150)

        h_news = fetch_news(h_info["name"])
        a_news = fetch_news(a_info["name"])

        pred = predict(home_name, away_name, h_stats, a_stats,
                       h_elo, a_elo, h_news, a_news)

        pred["liga"] = m.get("liga", "")
        pred["hora"] = m.get("hora", "")
        pred["source"] = m.get("source", "")
        predictions.append(pred)

        # Save to results_db for auto-tracking
        try:
            from calibration import save_prediction
            save_prediction(pred)
        except Exception:
            pass

    # Get picks
    all_picks = get_picks(predictions)

    # Separate by confidence
    high_picks = [p for p in all_picks if p.get("prob", 0) >= 75]
    med_picks = [p for p in all_picks if 65 <= p.get("prob", 0) < 75]

    output = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "analyzed_at": datetime.now().isoformat(),
        "total_matches": len(matches),
        "analyzed": len(predictions),
        "predictions": predictions,
        "high_confidence_picks": high_picks,
        "medium_confidence_picks": med_picks,
        "total_picks": len(all_picks),
    }

    with open(PICKS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n  Resultados:")
    print(f"    Partidos analizados: {len(predictions)}")
    print(f"    Picks +75%: {len(high_picks)}")
    print(f"    Picks 65-75%: {len(med_picks)}")
    print(f"  Guardado en: {PICKS_PATH}")

    return output


if __name__ == "__main__":
    analyze_today()
