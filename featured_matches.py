"""
FEATURED_MATCHES.PY — Partidos destacados para la landing page
══════════════════════════════════════════════════════════════
Obtiene los 6 partidos mas relevantes de las proximas 12 horas.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from data_dir import data_path

FEATURED_PATH = data_path("featured_matches.json")
CACHE_TTL = 3600  # 1 hora

TOP_LEAGUES = {
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League",
    "Primera Division", "Eredivisie", "Liga Portugal",
}

TOP_TEAMS = {
    # Premier League
    "manchester city", "arsenal", "liverpool", "chelsea", "manchester united",
    "tottenham", "newcastle",
    # La Liga
    "real madrid", "barcelona", "atletico", "real sociedad",
    # Serie A
    "inter", "napoli", "juventus", "milan", "atalanta",
    # Bundesliga
    "bayern", "dortmund", "leverkusen", "leipzig",
    # Ligue 1
    "paris saint-germain", "marseille", "monaco",
    # South America
    "boca juniors", "river plate", "flamengo", "palmeiras",
    "atletico nacional", "millonarios",
}


def _load_env_key(name):
    val = os.environ.get(name, "")
    if val:
        return val
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith(name + "="):
                    return line.strip().split("=", 1)[1]
    return ""


def _is_top_team(name):
    nl = name.lower()
    return any(t in nl for t in TOP_TEAMS)


def _relevance_score(match):
    """Calcula score de relevancia (mayor = mas relevante)."""
    score = 0
    comp = match.get("competition", "")
    if comp in TOP_LEAGUES:
        score += 10
    if "Champions" in comp:
        score += 15
    home = match.get("home", "")
    away = match.get("away", "")
    if _is_top_team(home):
        score += 5
    if _is_top_team(away):
        score += 5
    if _is_top_team(home) and _is_top_team(away):
        score += 10  # Derby / big match bonus
    return score


def fetch_featured():
    """Obtiene partidos destacados de las proximas 12 horas."""

    # Check cache
    if os.path.exists(FEATURED_PATH):
        try:
            mtime = os.path.getmtime(FEATURED_PATH)
            import time
            if time.time() - mtime < CACHE_TTL:
                with open(FEATURED_PATH, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    key = _load_env_key("FOOTBALL_DATA_API_KEY")
    if not key:
        return {"matches": [], "updated": datetime.now().isoformat()}

    now = datetime.now()
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    url = f"https://api.football-data.org/v4/matches?dateFrom={date_from}&dateTo={date_to}"
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", key)

    matches = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        for m in data.get("matches", []):
            status = m.get("status", "")
            if status not in ("TIMED", "SCHEDULED"):
                continue

            utc_date = m.get("utcDate", "")
            if not utc_date:
                continue

            # Parse UTC time
            try:
                match_time = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
                match_local = match_time.replace(tzinfo=None)  # Simplified
            except Exception:
                continue

            # Only next 12 hours
            if match_local > now + timedelta(hours=12):
                continue
            if match_local < now - timedelta(minutes=30):
                continue

            home = m.get("homeTeam", {}).get("name", "?")
            away = m.get("awayTeam", {}).get("name", "?")
            comp = m.get("competition", {}).get("name", "?")
            hora = utc_date[11:16] if len(utc_date) > 16 else ""

            # Minutes until start
            delta = match_local - now
            mins_until = max(0, int(delta.total_seconds() / 60))
            hours_until = mins_until // 60
            mins_remainder = mins_until % 60

            entry = {
                "home": home,
                "away": away,
                "competition": comp,
                "hora": hora,
                "mins_until": mins_until,
                "countdown": f"{hours_until}h {mins_remainder}m" if hours_until > 0 else f"{mins_remainder}m",
                "relevance": _relevance_score({
                    "home": home, "away": away, "competition": comp,
                }),
                "is_big_match": _is_top_team(home) and _is_top_team(away),
            }
            matches.append(entry)

    except Exception as e:
        print(f"[FEATURED] Error: {e}")

    # Sort by relevance, take top 6
    matches.sort(key=lambda x: x["relevance"], reverse=True)
    featured = matches[:6]

    # Mark #1 as recommended
    if featured:
        featured[0]["recommended"] = True

    result = {
        "matches": featured,
        "updated": datetime.now().isoformat(),
        "total_found": len(matches),
    }

    # Cache
    with open(FEATURED_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
