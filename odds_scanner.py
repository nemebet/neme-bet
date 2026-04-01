"""
ODDS_SCANNER.PY — Scanner de Cuotas para NEME BET
═══════════════════════════════════════════════════
Escanea cuotas de mercado via web scraping y las compara
con las probabilidades del modelo para detectar value bets.

Fuentes:
  - Odds API (free tier, 500 req/month)
  - Google search scraping (fallback)
  - Manual input

Funcionalidades:
  1. Escanear cuotas de multiples casas
  2. Calcular edge (ventaja) modelo vs mercado
  3. Detectar value bets (edge > umbral)
  4. Calcular stakes optimos (criterio de Kelly)
"""

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    env = {}
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


# ═══════════════════════════════════════════════════════════════════════════
#  SCRAPING DE CUOTAS
# ═══════════════════════════════════════════════════════════════════════════

def scrape_odds_google(home, away):
    """
    Busca cuotas en Google para un partido.
    Google a veces muestra cuotas directamente en los resultados de busqueda.
    """
    query = f"{home} vs {away} odds betting"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")

    odds_found = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read().decode("utf-8", errors="replace")

        # Buscar patrones de cuotas en titulos
        titles = re.findall(r"<title>([^<]+)</title>", xml)
        for title in titles:
            # Patron: "1.85" o "2/1" o "+150"
            decimal_odds = re.findall(r'\b(\d+\.\d{2})\b', title)
            if len(decimal_odds) >= 2:
                odds_found.append({
                    "source": "Google News",
                    "title": title.strip()[:100],
                    "odds_raw": decimal_odds[:3],
                })
    except Exception:
        pass

    return odds_found


def fetch_odds_api(home, away, api_key=None):
    """
    Usa The Odds API (free tier: 500 req/month) para obtener cuotas reales.
    Registro: https://the-odds-api.com/
    """
    if not api_key:
        return None

    # Buscar en deportes de futbol
    for sport in ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
                   "soccer_germany_bundesliga", "soccer_france_ligue_one",
                   "soccer_uefa_champs_league"]:
        url = (f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
               f"?apiKey={api_key}&regions=eu&markets=h2h&oddsFormat=decimal")
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            for event in data:
                h = event.get("home_team", "").lower()
                a = event.get("away_team", "").lower()
                if (home.lower() in h or h in home.lower()) and \
                   (away.lower() in a or a in away.lower()):
                    bookmakers = []
                    for bm in event.get("bookmakers", []):
                        for market in bm.get("markets", []):
                            if market["key"] == "h2h":
                                outcomes = {o["name"]: o["price"]
                                            for o in market.get("outcomes", [])}
                                bookmakers.append({
                                    "name": bm["title"],
                                    "home": outcomes.get(event["home_team"], 0),
                                    "draw": outcomes.get("Draw", 0),
                                    "away": outcomes.get(event["away_team"], 0),
                                    "updated": bm.get("last_update", ""),
                                })
                    if bookmakers:
                        return {
                            "home_team": event["home_team"],
                            "away_team": event["away_team"],
                            "bookmakers": bookmakers,
                            "commence": event.get("commence_time", ""),
                        }
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  CALCULO DE VALUE BETS
# ═══════════════════════════════════════════════════════════════════════════

def implied_prob(odds):
    """Convierte cuota decimal a probabilidad implicita."""
    if odds <= 1.0:
        return 0
    return round(1 / odds * 100, 2)


def calculate_edge(model_prob, market_odds):
    """
    Calcula edge (ventaja) del modelo vs mercado.
    edge = probabilidad_modelo - probabilidad_implicita_mercado
    Positivo = value bet (el modelo ve mas probabilidad que el mercado).
    """
    if market_odds <= 1.0:
        return 0
    market_prob = implied_prob(market_odds)
    return round(model_prob - market_prob, 2)


def kelly_fraction(model_prob, market_odds, fraction=0.25):
    """
    Calcula fraccion de Kelly para sizing optimo.
    fraction=0.25 = Kelly cuarto (mas conservador).

    Kelly = (p * odds - 1) / (odds - 1)
    donde p = probabilidad del modelo (decimal)
    """
    p = model_prob / 100
    if market_odds <= 1.0 or p <= 0:
        return 0
    kelly = (p * market_odds - 1) / (market_odds - 1)
    if kelly <= 0:
        return 0
    return round(kelly * fraction * 100, 2)  # % del bankroll


def scan_match(prediction, market_odds=None, odds_api_key=None):
    """
    Escanea cuotas para un partido y calcula value bets.

    Args:
        prediction: dict con p1, px, p2, o25, btts_y, etc.
        market_odds: dict manual {home: 2.10, draw: 3.20, away: 3.50}
        odds_api_key: key para The Odds API (opcional)

    Returns:
        dict con analisis de value
    """
    home = prediction.get("home", prediction.get("home_team", "?"))
    away = prediction.get("away", prediction.get("away_team", "?"))

    # Obtener cuotas
    odds_sources = []

    # 1. Cuotas manuales
    if market_odds:
        odds_sources.append({
            "name": "Manual",
            "home": market_odds.get("home", 0),
            "draw": market_odds.get("draw", 0),
            "away": market_odds.get("away", 0),
        })

    # 2. The Odds API
    if odds_api_key:
        api_result = fetch_odds_api(home, away, odds_api_key)
        if api_result:
            for bm in api_result.get("bookmakers", []):
                odds_sources.append(bm)

    # 3. Scraping Google (fallback info)
    google_odds = scrape_odds_google(home, away)

    # Analizar value para cada fuente de cuotas
    p1 = prediction.get("p1", prediction.get("p_home_win", 33))
    px = prediction.get("px", prediction.get("p_draw", 33))
    p2 = prediction.get("p2", prediction.get("p_away_win", 33))

    value_bets = []

    for source in odds_sources:
        for outcome, prob, odds_key in [
            ("1 Local", p1, "home"),
            ("X Empate", px, "draw"),
            ("2 Visitante", p2, "away"),
        ]:
            odds = source.get(odds_key, 0)
            if odds <= 1.0:
                continue

            edge = calculate_edge(prob, odds)
            kelly = kelly_fraction(prob, odds)
            impl = implied_prob(odds)

            bet_info = {
                "match": f"{home} vs {away}",
                "outcome": outcome,
                "model_prob": prob,
                "market_odds": odds,
                "market_prob": impl,
                "edge": edge,
                "kelly_pct": kelly,
                "source": source.get("name", "?"),
                "is_value": edge > 5,  # >5% edge = value bet
            }
            value_bets.append(bet_info)

    # Ordenar por edge descendente
    value_bets.sort(key=lambda x: x["edge"], reverse=True)

    return {
        "match": f"{home} vs {away}",
        "model": {"p1": p1, "px": px, "p2": p2},
        "odds_sources": len(odds_sources),
        "google_info": len(google_odds),
        "value_bets": value_bets,
        "best_value": value_bets[0] if value_bets and value_bets[0]["edge"] > 0 else None,
    }


def scan_all(predictions, market_odds_list=None, odds_api_key=None):
    """
    Escanea cuotas para multiples partidos.

    Args:
        predictions: lista de dicts de prediccion
        market_odds_list: lista de dicts de cuotas (mismo orden que predictions)
        odds_api_key: key para The Odds API

    Returns:
        lista de resultados de escaneo
    """
    results = []
    for i, pred in enumerate(predictions):
        odds = None
        if market_odds_list and i < len(market_odds_list):
            odds = market_odds_list[i]
        result = scan_match(pred, odds, odds_api_key)
        results.append(result)
    return results


def format_value_report(scan_results):
    """Formatea reporte de value bets para display."""
    lines = [
        "SCANNER DE CUOTAS — NEME BET",
        "=" * 45,
    ]

    all_values = []
    for result in scan_results:
        for vb in result.get("value_bets", []):
            if vb["is_value"]:
                all_values.append(vb)

    if not all_values:
        lines.append("")
        lines.append("Sin value bets detectadas.")
        lines.append("Ingresa cuotas manualmente o configura The Odds API.")
        return "\n".join(lines)

    lines.append(f"\n{len(all_values)} VALUE BETS ENCONTRADAS:\n")

    for i, vb in enumerate(sorted(all_values, key=lambda x: x["edge"], reverse=True), 1):
        lines.append(f"  #{i} {vb['outcome']}")
        lines.append(f"     {vb['match']}")
        lines.append(f"     Modelo: {vb['model_prob']:.1f}%  |  Mercado: {vb['market_prob']:.1f}% ({vb['market_odds']:.2f})")
        lines.append(f"     Edge: +{vb['edge']:.1f}%  |  Kelly: {vb['kelly_pct']:.1f}% del bankroll")
        lines.append(f"     Fuente: {vb['source']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print("\nNEME BET — Scanner de Cuotas")
    print("=" * 40)
    print("\nEjemplo con cuotas manuales:\n")

    # Ejemplo
    pred = {"home": "Real Madrid", "away": "Barcelona",
            "p1": 60.0, "px": 22.0, "p2": 18.0}
    odds = {"home": 1.90, "draw": 3.40, "away": 4.50}

    result = scan_match(pred, odds)
    print(format_value_report([result]))
