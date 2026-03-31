"""
Módulo de estadísticas de córners - API-Football (free tier)
Descarga córners por partido para los equipos solicitados.

API-Football free tier: 100 requests/día, 10 req/minuto.
Registro: https://dashboard.api-football.com/register

Estrategia optimizada:
  1. Descargar fixtures por equipo (1 request por equipo×competición)
  2. Descargar estadísticas por fixture (1 request por partido)
  3. Total estimado: ~60-70 requests para 8 equipos
"""

import json
import os
import sys
import time
from collections import defaultdict

try:
    import requests as req_lib
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests as req_lib


API_BASE = "https://v3.football.api-sports.io"

# Equipos objetivo con sus IDs en API-Football
TARGET_TEAMS = {
    1113: "Bosnia-Herzegovina",
    768:  "Italy",
    770:  "Czechia",
    21:   "Denmark",
    1111: "Kosovo",
    777:  "Turkey",
    5:    "Sweden",
    24:   "Poland",
}

# Competiciones y temporadas accesibles en plan free
COMPETITIONS = [
    (32, "WCQ UEFA", 2024),
    (5, "Nations League", 2024),
    (5, "Nations League", 2022),
]

REQUEST_COUNT = 0
REQUEST_LIMIT = 95  # Dejar margen de 5


def get_api_key():
    """Obtiene la API key de API-Football."""
    api_key = os.environ.get("API_FOOTBALL_KEY")
    if api_key:
        return api_key

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("API_FOOTBALL_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    print("ERROR: No se encontró API_FOOTBALL_KEY.")
    print("Añádela a .env: API_FOOTBALL_KEY=tu_key")
    print("Registro gratuito: https://dashboard.api-football.com/register")
    sys.exit(1)


def api_request(endpoint, api_key, params=None):
    """Petición a API-Football con rate limiting estricto."""
    global REQUEST_COUNT
    if REQUEST_COUNT >= REQUEST_LIMIT:
        print(f"\n  ⚠ Límite de requests alcanzado ({REQUEST_COUNT}). Deteniendo.")
        return None

    headers = {"x-apisports-key": api_key}
    url = f"{API_BASE}/{endpoint}"

    response = req_lib.get(url, headers=headers, params=params, timeout=30)
    REQUEST_COUNT += 1

    if response.status_code == 429:
        print("    Rate limit (10/min), esperando 65s...")
        time.sleep(65)
        response = req_lib.get(url, headers=headers, params=params, timeout=30)
        REQUEST_COUNT += 1

    data = response.json()
    errors = data.get("errors", {})
    if errors:
        if "rateLimit" in str(errors):
            print("    Rate limit, esperando 65s...")
            time.sleep(65)
            response = req_lib.get(url, headers=headers, params=params, timeout=30)
            REQUEST_COUNT += 1
            data = response.json()
        elif errors:
            print(f"    Error: {errors}")
            return None

    return data


def fetch_team_fixtures(api_key, team_id, league_id, season):
    """Obtiene los partidos finalizados de un equipo en una competición."""
    params = {
        "team": team_id,
        "league": league_id,
        "season": season,
        "status": "FT",
    }
    data = api_request("fixtures", api_key, params)
    if not data:
        return []
    return data.get("response", [])


def fetch_fixture_stats(api_key, fixture_id):
    """Obtiene estadísticas de un partido (incluye córners)."""
    data = api_request("fixtures/statistics", api_key, {"fixture": fixture_id})
    if not data:
        return None
    return data.get("response", [])


def extract_stat(stats_list, stat_type):
    """Extrae un valor específico de la lista de estadísticas."""
    for stat in stats_list:
        if stat.get("type") == stat_type:
            return stat.get("value")
    return None


def main():
    print("=" * 65)
    print("  DESCARGA DE CÓRNERS - API-Football (plan gratuito)")
    print("=" * 65)

    api_key = get_api_key()

    # Verificar estado
    print("\nVerificando API key...")
    status_data = api_request("status", api_key)
    if status_data:
        resp = status_data.get("response", {})
        reqs = resp.get("requests", {})
        current = reqs.get("current", 0)
        limit = reqs.get("limit_day", 100)
        print(f"  Plan: {resp.get('subscription', {}).get('plan', '?')}")
        print(f"  Requests usados hoy: {current}/{limit}")
        if current > 80:
            print("  ⚠ Pocos requests restantes, procediendo con cuidado...")

    # Paso 1: Obtener todos los fixture IDs de los 8 equipos
    print(f"\n{'─' * 65}")
    print(f"  PASO 1: Buscando partidos de {len(TARGET_TEAMS)} equipos")
    print(f"{'─' * 65}")

    # Recopilar fixture IDs únicos (evitar duplicados entre equipos)
    fixture_map = {}  # fixture_id -> fixture data

    for team_id, team_name in TARGET_TEAMS.items():
        print(f"\n  {team_name} (id={team_id}):")
        for league_id, league_name, season in COMPETITIONS:
            if REQUEST_COUNT >= REQUEST_LIMIT:
                break

            fixtures = fetch_team_fixtures(api_key, team_id, league_id, season)
            new_count = 0
            for f in fixtures:
                fid = f["fixture"]["id"]
                if fid not in fixture_map:
                    fixture_map[fid] = {
                        "fixture_id": fid,
                        "date": f["fixture"]["date"][:10],
                        "competition": league_name,
                        "home_team": f["teams"]["home"]["name"],
                        "away_team": f["teams"]["away"]["name"],
                        "home_id": f["teams"]["home"]["id"],
                        "away_id": f["teams"]["away"]["id"],
                        "home_goals": f["goals"]["home"],
                        "away_goals": f["goals"]["away"],
                    }
                    new_count += 1
            print(f"    {league_name} {season}: {len(fixtures)} partidos ({new_count} nuevos)")
            time.sleep(7)  # 10 req/min = 6s mínimo entre requests

    print(f"\n  Total fixtures únicos: {len(fixture_map)}")
    print(f"  Requests usados hasta ahora: {REQUEST_COUNT}")

    remaining_requests = REQUEST_LIMIT - REQUEST_COUNT
    fixtures_to_fetch = min(len(fixture_map), remaining_requests)
    print(f"  Fixtures a procesar (con requests disponibles): {fixtures_to_fetch}")

    # Paso 2: Obtener estadísticas (córners) de cada fixture
    print(f"\n{'─' * 65}")
    print(f"  PASO 2: Descargando estadísticas de córners")
    print(f"{'─' * 65}")

    all_matches = []
    processed = 0

    for fid, fdata in sorted(fixture_map.items(), key=lambda x: x[1]["date"], reverse=True):
        if REQUEST_COUNT >= REQUEST_LIMIT:
            print(f"\n  ⚠ Límite alcanzado. Procesados {processed} de {len(fixture_map)}")
            break

        stats = fetch_fixture_stats(api_key, fid)
        time.sleep(7)

        home_corners = None
        away_corners = None

        if stats:
            for team_stats in stats:
                tid = team_stats.get("team", {}).get("id")
                statistics = team_stats.get("statistics", [])
                corners = extract_stat(statistics, "Corner Kicks")

                if tid == fdata["home_id"]:
                    home_corners = corners
                elif tid == fdata["away_id"]:
                    away_corners = corners

        match_data = {
            "date": fdata["date"],
            "competition": fdata["competition"],
            "home_team": fdata["home_team"],
            "away_team": fdata["away_team"],
            "home_goals": fdata["home_goals"],
            "away_goals": fdata["away_goals"],
            "home_corners": home_corners,
            "away_corners": away_corners,
            "total_corners": (home_corners or 0) + (away_corners or 0) if home_corners is not None else None,
        }
        all_matches.append(match_data)
        processed += 1

        if processed % 5 == 0:
            with_corners = sum(1 for m in all_matches if m["total_corners"] is not None)
            print(f"    {processed} partidos procesados ({with_corners} con córners) | Requests: {REQUEST_COUNT}")

    # Resumen
    with_corners = [m for m in all_matches if m["total_corners"] is not None]
    print(f"\n  Partidos procesados: {len(all_matches)}")
    print(f"  Partidos con datos de córners: {len(with_corners)}")

    if not with_corners:
        print("\n  ⚠ No se encontraron datos de córners.")
        # Guardar lo que tenemos de todas formas
        raw_path = os.path.join(os.path.dirname(__file__), "corners_matches.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)
        sys.exit(1)

    # Guardar partidos raw
    raw_path = os.path.join(os.path.dirname(__file__), "corners_matches.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_matches, f, ensure_ascii=False, indent=2)
    print(f"\n  Guardado en: {raw_path}")

    # Paso 3: Calcular estadísticas por equipo
    print(f"\n{'─' * 65}")
    print(f"  PASO 3: Calculando estadísticas de córners por equipo")
    print(f"{'─' * 65}")

    teams = defaultdict(lambda: {
        "home_corners_for": [], "home_corners_against": [],
        "away_corners_for": [], "away_corners_against": [],
    })

    for m in with_corners:
        hc = m["home_corners"]
        ac = m["away_corners"]
        home = m["home_team"]
        away = m["away_team"]

        teams[home]["home_corners_for"].append(hc)
        teams[home]["home_corners_against"].append(ac)
        teams[away]["away_corners_for"].append(ac)
        teams[away]["away_corners_against"].append(hc)

    stats = {}
    for name, data in teams.items():
        all_for = data["home_corners_for"] + data["away_corners_for"]
        all_against = data["home_corners_against"] + data["away_corners_against"]
        if not all_for:
            continue

        stats[name] = {
            "team": name,
            "matches_with_corners": len(all_for),
            "avg_corners_for": round(sum(all_for) / len(all_for), 2),
            "avg_corners_against": round(sum(all_against) / len(all_against), 2),
            "avg_total_corners": round((sum(all_for) + sum(all_against)) / len(all_for), 2),
            "home": {
                "avg_corners_for": round(sum(data["home_corners_for"]) / max(len(data["home_corners_for"]), 1), 2),
                "avg_corners_against": round(sum(data["home_corners_against"]) / max(len(data["home_corners_against"]), 1), 2),
            },
            "away": {
                "avg_corners_for": round(sum(data["away_corners_for"]) / max(len(data["away_corners_for"]), 1), 2),
                "avg_corners_against": round(sum(data["away_corners_against"]) / max(len(data["away_corners_against"]), 1), 2),
            },
        }

    # Informe
    print(f"\n  {'Equipo':<28s} │ {'PJ':>3s} │ {'CF/p':>5s} {'CC/p':>5s} {'Tot':>5s} │ {'CF_L':>5s} {'CC_L':>5s} │ {'CF_V':>5s} {'CC_V':>5s}")
    print(f"  {'─' * 28}─┼─{'─' * 3}─┼─{'─' * 5}─{'─' * 5}─{'─' * 5}─┼─{'─' * 5}─{'─' * 5}─┼─{'─' * 5}─{'─' * 5}")

    for t in sorted(stats.values(), key=lambda x: x["avg_corners_for"], reverse=True):
        print(f"  {t['team']:<28s} │ {t['matches_with_corners']:>3d} │ "
              f"{t['avg_corners_for']:5.2f} {t['avg_corners_against']:5.2f} {t['avg_total_corners']:5.2f} │ "
              f"{t['home']['avg_corners_for']:5.2f} {t['home']['avg_corners_against']:5.2f} │ "
              f"{t['away']['avg_corners_for']:5.2f} {t['away']['avg_corners_against']:5.2f}")

    # Guardar estadísticas
    stats_path = os.path.join(os.path.dirname(__file__), "corner_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n  Estadísticas guardadas en: {stats_path}")

    print(f"\n  Total requests usados: {REQUEST_COUNT}/100")
    print(f"  CF=Córners a favor  CC=Córners en contra  L=Local  V=Visitante")


if __name__ == "__main__":
    main()
