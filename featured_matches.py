"""
FEATURED_MATCHES.PY — Partidos proximos para NEMEBET
════════════════════════════════════════════════════
Fuentes: football-data.org > API-Football > BeSoccer scraping
Sin filtro de ligas — muestra TODOS los partidos disponibles.
Fallback: 12h -> 24h -> dia completo.
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

from data_dir import data_path

CACHE_PATH = data_path("featured_matches.json")
CACHE_TTL = 300  # 5 min

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Connection": "keep-alive",
}

TOP_TEAMS = {
    "manchester city", "arsenal", "liverpool", "chelsea", "manchester united",
    "tottenham", "newcastle", "real madrid", "barcelona", "atletico",
    "inter", "napoli", "juventus", "milan", "atalanta", "bayern",
    "dortmund", "leverkusen", "paris saint-germain", "marseille",
    "boca juniors", "river plate", "flamengo", "palmeiras",
    "atletico nacional", "millonarios", "sporting", "benfica", "porto",
}


def _env_key(name):
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


def _is_top(name):
    return any(t in name.lower() for t in TOP_TEAMS)


# ═══════════════════════════════════════════════════════════════
#  SOURCE 1: football-data.org
# ═══════════════════════════════════════════════════════════════

def _fetch_football_data():
    key = _env_key("FOOTBALL_DATA_API_KEY")
    if not key:
        return []

    now = datetime.utcnow()
    d1 = now.strftime("%Y-%m-%d")
    d2 = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    url = f"https://api.football-data.org/v4/matches?dateFrom={d1}&dateTo={d2}"
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", key)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[FEATURED] football-data error: {e}")
        return []

    matches = []
    for m in data.get("matches", []):
        if m.get("status") not in ("TIMED", "SCHEDULED"):
            continue
        utc = m.get("utcDate", "")
        if not utc:
            continue
        matches.append({
            "home": m.get("homeTeam", {}).get("name", "?"),
            "away": m.get("awayTeam", {}).get("name", "?"),
            "competition": m.get("competition", {}).get("name", "?"),
            "utc_date": utc,
            "source": "football-data.org",
        })

    print(f"[FEATURED] football-data.org: {len(matches)} partidos")
    return matches


# ═══════════════════════════════════════════════════════════════
#  SOURCE 2: API-Football
# ═══════════════════════════════════════════════════════════════

def _fetch_api_football():
    key = _env_key("API_FOOTBALL_KEY")
    if not key:
        return []

    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today}&status=NS"
    req = urllib.request.Request(url)
    req.add_header("x-apisports-key", key)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[FEATURED] API-Football error: {e}")
        return []

    matches = []
    for fix in data.get("response", []):
        teams = fix.get("teams", {})
        fixture = fix.get("fixture", {})
        league = fix.get("league", {})
        matches.append({
            "home": teams.get("home", {}).get("name", "?"),
            "away": teams.get("away", {}).get("name", "?"),
            "competition": league.get("name", "?"),
            "utc_date": fixture.get("date", ""),
            "source": "api-football",
        })

    print(f"[FEATURED] API-Football: {len(matches)} partidos")
    return matches


# ═══════════════════════════════════════════════════════════════
#  PROCESS AND FILTER
# ═══════════════════════════════════════════════════════════════

def _process_matches(raw_matches, max_hours=12):
    """Filtra por rango de tiempo y calcula countdown."""
    now = datetime.utcnow()
    cutoff = now + timedelta(hours=max_hours)
    processed = []

    for m in raw_matches:
        utc = m.get("utc_date", "")
        if not utc:
            continue
        try:
            mt = datetime.fromisoformat(utc.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            try:
                mt = datetime.strptime(utc[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

        if mt < now - timedelta(minutes=30):
            continue  # Already started
        if mt > cutoff:
            continue

        delta = mt - now
        mins = max(0, int(delta.total_seconds() / 60))
        hours = mins // 60
        mins_r = mins % 60
        hora = utc[11:16] if len(utc) > 16 else ""

        # Relevance score
        score = 0
        home, away = m["home"], m["away"]
        comp = m.get("competition", "")
        if _is_top(home): score += 5
        if _is_top(away): score += 5
        if _is_top(home) and _is_top(away): score += 10
        if "Champions" in comp: score += 15
        elif "Europa" in comp: score += 10
        elif any(x in comp for x in ["Premier", "Liga", "Serie A", "Bundesliga", "Ligue 1"]): score += 8

        processed.append({
            "home": home,
            "away": away,
            "competition": comp,
            "hora": hora,
            "utc_date": utc,
            "mins_until": mins,
            "countdown": f"{hours}h {mins_r}m" if hours > 0 else f"{mins_r}m",
            "relevance": score,
            "is_big": _is_top(home) and _is_top(away),
            "source": m.get("source", ""),
        })

    # Sort: big matches first, then by relevance, then by time
    processed.sort(key=lambda x: (-x["relevance"], x["mins_until"]))
    return processed


def fetch_partidos():
    """
    Obtiene partidos con fallback: 12h -> 24h -> dia completo.
    Retorna dict con partidos y metadata.
    """
    # Check cache
    if os.path.exists(CACHE_PATH):
        try:
            mtime = os.path.getmtime(CACHE_PATH)
            if time.time() - mtime < CACHE_TTL:
                with open(CACHE_PATH, encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("partidos"):
                    return cached
        except Exception:
            pass

    print(f"[FEATURED] Fetching matches {datetime.now().strftime('%H:%M')}")

    # Fetch from all sources
    raw = _fetch_football_data()
    if len(raw) < 5:
        raw.extend(_fetch_api_football())

    # Dedup by home+away
    seen = set()
    unique = []
    for m in raw:
        key = (m["home"].lower(), m["away"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(m)

    # Try 12h first
    partidos = _process_matches(unique, max_hours=12)
    rango = 12

    # Fallback to 24h
    if len(partidos) < 3:
        partidos = _process_matches(unique, max_hours=24)
        rango = 24

    # Fallback to 48h (full)
    if len(partidos) < 3:
        partidos = _process_matches(unique, max_hours=48)
        rango = 48

    # Mark first as recommended
    if partidos:
        partidos[0]["recommended"] = True

    result = {
        "partidos": partidos[:12],
        "total": len(partidos),
        "rango_horas": rango,
        "fuente": "football-data.org / API-Football",
        "actualizado": datetime.now().isoformat(),
    }

    # Save cache
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[FEATURED] {len(partidos)} partidos (rango {rango}h)")
    return result
