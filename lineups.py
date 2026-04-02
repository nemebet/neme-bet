"""
LINEUPS.PY — Alineaciones en tiempo real para NEME BET
═══════════════════════════════════════════════════════
Fuentes: API-Football > SofaScore > BeSoccer > Google News
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LINEUPS_CACHE = os.path.join(BASE_DIR, "lineups_cache.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
}

def _load_env_key(name):
    val = os.environ.get(name, "")
    if val:
        return val
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith(name + "="):
                    return line.strip().split("=", 1)[1]
    return ""


def _load_cache():
    if os.path.exists(LINEUPS_CACHE):
        try:
            with open(LINEUPS_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(data):
    with open(LINEUPS_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cache_key(home, away):
    today = datetime.now().strftime("%Y-%m-%d")
    return f"{home.lower()}_{away.lower()}_{today}"


# ═══════════════════════════════════════════════════════════════
#  FUENTE 1: API-Football /fixtures/lineups
# ═══════════════════════════════════════════════════════════════

def _search_fixture_id(home, away):
    """Busca el fixture ID en API-Football para hoy."""
    key = _load_env_key("API_FOOTBALL_KEY")
    if not key:
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today}"
    req = urllib.request.Request(url)
    req.add_header("x-apisports-key", key)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        for fix in data.get("response", []):
            teams = fix.get("teams", {})
            h = teams.get("home", {}).get("name", "").lower()
            a = teams.get("away", {}).get("name", "").lower()
            if (home.lower() in h or h in home.lower()) and \
               (away.lower() in a or a in away.lower()):
                return fix.get("fixture", {}).get("id")
    except Exception:
        pass
    return None


def fetch_lineup_api_football(home, away):
    """Obtiene alineaciones de API-Football."""
    key = _load_env_key("API_FOOTBALL_KEY")
    if not key:
        return None

    fix_id = _search_fixture_id(home, away)
    if not fix_id:
        return None

    url = f"https://v3.football.api-sports.io/fixtures/lineups?fixture={fix_id}"
    req = urllib.request.Request(url)
    req.add_header("x-apisports-key", key)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        lineups = data.get("response", [])
        if not lineups:
            return None

        result = {"source": "API-Football", "confirmed_at": datetime.now().isoformat(), "teams": []}

        for team_data in lineups:
            team = team_data.get("team", {})
            formation = team_data.get("formation", "?")
            starters = []
            for p in team_data.get("startXI", []):
                player = p.get("player", {})
                starters.append({
                    "name": player.get("name", "?"),
                    "number": player.get("number", 0),
                    "pos": player.get("pos", "?"),
                })

            subs = []
            for p in team_data.get("substitutes", []):
                player = p.get("player", {})
                subs.append({
                    "name": player.get("name", "?"),
                    "number": player.get("number", 0),
                    "pos": player.get("pos", "?"),
                })

            result["teams"].append({
                "name": team.get("name", "?"),
                "formation": formation,
                "starters": starters,
                "substitutes": subs[:5],
            })

        return result
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  FUENTE 2: Google News RSS
# ═══════════════════════════════════════════════════════════════

def fetch_lineup_news(team_name):
    """Busca noticias de alineacion confirmada en Google News."""
    queries = [
        f"{team_name} confirmed lineup today",
        f"{team_name} alineacion confirmada hoy",
        f"{team_name} starting XI",
    ]

    news = []
    for q in queries:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml = resp.read().decode("utf-8", errors="replace")
            items = re.findall(
                r"<item>.*?<title>([^<]+)</title>.*?<pubDate>([^<]+)</pubDate>.*?</item>",
                xml, re.DOTALL)
            cutoff = datetime.now() - timedelta(hours=12)
            for title, pubdate in items:
                try:
                    dt = datetime.strptime(pubdate.strip()[:25], "%a, %d %b %Y %H:%M:%S")
                except ValueError:
                    dt = datetime.now()
                if dt < cutoff:
                    continue
                tl = title.lower()
                if any(k in tl for k in ["lineup", "starting xi", "team news",
                                          "alineacion", "titulares", "xi confirmado"]):
                    news.append({
                        "title": title.strip(),
                        "date": dt.strftime("%Y-%m-%d %H:%M"),
                        "hours_ago": int((datetime.now() - dt).total_seconds() / 3600),
                    })
        except Exception:
            pass

    news.sort(key=lambda x: x.get("hours_ago", 99))
    return news[:5]


# ═══════════════════════════════════════════════════════════════
#  MAIN API
# ═══════════════════════════════════════════════════════════════

def get_lineup(home, away, force_refresh=False):
    """
    Obtiene alineacion para un partido.
    Retorna dict con alineaciones o None si no disponible.
    Cachea resultados por 30 minutos.
    """
    cache = _load_cache()
    key = _cache_key(home, away)

    # Check cache (30 min TTL)
    if not force_refresh and key in cache:
        cached = cache[key]
        cached_at = cached.get("confirmed_at", "")
        if cached_at:
            try:
                dt = datetime.fromisoformat(cached_at)
                if (datetime.now() - dt).total_seconds() < 1800:  # 30 min
                    cached["from_cache"] = True
                    return cached
            except Exception:
                pass

    # Try sources in order
    print(f"[LINEUPS] Buscando alineacion: {home} vs {away}")

    # 1. API-Football
    result = fetch_lineup_api_football(home, away)
    if result and result.get("teams"):
        print(f"  -> API-Football: alineacion encontrada")
        cache[key] = result
        _save_cache(cache)
        return result

    # 2. Google News (info, not full lineup)
    h_news = fetch_lineup_news(home)
    a_news = fetch_lineup_news(away)

    if h_news or a_news:
        result = {
            "source": "Google News",
            "confirmed": False,
            "confirmed_at": datetime.now().isoformat(),
            "news": {"home": h_news, "away": a_news},
            "teams": [],
        }
        cache[key] = result
        _save_cache(cache)
        return result

    # No lineup available
    return {
        "source": None,
        "confirmed": False,
        "confirmed_at": None,
        "message": "Alineacion no confirmada — se actualizara automaticamente",
        "teams": [],
    }


def format_lineup_html(lineup_data, home, away):
    """Genera HTML para mostrar alineaciones en la app."""
    if not lineup_data or not lineup_data.get("teams"):
        # No lineup yet
        confirmed = lineup_data.get("confirmed", False) if lineup_data else False
        news = lineup_data.get("news", {}) if lineup_data else {}

        html = '<div style="padding:12px;background:var(--bg3);border-radius:10px;margin-top:10px">'
        html += '<div style="font-size:13px;color:var(--text2);text-align:center">'
        html += 'Alineacion no confirmada — se actualizara automaticamente'
        html += '</div>'

        # Show news if available
        for team, items in news.items():
            if items:
                html += f'<div style="margin-top:8px;font-size:12px;color:var(--text2)">'
                for n in items[:2]:
                    html += f'<div style="margin:3px 0">- {n["title"][:70]}... (hace {n["hours_ago"]}h)</div>'
                html += '</div>'

        html += '</div>'
        return html

    # Has lineup data
    confirmed_at = lineup_data.get("confirmed_at", "")
    source = lineup_data.get("source", "?")

    # Calculate "hace X minutos"
    time_str = ""
    if confirmed_at:
        try:
            dt = datetime.fromisoformat(confirmed_at)
            mins = int((datetime.now() - dt).total_seconds() / 60)
            if mins < 60:
                time_str = f"Confirmada hace {mins} minutos"
            else:
                time_str = f"Confirmada hace {mins // 60}h {mins % 60}m"
        except Exception:
            pass

    html = '<div style="margin-top:10px">'
    html += f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
    html += f'<span style="font-size:14px;font-weight:700;color:var(--green)">Alineaciones oficiales</span>'
    if time_str:
        html += f'<span style="font-size:11px;color:var(--text2)">{time_str}</span>'
    html += '</div>'

    for team in lineup_data["teams"]:
        name = team.get("name", "?")
        formation = team.get("formation", "?")

        html += f'<div style="background:var(--bg3);border-radius:10px;padding:12px;margin-bottom:8px">'
        html += f'<div style="display:flex;justify-content:space-between;margin-bottom:6px">'
        html += f'<span style="font-weight:700;font-size:14px">{name}</span>'
        html += f'<span style="color:var(--green);font-weight:600;font-size:13px">{formation}</span>'
        html += f'</div>'

        # Starters
        for p in team.get("starters", []):
            pos_color = {"G": "#F5A623", "D": "#4A9EFF", "M": "#1AE89B", "F": "#FF4757"}.get(p.get("pos", "?"), "#888")
            html += f'<div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:13px">'
            html += f'<span style="width:18px;text-align:center;color:{pos_color};font-weight:700;font-size:11px">{p.get("pos","")}</span>'
            html += f'<span style="color:var(--text2);width:20px;text-align:right;font-size:11px">{p.get("number","")}</span>'
            html += f'<span>{p.get("name","?")}</span>'
            html += '</div>'

        html += '</div>'

    html += '</div>'
    return html
