"""
FEATURED_MATCHES.PY — Partidos globales para NEMEBET
═══════════════════════════════════════════════════
Todas las ligas del mundo: Europa, LATAM, Asia, Africa.
Fuentes: API-Football (global) > football-data.org
"""

import json
import os
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

from data_dir import data_path

CACHE_FILE = data_path("featured_matches.json")
CACHE_TTL = 300  # 5 min

_cache_lock = threading.Lock()
_memory_cache = None
_memory_cache_time = 0

# ═══════════════════════════════════════════════════════════
#  ALL LEAGUES BY REGION
# ═══════════════════════════════════════════════════════════

TOP_LEAGUE_IDS = {
    # Europe top
    2, 3, 848, 39, 140, 135, 78, 61, 94, 88, 144, 203, 179,
    # LATAM top
    239, 128, 71, 262, 253, 13, 14, 265, 268, 281, 278,
    # Asia top
    98, 307, 17, 188,
    # Africa
    20, 21,
}

LATAM_IDS = {239, 128, 253, 262, 71, 13, 14, 130, 131, 265, 268, 281, 278, 282, 330, 267, 233, 73}

REGION_MAP = {
    # Europe
    39: "EU", 40: "EU", 140: "EU", 141: "EU", 135: "EU", 136: "EU",
    78: "EU", 79: "EU", 61: "EU", 62: "EU", 94: "EU", 88: "EU",
    144: "EU", 203: "EU", 179: "EU", 207: "EU", 218: "EU", 119: "EU",
    113: "EU", 103: "EU", 106: "EU", 2: "EU", 3: "EU", 848: "EU",
    197: "EU", 235: "EU", 333: "EU", 345: "EU", 283: "EU", 286: "EU",
    210: "EU", 172: "EU", 271: "EU", 332: "EU", 384: "EU",
    # LATAM
    239: "LATAM", 128: "LATAM", 71: "LATAM", 262: "LATAM", 253: "LATAM",
    13: "LATAM", 14: "LATAM", 265: "LATAM", 268: "LATAM", 281: "LATAM",
    278: "LATAM", 282: "LATAM", 330: "LATAM", 267: "LATAM", 130: "LATAM",
    131: "LATAM", 73: "LATAM", 263: "LATAM", 240: "LATAM", 254: "LATAM",
    # Asia
    98: "ASIA", 99: "ASIA", 169: "ASIA", 292: "ASIA", 307: "ASIA",
    435: "ASIA", 290: "ASIA", 323: "ASIA", 188: "ASIA", 17: "ASIA",
    196: "ASIA", 296: "ASIA",
    # Africa
    233: "AFRICA", 200: "AFRICA", 288: "AFRICA", 20: "AFRICA", 21: "AFRICA",
}

TOP_TEAMS = {
    "manchester city", "arsenal", "liverpool", "chelsea", "manchester united",
    "tottenham", "newcastle", "real madrid", "barcelona", "atletico",
    "inter", "napoli", "juventus", "milan", "atalanta", "bayern",
    "dortmund", "leverkusen", "paris saint-germain", "marseille",
    "boca juniors", "river plate", "flamengo", "palmeiras",
    "atletico nacional", "millonarios", "america de cali", "deportivo cali",
    "monterrey", "america", "cruz azul", "guadalajara",
    "sporting", "benfica", "porto", "ajax", "feyenoord",
    "al hilal", "al ahly", "al nassr",
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


# ═══════════════════════════════════════════════════════════
#  FETCH ALL MATCHES (single API call)
# ═══════════════════════════════════════════════════════════

def _fetch_api_football_global():
    """Single call: all matches for today (most efficient)."""
    key = _env_key("API_FOOTBALL_KEY")
    if not key:
        print("[FETCH] API_FOOTBALL_KEY not found — skipping")
        return []

    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today}"
    req = urllib.request.Request(url)
    req.add_header("x-apisports-key", key)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[FETCH] API-Football error: {type(e).__name__}: {e}")
        return []

    matches = []
    finished = {"FT", "AET", "PEN", "AWD", "WO", "CANC", "ABD", "PST"}

    for fix in data.get("response", []):
        try:
            f = fix["fixture"]
            teams = fix["teams"]
            league = fix["league"]
            status = f.get("status", {}).get("short", "")

            if status in finished:
                continue

            lid = league.get("id", 0)
            region = REGION_MAP.get(lid, "OTHER")
            is_latam = lid in LATAM_IDS
            is_top = lid in TOP_LEAGUE_IDS
            is_live = status in ("1H", "2H", "HT", "ET", "P", "BT")

            matches.append({
                "home": teams.get("home", {}).get("name", "?"),
                "away": teams.get("away", {}).get("name", "?"),
                "competition": league.get("name", "?"),
                "country": league.get("country", "?"),
                "utc_date": f.get("date", ""),
                "source": "api-football",
                "league_id": lid,
                "region": region,
                "is_latam": is_latam,
                "is_top": is_top,
                "is_live": is_live,
                "status": status,
            })
        except Exception:
            continue

    print(f"[FETCH] API-Football: {len(matches)} matches from {len(data.get('response', []))} fixtures")
    return matches


def _fetch_football_data():
    """Backup: football-data.org free tier."""
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
        print(f"[FETCH] football-data error: {e}")
        return []

    matches = []
    for m in data.get("matches", []):
        if m.get("status") not in ("TIMED", "SCHEDULED"):
            continue
        matches.append({
            "home": m.get("homeTeam", {}).get("name", "?"),
            "away": m.get("awayTeam", {}).get("name", "?"),
            "competition": m.get("competition", {}).get("name", "?"),
            "country": "",
            "utc_date": m.get("utcDate", ""),
            "source": "football-data.org",
            "league_id": 0,
            "region": "EU",
            "is_latam": False,
            "is_top": True,
            "is_live": False,
            "status": "NS",
        })

    print(f"[FETCH] football-data.org: {len(matches)} matches")
    return matches


# ═══════════════════════════════════════════════════════════
#  PROCESS, SCORE, FILTER
# ═══════════════════════════════════════════════════════════

def _process(raw, max_hours=24):
    now = datetime.utcnow()
    cutoff = now + timedelta(hours=max_hours)
    processed = []

    for m in raw:
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

        # Live matches always included
        if not m.get("is_live"):
            if mt < now - timedelta(minutes=30):
                continue
            if mt > cutoff:
                continue

        delta = mt - now
        mins = max(0, int(delta.total_seconds() / 60))
        hours = mins // 60
        mins_r = mins % 60
        hora = utc[11:16] if len(utc) > 16 else ""

        # Relevance
        score = 0
        home, away, comp = m["home"], m["away"], m.get("competition", "")
        if m.get("is_live"): score += 50
        if m.get("is_top"): score += 12
        if m.get("is_latam"): score += 12
        if _is_top(home): score += 5
        if _is_top(away): score += 5
        if _is_top(home) and _is_top(away): score += 10
        if "Champions" in comp or "Libertadores" in comp: score += 15
        elif "Europa" in comp or "Sudamericana" in comp: score += 10
        elif any(x in comp for x in ["Premier", "Serie A", "Bundesliga", "Ligue 1"]): score += 8
        elif any(x in comp.lower() for x in ["betplay", "liga mx", "mls", "brasileir"]): score += 11

        processed.append({
            "home": home, "away": away,
            "competition": comp,
            "country": m.get("country", ""),
            "hora": hora, "utc_date": utc,
            "mins_until": mins,
            "countdown": "EN VIVO" if m.get("is_live") else (f"{hours}h {mins_r}m" if hours > 0 else f"{mins_r}m"),
            "relevance": score,
            "region": m.get("region", "OTHER"),
            "is_top": m.get("is_top", False),
            "is_latam": m.get("is_latam", False),
            "is_live": m.get("is_live", False),
            "is_big": _is_top(home) and _is_top(away),
            "recommended": False,
            "source": m.get("source", ""),
        })

    # Sort: live first, then relevance, then time
    processed.sort(key=lambda x: (-50 if x["is_live"] else 0, -x["relevance"], x["mins_until"]))

    if processed:
        processed[0]["recommended"] = True

    return processed


# ═══════════════════════════════════════════════════════════
#  MAIN — with memory cache + disk cache + thread safety
# ═══════════════════════════════════════════════════════════

def fetch_partidos(force=False):
    """Main function: fetch all global matches with smart cache."""
    global _memory_cache, _memory_cache_time

    now = time.time()

    # 1. Memory cache (fastest)
    if not force and _memory_cache and (now - _memory_cache_time) < CACHE_TTL:
        return _memory_cache

    with _cache_lock:
        # Double-check after acquiring lock
        if not force and _memory_cache and (now - _memory_cache_time) < CACHE_TTL:
            return _memory_cache

        # 2. Disk cache
        if not force and os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                age = now - mtime
                if age < CACHE_TTL:
                    with open(CACHE_FILE, encoding="utf-8") as f:
                        cached = json.load(f)
                    if cached.get("partidos"):
                        _memory_cache = cached
                        _memory_cache_time = now
                        return cached
            except Exception as e:
                print(f"[CACHE] Error reading: {e}")

        # 3. Fetch fresh data
        print(f"[FEATURED] Fetching global {datetime.now().strftime('%H:%M')}")

        raw = _fetch_api_football_global()
        if len(raw) < 10:
            raw.extend(_fetch_football_data())

        # Dedup
        seen = set()
        unique = []
        for m in raw:
            key = (m["home"].lower(), m["away"].lower())
            if key not in seen:
                seen.add(key)
                unique.append(m)

        # Process with 24h window (fallback to 48h)
        partidos = _process(unique, 24)
        rango = 24
        if len(partidos) < 3:
            partidos = _process(unique, 48)
            rango = 48

        # Region counts
        regions = {}
        for p in partidos:
            r = p.get("region", "OTHER")
            regions[r] = regions.get(r, 0) + 1

        result = {
            "partidos": partidos[:100],
            "total": len(partidos),
            "en_vivo": sum(1 for p in partidos if p.get("is_live")),
            "rango_horas": rango,
            "fuente": "API-Football global",
            "actualizado": datetime.now().isoformat(),
            "regions": regions,
            "live_count": sum(1 for p in partidos if p.get("is_live")),
        }

        # 4. Save to disk and memory
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            print(f"[CACHE] Error saving: {e}")

        _memory_cache = result
        _memory_cache_time = time.time()

        live = result["live_count"]
        print(f"[FEATURED] {len(partidos)} partidos ({live} live) | Regions: {regions}")
        return result
