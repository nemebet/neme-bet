"""
BESOCCER_SCRAPER.PY — Scraper de partidos del dia para NEME BET
═══════════════════════════════════════════════════════════════
Fuentes: BeSoccer.com -> Flashscore.com (fallback)
Extrae partidos del dia filtrados por ligas relevantes.
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, date
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from data_dir import data_path
OUTPUT_PATH = data_path("partidos_hoy.json")

LIGAS_RELEVANTES = {
    # Nombre parcial -> nombre normalizado
    "betplay": "Liga BetPlay Colombia",
    "colombia": "Liga BetPlay Colombia",
    "liga profesional argentina": "Liga Argentina",
    "argentina": "Liga Argentina",
    "premier league": "Premier League",
    "la liga": "La Liga",
    "serie a": "Serie A",
    "bundesliga": "Bundesliga",
    "ligue 1": "Ligue 1",
    "champions league": "Champions League",
    "europa league": "Europa League",
    "mls": "MLS",
    "eredivisie": "Eredivisie",
    "liga portugal": "Liga Portugal",
    "championship": "Championship",
    "copa libertadores": "Copa Libertadores",
    "copa sudamericana": "Copa Sudamericana",
    "serie a brazil": "Serie A Brasil",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def _fetch_url(url, timeout=12):
    """Fetch URL con headers de navegador."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [ERROR] {url}: {e}")
        return None


def _match_liga(nombre):
    """Verifica si una liga es relevante y retorna su nombre normalizado."""
    nl = nombre.lower().strip()
    for key, val in LIGAS_RELEVANTES.items():
        if key in nl:
            return val
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  FUENTE 1: BESOCCER
# ═══════════════════════════════════════════════════════════════════════════

def scrape_besoccer():
    """Scrape partidos del dia desde BeSoccer."""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://www.besoccer.com/livescore/{today}"
    print(f"  BeSoccer: {url}")

    html = _fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    partidos = []

    # BeSoccer agrupa partidos por competicion
    panels = soup.find_all("div", class_=re.compile(r"panel|match-group|competition"))
    if not panels:
        panels = soup.find_all("div", class_=re.compile(r"league|comp"))

    # Fallback: buscar patron general de partidos
    rows = soup.find_all(["div", "a"], class_=re.compile(r"match|game|fixture"))

    current_liga = ""
    for row in rows:
        # Intentar extraer liga del contexto padre
        parent = row.find_parent(class_=re.compile(r"panel|group|comp|league"))
        if parent:
            header = parent.find(class_=re.compile(r"head|title|name|comp"))
            if header:
                current_liga = header.get_text(strip=True)

        # Extraer equipos
        teams = row.find_all(class_=re.compile(r"team|name|home|away"))
        if len(teams) >= 2:
            home = teams[0].get_text(strip=True)
            away = teams[1].get_text(strip=True)

            if not home or not away or len(home) < 2 or len(away) < 2:
                continue

            # Hora
            time_el = row.find(class_=re.compile(r"time|hour|clock|date"))
            hora = time_el.get_text(strip=True) if time_el else ""

            liga_norm = _match_liga(current_liga)

            partidos.append({
                "home": home,
                "away": away,
                "liga": liga_norm or current_liga,
                "liga_raw": current_liga,
                "hora": hora,
                "fecha": today,
                "source": "besoccer",
                "relevant": liga_norm is not None,
            })

    return partidos


# ═══════════════════════════════════════════════════════════════════════════
#  FUENTE 2: FLASHSCORE (Fallback)
# ═══════════════════════════════════════════════════════════════════════════

def scrape_flashscore():
    """Scrape partidos desde Flashscore como fallback."""
    url = "https://www.flashscore.com/"
    print(f"  Flashscore: {url}")

    html = _fetch_url(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    partidos = []
    today = date.today().strftime("%Y-%m-%d")

    events = soup.find_all(class_=re.compile(r"event|sportName|match"))
    current_liga = ""

    for ev in events:
        # Liga header
        if any(c in (ev.get("class") or []) for c in ["event__title", "sportName"]):
            current_liga = ev.get_text(strip=True)
            continue

        teams = ev.find_all(class_=re.compile(r"participant|team|home|away"))
        if len(teams) >= 2:
            home = teams[0].get_text(strip=True)
            away = teams[1].get_text(strip=True)
            if not home or not away:
                continue

            time_el = ev.find(class_=re.compile(r"time|event__time"))
            hora = time_el.get_text(strip=True) if time_el else ""

            liga_norm = _match_liga(current_liga)
            partidos.append({
                "home": home, "away": away,
                "liga": liga_norm or current_liga,
                "liga_raw": current_liga,
                "hora": hora, "fecha": today,
                "source": "flashscore",
                "relevant": liga_norm is not None,
            })

    return partidos


# ═══════════════════════════════════════════════════════════════════════════
#  FUENTE 3: FOOTBALL-DATA.ORG API (mas confiable)
# ═══════════════════════════════════════════════════════════════════════════

def scrape_football_data():
    """Obtiene partidos del dia via football-data.org API."""
    env = {}
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip()
    key = os.environ.get("FOOTBALL_DATA_API_KEY", env.get("FOOTBALL_DATA_API_KEY", ""))
    if not key:
        return []

    today = date.today().strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/matches?dateFrom={today}&dateTo={today}"
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", key)

    print(f"  football-data.org: partidos de {today}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [ERROR] football-data.org: {e}")
        return []

    partidos = []
    for m in data.get("matches", []):
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        comp = m.get("competition", {}).get("name", "")
        utc = m.get("utcDate", "")
        hora = utc[11:16] if len(utc) > 16 else ""
        status = m.get("status", "")

        if status not in ("TIMED", "SCHEDULED", ""):
            continue

        liga_norm = _match_liga(comp)
        partidos.append({
            "home": home, "away": away,
            "liga": liga_norm or comp,
            "liga_raw": comp,
            "hora": hora, "fecha": today,
            "source": "football-data.org",
            "relevant": liga_norm is not None,
            "match_id": m.get("id"),
        })

    return partidos


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def scrape_today():
    """
    Scrape partidos del dia de todas las fuentes.
    Prioridad: football-data.org > BeSoccer > Flashscore
    """
    print(f"\n[SCRAPER] {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    all_matches = []

    # 1. football-data.org (API, mas confiable)
    fd = scrape_football_data()
    if fd:
        all_matches.extend(fd)
        print(f"  football-data.org: {len(fd)} partidos")

    # 2. BeSoccer (scraping)
    if len(all_matches) < 5:
        bs = scrape_besoccer()
        if bs:
            all_matches.extend(bs)
            print(f"  BeSoccer: {len(bs)} partidos")

    # 3. Flashscore (fallback)
    if len(all_matches) < 5:
        fs = scrape_flashscore()
        if fs:
            all_matches.extend(fs)
            print(f"  Flashscore: {len(fs)} partidos")

    # Dedup por home+away
    seen = set()
    unique = []
    for m in all_matches:
        key = (m["home"].lower(), m["away"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(m)

    # Filtrar relevantes
    relevant = [m for m in unique if m.get("relevant")]
    print(f"  Total: {len(unique)} | Relevantes: {len(relevant)}")

    # Guardar
    output = {
        "date": date.today().isoformat(),
        "scraped_at": datetime.now().isoformat(),
        "total": len(unique),
        "relevant": len(relevant),
        "matches_all": unique,
        "matches_relevant": relevant,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  Guardado en: {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    result = scrape_today()
    print(f"\nPartidos relevantes del dia:")
    for m in result["matches_relevant"]:
        print(f"  {m['hora']} {m['home']} vs {m['away']} ({m['liga']})")
