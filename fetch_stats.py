"""
Predictor de Apuestas de Fútbol - Módulo de Estadísticas
Descarga resultados de clasificación UEFA Mundial desde football-data.org
y calcula estadísticas por equipo.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import requests
except ImportError:
    print("Instalando requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


API_BASE = "https://api.football-data.org/v4"

# Competiciones disponibles en el plan gratuito de football-data.org
COMPETITIONS = [
    ("PL", "Premier League"),
    ("BL1", "Bundesliga"),
    ("SA", "Serie A"),
    ("PD", "La Liga"),
    ("FL1", "Ligue 1"),
    ("CL", "Champions League"),
    ("EC", "Eurocopa"),
    ("WC", "World Cup"),
]

# Rango de fechas: últimos 2 años
DATE_TO = datetime.now().strftime("%Y-%m-%d")
DATE_FROM = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")


def get_api_key():
    """Obtiene la API key desde variable de entorno o archivo .env."""
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if api_key:
        return api_key

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FOOTBALL_DATA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    print("ERROR: No se encontró la API key.")
    print("Opciones:")
    print("  1. Exportar variable de entorno:")
    print('     export FOOTBALL_DATA_API_KEY="tu_api_key"')
    print("  2. Crear archivo .env en el directorio del proyecto:")
    print('     FOOTBALL_DATA_API_KEY=tu_api_key')
    print()
    print("Obtén tu API key gratuita en: https://www.football-data.org/client/register")
    sys.exit(1)


def api_request(endpoint, api_key, params=None):
    """Realiza una petición a la API con manejo de rate limiting."""
    headers = {"X-Auth-Token": api_key}
    url = f"{API_BASE}/{endpoint}"

    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code == 429:
        print("  Rate limit alcanzado, esperando 60 segundos...")
        time.sleep(60)
        response = requests.get(url, headers=headers, params=params, timeout=30)

    response.raise_for_status()
    return response.json()


def fetch_matches(api_key):
    """Descarga partidos de todas las competiciones disponibles en el plan gratuito."""
    print(f"Descargando partidos del {DATE_FROM} al {DATE_TO}...")
    print(f"Competiciones: {', '.join(name for _, name in COMPETITIONS)}\n")

    params = {
        "dateFrom": DATE_FROM,
        "dateTo": DATE_TO,
        "status": "FINISHED",
    }

    all_matches = []

    for code, name in COMPETITIONS:
        try:
            print(f"  [{code}] {name}...", end=" ", flush=True)
            data = api_request(
                f"competitions/{code}/matches", api_key, params
            )
            matches = data.get("matches", [])
            parsed = []
            for m in matches:
                home = m.get("homeTeam", {})
                away = m.get("awayTeam", {})
                score = m.get("score", {})
                full_time = score.get("fullTime", {})

                if full_time.get("home") is None or full_time.get("away") is None:
                    continue

                parsed.append({
                    "date": m.get("utcDate", ""),
                    "matchday": m.get("matchday"),
                    "competition": code,
                    "competition_name": name,
                    "stage": m.get("stage", ""),
                    "home_team": home.get("name", "Unknown"),
                    "away_team": away.get("name", "Unknown"),
                    "home_goals": full_time["home"],
                    "away_goals": full_time["away"],
                    "winner": m.get("score", {}).get("winner", ""),
                })

            all_matches.extend(parsed)
            print(f"{len(parsed)} partidos")
            time.sleep(6)  # Respetar rate limit (10 req/min)

        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, 'status_code', '?')
            if status == 403:
                print(f"NO DISPONIBLE (plan gratuito)")
            else:
                print(f"Error {status}")
            continue

    print(f"\nTotal de partidos descargados: {len(all_matches)}")
    return all_matches


def calculate_team_stats(matches):
    """Calcula estadísticas completas por equipo."""
    teams = defaultdict(lambda: {
        "matches_played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "goals_scored": 0,
        "goals_conceded": 0,
        "home": {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0},
        "away": {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0},
        "recent_matches": [],  # Para racha de forma
    })

    # Ordenar partidos por fecha
    sorted_matches = sorted(matches, key=lambda x: x["date"])

    for match in sorted_matches:
        home = match["home_team"]
        away = match["away_team"]
        hg = match["home_goals"]
        ag = match["away_goals"]
        date = match["date"][:10]

        # --- Equipo local ---
        t = teams[home]
        t["matches_played"] += 1
        t["goals_scored"] += hg
        t["goals_conceded"] += ag
        t["home"]["played"] += 1
        t["home"]["gf"] += hg
        t["home"]["ga"] += ag

        if hg > ag:
            result_home = "W"
            t["wins"] += 1
            t["home"]["wins"] += 1
        elif hg == ag:
            result_home = "D"
            t["draws"] += 1
            t["home"]["draws"] += 1
        else:
            result_home = "L"
            t["losses"] += 1
            t["home"]["losses"] += 1

        t["recent_matches"].append({
            "date": date, "opponent": away, "venue": "home",
            "gf": hg, "ga": ag, "result": result_home,
        })

        # --- Equipo visitante ---
        t = teams[away]
        t["matches_played"] += 1
        t["goals_scored"] += ag
        t["goals_conceded"] += hg
        t["away"]["played"] += 1
        t["away"]["gf"] += ag
        t["away"]["ga"] += hg

        if ag > hg:
            result_away = "W"
            t["wins"] += 1
            t["away"]["wins"] += 1
        elif ag == hg:
            result_away = "D"
            t["draws"] += 1
            t["away"]["draws"] += 1
        else:
            result_away = "L"
            t["losses"] += 1
            t["away"]["losses"] += 1

        t["recent_matches"].append({
            "date": date, "opponent": home, "venue": "away",
            "gf": ag, "ga": hg, "result": result_away,
        })

    return teams


def compute_form(recent_matches, n=5):
    """Calcula la racha de forma de los últimos N partidos.
    Devuelve: cadena de resultados, puntos, y descripción.
    W=3pts, D=1pt, L=0pts.
    """
    last_n = recent_matches[-n:]
    form_string = "".join(m["result"] for m in last_n)
    points = sum(3 if m["result"] == "W" else 1 if m["result"] == "D" else 0 for m in last_n)
    max_points = n * 3
    form_pct = (points / max_points * 100) if max_points > 0 else 0
    return {
        "sequence": form_string,
        "points": points,
        "max_points": max_points,
        "percentage": round(form_pct, 1),
        "matches": last_n,
    }


def format_report(teams):
    """Genera el informe de estadísticas por equipo."""
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("PREDICTOR DE APUESTAS - ESTADÍSTICAS DE EQUIPOS UEFA")
    report_lines.append(f"Período: {DATE_FROM} a {DATE_TO}")
    report_lines.append("=" * 80)

    # Ordenar equipos por porcentaje de victorias
    sorted_teams = sorted(
        teams.items(),
        key=lambda x: x[1]["wins"] / max(x[1]["matches_played"], 1),
        reverse=True,
    )

    stats_output = []

    for team_name, data in sorted_teams:
        mp = data["matches_played"]
        if mp == 0:
            continue

        avg_gf = data["goals_scored"] / mp
        avg_ga = data["goals_conceded"] / mp
        win_pct = data["wins"] / mp * 100

        home = data["home"]
        away = data["away"]
        home_avg_gf = home["gf"] / max(home["played"], 1)
        home_avg_ga = home["ga"] / max(home["played"], 1)
        away_avg_gf = away["gf"] / max(away["played"], 1)
        away_avg_ga = away["ga"] / max(away["played"], 1)

        form = compute_form(data["recent_matches"])

        report_lines.append(f"\n{'─' * 60}")
        report_lines.append(f"  {team_name}")
        report_lines.append(f"{'─' * 60}")
        report_lines.append(f"  Partidos: {mp}  |  V: {data['wins']}  E: {data['draws']}  D: {data['losses']}  |  % Victoria: {win_pct:.0f}%")
        report_lines.append(f"  Goles marcados: {data['goals_scored']}  ({avg_gf:.2f}/partido)")
        report_lines.append(f"  Goles recibidos: {data['goals_conceded']}  ({avg_ga:.2f}/partido)")
        report_lines.append(f"  LOCAL  -> PJ: {home['played']}  V:{home['wins']} E:{home['draws']} D:{home['losses']}  GF:{home_avg_gf:.2f}/p  GA:{home_avg_ga:.2f}/p")
        report_lines.append(f"  VISIT  -> PJ: {away['played']}  V:{away['wins']} E:{away['draws']} D:{away['losses']}  GF:{away_avg_gf:.2f}/p  GA:{away_avg_ga:.2f}/p")
        report_lines.append(f"  Forma (últimos 5): {form['sequence']}  ({form['points']}/{form['max_points']} pts = {form['percentage']}%)")

        stats_output.append({
            "team": team_name,
            "matches_played": mp,
            "wins": data["wins"],
            "draws": data["draws"],
            "losses": data["losses"],
            "win_percentage": round(win_pct, 1),
            "avg_goals_scored": round(avg_gf, 2),
            "avg_goals_conceded": round(avg_ga, 2),
            "home": {
                "played": home["played"],
                "win_rate": round(home["wins"] / max(home["played"], 1) * 100, 1),
                "avg_gf": round(home_avg_gf, 2),
                "avg_ga": round(home_avg_ga, 2),
            },
            "away": {
                "played": away["played"],
                "win_rate": round(away["wins"] / max(away["played"], 1) * 100, 1),
                "avg_gf": round(away_avg_gf, 2),
                "avg_ga": round(away_avg_ga, 2),
            },
            "form_last_5": {
                "sequence": form["sequence"],
                "points": form["points"],
                "percentage": form["percentage"],
            },
        })

    return "\n".join(report_lines), stats_output


def main():
    api_key = get_api_key()
    print("API key cargada correctamente.\n")

    # 1. Descargar partidos
    matches = fetch_matches(api_key)

    if not matches:
        print("\nNo se encontraron partidos. Verifica tu API key y que el plan gratuito")
        print("tenga acceso a las competiciones solicitadas.")
        sys.exit(1)

    # Guardar partidos raw
    raw_path = os.path.join(os.path.dirname(__file__), "data_matches.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    print(f"\nPartidos guardados en: {raw_path}")

    # 2. Calcular estadísticas
    print("\nCalculando estadísticas por equipo...")
    teams = calculate_team_stats(matches)

    # 3. Generar informe
    report_text, stats_data = format_report(teams)
    print(report_text)

    # 4. Guardar estadísticas en JSON
    stats_path = os.path.join(os.path.dirname(__file__), "team_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_data, f, ensure_ascii=False, indent=2)
    print(f"\nEstadísticas guardadas en: {stats_path}")

    print(f"\n{'=' * 80}")
    print(f"Equipos analizados: {len(stats_data)}")
    print(f"Total partidos procesados: {len(matches)}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
