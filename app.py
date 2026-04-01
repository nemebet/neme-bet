#!/usr/bin/env python3
"""
APP.PY — Predictor Autonomo de Apuestas v2.0
═════════════════════════════════════════════
Recibe partidos en texto plano, busca noticias automaticamente,
corre el modelo ensemble v5 y selecciona los mejores picks del dia.

Uso:
  python3 app.py "Real Madrid vs Barcelona, Man City vs Liverpool"
  python3 app.py                          # Modo interactivo
  python3 app.py --resultado "R.Madrid vs Barcelona" 2 1
  python3 app.py --accuracy               # Ver estadisticas de acierto

Fuentes de datos:
  - football-data.org (partidos, equipos, stats) — KEY en .env
  - Google News RSS (noticias de lesiones, ultimas 48h) — gratis
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
import time
from datetime import datetime, timedelta
from math import exp, lgamma, log
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURACION
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_env():
    env = {}
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

ENV = load_env()
FOOTBALL_DATA_KEY = ENV.get("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# Modelo
MAX_GOALS = 8
W_POISSON = 0.40
W_DIXON_COLES = 0.30
W_ELO = 0.30
DC_RHO = -0.13
ELO_INITIAL = 1500
ELO_K = 40
ELO_HOME_ADVANTAGE = 100

# Seleccion de picks
MIN_PROBABILITY = 65.0
MIN_EDGE = 15.0
MIN_SUBMODELS_AGREE = 2

# Rate limit: football-data.org free = 10 req/min
_last_request_time = 0
REQUEST_INTERVAL = 6.5  # segundos entre requests

# ═══════════════════════════════════════════════════════════════════════════
#  HTTP CON RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════

def _rate_limit():
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def football_data_get(endpoint, params=None):
    """GET request a football-data.org con rate limiting."""
    _rate_limit()
    url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", FOOTBALL_DATA_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"    [RATE LIMIT] Esperando 60s...")
            time.sleep(60)
            return football_data_get(endpoint, params)
        print(f"    [API ERROR] {e.code}: {endpoint}")
        return {}
    except Exception as e:
        print(f"    [ERROR] {endpoint}: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIONES MATEMATICAS (Modelo Ensemble v5)
# ═══════════════════════════════════════════════════════════════════════════

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(k * log(max(lam, 1e-10)) - lam - lgamma(k + 1))


def prob_to_odds(p):
    return round(100 / p, 2) if p > 0 else 99.99


def dixon_coles_tau(h, a, lh, la, rho=DC_RHO):
    if h == 0 and a == 0: return 1.0 - lh * la * rho
    if h == 0 and a == 1: return 1.0 + lh * rho
    if h == 1 and a == 0: return 1.0 + la * rho
    if h == 1 and a == 1: return 1.0 - rho
    return 1.0


def build_dc_matrix(lh, la, rho=DC_RHO):
    m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            tau = max(dixon_coles_tau(h, a, lh, la, rho), 0.001)
            m[(h, a)] = poisson_pmf(h, lh) * poisson_pmf(a, la) * tau
    t = sum(m.values())
    return {k: v / t for k, v in m.items()} if t > 0 else m


def extract_markets(matrix):
    t = sum(matrix.values())
    if t == 0:
        return {"1": 1/3, "X": 1/3, "2": 1/3, "btts": 0.5, "o25": 0.5, "o15": 0.5}
    return {
        "1":    sum(p for (h, a), p in matrix.items() if h > a) / t,
        "X":    sum(p for (h, a), p in matrix.items() if h == a) / t,
        "2":    sum(p for (h, a), p in matrix.items() if h < a) / t,
        "btts": sum(p for (h, a), p in matrix.items() if h > 0 and a > 0) / t,
        "o25":  sum(p for (h, a), p in matrix.items() if h + a > 2.5) / t,
        "o15":  sum(p for (h, a), p in matrix.items() if h + a > 1.5) / t,
    }


def elo_expected_goals(elo_h, elo_a, avg_gf):
    diff = elo_h - elo_a + ELO_HOME_ADVANTAGE
    sr = 10 ** (diff / 400)
    total = avg_gf * 2
    return max(0.3, min(total * sr / (1 + sr), 4.5)), max(0.2, min(total / (1 + sr), 4.0))


# ═══════════════════════════════════════════════════════════════════════════
#  1. PARSER DE PARTIDOS
# ═══════════════════════════════════════════════════════════════════════════

def parse_matches(text):
    parts = re.split(r'[,;\n]+', text.strip())
    matches = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        teams = re.split(r'\s+(?:vs\.?|VS\.?|v\.?|contra|-)\s+', part, maxsplit=1)
        if len(teams) == 2:
            home = teams[0].strip()
            away = teams[1].strip()
            if home and away:
                matches.append((home, away))
        else:
            print(f"  [WARN] No pude parsear: '{part}' — usa formato 'Equipo1 vs Equipo2'")
    return matches


# ═══════════════════════════════════════════════════════════════════════════
#  2. BUSQUEDA DE EQUIPOS EN football-data.org
# ═══════════════════════════════════════════════════════════════════════════

# Competiciones disponibles en tier gratuito
FREE_COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "CL", "DED", "PPL", "ELC", "BSA"]

# Cache de equipos (se carga una vez)
_teams_cache = None


def load_teams_cache():
    """Carga todos los equipos de las competiciones gratuitas."""
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache

    cache_path = os.path.join(BASE_DIR, ".teams_cache.json")

    # Usar cache en disco si existe y tiene menos de 7 dias
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < 7 * 86400:
            with open(cache_path, encoding="utf-8") as f:
                _teams_cache = json.load(f)
                return _teams_cache

    print("    Cargando base de equipos (primera vez, toma ~1 min)...")
    teams = {}
    for comp_code in FREE_COMPETITIONS:
        print(f"      Cargando {comp_code}...", end=" ", flush=True)
        data = football_data_get(f"competitions/{comp_code}/teams")
        comp_teams = data.get("teams", [])
        print(f"{len(comp_teams)} equipos")
        for t in comp_teams:
            tid = t["id"]
            if tid not in teams:
                teams[tid] = {
                    "id": tid,
                    "name": t.get("name", ""),
                    "short": t.get("shortName", ""),
                    "tla": t.get("tla", ""),
                    "competitions": [comp_code],
                }
            else:
                if comp_code not in teams[tid]["competitions"]:
                    teams[tid]["competitions"].append(comp_code)

    _teams_cache = teams

    # Guardar cache en disco
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)
    print(f"    {len(teams)} equipos cargados y cacheados")
    return teams


def find_team(name):
    """Busca un equipo por nombre en la base de datos."""
    teams = load_teams_cache()
    name_lower = name.lower().strip()

    # 1. Busqueda exacta en name, short, tla
    for tid, t in teams.items():
        if (t["name"].lower() == name_lower or
            t["short"].lower() == name_lower or
            t["tla"].lower() == name_lower):
            return t

    # 2. Busqueda: el input ES el inicio del nombre oficial
    #    "Barcelona" -> "FC Barcelona" NO "RCD Espanyol de Barcelona"
    #    "Manchester City" -> "Manchester City FC" NO "Manchester United FC"
    candidates = []
    for tid, t in teams.items():
        for field in [t["name"], t["short"]]:
            fl = field.lower()
            # El nombre oficial empieza con el input
            if fl.startswith(name_lower):
                candidates.append((t, 100 - len(fl)))  # Preferir mas corto
                break
            # El input empieza con el nombre corto
            if name_lower.startswith(fl) and len(fl) >= 3:
                candidates.append((t, 90 - len(fl)))
                break
            # "FC Barcelona" -> quitar prefijo "FC " y comparar
            clean = re.sub(r'^(FC|CF|AC|AS|US|SS|RC|RCD|SC|SL|BSC|TSG|VfB|VfL|1\.)\s+', '', fl)
            if clean.startswith(name_lower) or name_lower.startswith(clean):
                candidates.append((t, 95 - len(fl)))
                break

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    # 3. Busqueda por todas las palabras del input presentes en el nombre
    words = name_lower.split()
    best_match = None
    best_score = 0
    for tid, t in teams.items():
        full = f"{t['name']} {t['short']}".lower()
        # Todas las palabras deben estar presentes
        matches = sum(1 for w in words if w in full)
        if matches == len(words) and len(words) > 0:
            # Preferir nombre mas corto (mas especifico)
            score = matches * 100 - len(full)
            if score > best_score:
                best_score = score
                best_match = t

    if best_match:
        return best_match

    # 4. Busqueda parcial flexible (al menos 50% de palabras)
    for tid, t in teams.items():
        full = f"{t['name']} {t['short']}".lower()
        matches = sum(1 for w in words if w in full)
        score = matches / len(words) if words else 0
        if score >= 0.5:
            total_score = score * 100 - len(full)
            if total_score > best_score:
                best_score = total_score
                best_match = t

    return best_match


# ═══════════════════════════════════════════════════════════════════════════
#  3. DATOS DE PARTIDOS RECIENTES (football-data.org)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_team_matches(team_id, limit=15):
    """Obtiene ultimos partidos finalizados de un equipo."""
    data = football_data_get(f"teams/{team_id}/matches", {
        "status": "FINISHED",
        "limit": limit,
    })
    matches = []
    for m in data.get("matches", []):
        score = m.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")
        if hg is None or ag is None:
            continue
        matches.append({
            "date": m["utcDate"][:10],
            "home_team": m["homeTeam"]["name"],
            "away_team": m["awayTeam"]["name"],
            "home_id": m["homeTeam"]["id"],
            "away_id": m["awayTeam"]["id"],
            "home_goals": hg,
            "away_goals": ag,
            "competition": m.get("competition", {}).get("name", "?"),
        })
    return matches


# ═══════════════════════════════════════════════════════════════════════════
#  4. NOTICIAS DE LESIONES (Google News RSS — gratis)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_injury_news(team_name):
    """
    Busca noticias de lesiones via Google News RSS.
    Retorna titulares relevantes de las ultimas 48h.
    """
    queries = [
        f"{team_name} injury news",
        f"{team_name} lineup confirmed",
    ]

    all_news = []
    seen_titles = set()

    for query in queries:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64)")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml = resp.read().decode("utf-8", errors="replace")

            # Extraer items con titulo y fecha
            items = re.findall(
                r"<item>.*?<title>([^<]+)</title>.*?<pubDate>([^<]+)</pubDate>.*?</item>",
                xml, re.DOTALL
            )

            cutoff = datetime.now() - timedelta(hours=72)

            for title, pub_date in items:
                # Parsear fecha
                try:
                    # Formato: "Mon, 31 Mar 2026 10:00:00 GMT"
                    dt = datetime.strptime(pub_date.strip()[:25], "%a, %d %b %Y %H:%M:%S")
                except ValueError:
                    dt = datetime.now()  # Si falla, asumir reciente

                if dt < cutoff:
                    continue

                title_clean = title.strip()
                if title_clean in seen_titles:
                    continue
                seen_titles.add(title_clean)

                # Filtrar por relevancia
                title_lower = title_clean.lower()
                keywords = ["injur", "out", "miss", "doubt", "ruled",
                            "fitness", "lineup", "team news", "squad",
                            "return", "suspend", "ban", "absent",
                            "lesion", "baja", "convocatoria", "alineacion"]
                if any(kw in title_lower for kw in keywords):
                    # Clasificar tipo
                    if any(w in title_lower for w in ["out", "miss", "ruled", "absent", "suspend", "ban"]):
                        news_type = "BAJA"
                    elif any(w in title_lower for w in ["doubt", "fitness", "injur"]):
                        news_type = "DUDA"
                    elif any(w in title_lower for w in ["lineup", "team news", "squad", "return"]):
                        news_type = "ALINEACION"
                    else:
                        news_type = "INFO"

                    all_news.append({
                        "title": title_clean,
                        "type": news_type,
                        "date": dt.strftime("%Y-%m-%d %H:%M"),
                        "hours_ago": int((datetime.now() - dt).total_seconds() / 3600),
                    })

        except Exception:
            pass

    # Ordenar por mas reciente
    all_news.sort(key=lambda x: x["hours_ago"])
    return all_news[:8]  # Max 8 noticias


# ═══════════════════════════════════════════════════════════════════════════
#  5. CALCULO DE STATS
# ═══════════════════════════════════════════════════════════════════════════

def compute_stats(matches, team_id):
    """Calcula estadisticas del equipo desde sus partidos recientes."""
    gf_home, ga_home = [], []
    gf_away, ga_away = [], []
    form = []  # W, D, L
    elo = ELO_INITIAL

    for m in matches:
        is_home = m["home_id"] == team_id
        if is_home:
            gf_home.append(m["home_goals"])
            ga_home.append(m["away_goals"])
            if m["home_goals"] > m["away_goals"]:
                form.append("W")
            elif m["home_goals"] == m["away_goals"]:
                form.append("D")
            else:
                form.append("L")
        else:
            gf_away.append(m["away_goals"])
            ga_away.append(m["home_goals"])
            if m["away_goals"] > m["home_goals"]:
                form.append("W")
            elif m["home_goals"] == m["away_goals"]:
                form.append("D")
            else:
                form.append("L")

    all_gf = gf_home + gf_away
    all_ga = ga_home + ga_away
    n = len(all_gf)

    if n == 0:
        return {
            "avg_gf": 1.3, "avg_ga": 1.1,
            "home_avg_gf": 1.5, "home_avg_ga": 1.0,
            "away_avg_gf": 1.1, "away_avg_ga": 1.3,
            "matches_played": 0, "form_pct": 50, "form_str": "?",
            "gd_per_match": 0.0,
        }

    # ELO basado en forma
    points = sum(3 if r == "W" else 1 if r == "D" else 0 for r in form)
    form_pct = points / (n * 3) * 100

    avg_gf = sum(all_gf) / n
    avg_ga = sum(all_ga) / n
    gd = avg_gf - avg_ga

    return {
        "avg_gf": round(avg_gf, 3),
        "avg_ga": round(avg_ga, 3),
        "home_avg_gf": round(sum(gf_home) / len(gf_home), 3) if gf_home else round(avg_gf * 1.1, 3),
        "home_avg_ga": round(sum(ga_home) / len(ga_home), 3) if ga_home else round(avg_ga * 0.9, 3),
        "away_avg_gf": round(sum(gf_away) / len(gf_away), 3) if gf_away else round(avg_gf * 0.9, 3),
        "away_avg_ga": round(sum(ga_away) / len(ga_away), 3) if ga_away else round(avg_ga * 1.1, 3),
        "matches_played": n,
        "form_pct": round(form_pct, 1),
        "form_str": "".join(form[-5:]),
        "gd_per_match": round(gd, 2),
    }


def estimate_elo(stats):
    """Estima rating ELO desde rendimiento reciente."""
    if stats["matches_played"] == 0:
        return ELO_INITIAL
    return int(ELO_INITIAL + stats["gd_per_match"] * 150)


# ═══════════════════════════════════════════════════════════════════════════
#  6. MOTOR DE PREDICCION (Ensemble: Poisson + Dixon-Coles + ELO)
# ═══════════════════════════════════════════════════════════════════════════

def predict_match(home_name, away_name, home_stats, away_stats,
                  home_elo, away_elo, home_news, away_news):
    """Ejecuta modelo ensemble completo."""

    # Media global
    avg_gf = (home_stats["avg_gf"] + away_stats["avg_gf"] +
              home_stats["avg_ga"] + away_stats["avg_ga"]) / 4
    if avg_gf < 0.5:
        avg_gf = 1.3

    home_adv = 1.10

    # Ratings de ataque/defensa normalizados
    h_att = home_stats["home_avg_gf"] / avg_gf if avg_gf > 0 else 1.0
    h_def = home_stats["home_avg_ga"] / avg_gf if avg_gf > 0 else 1.0
    a_att = away_stats["away_avg_gf"] / avg_gf if avg_gf > 0 else 1.0
    a_def = away_stats["away_avg_ga"] / avg_gf if avg_gf > 0 else 1.0

    # Lambdas base (Poisson)
    lh = h_att * a_def * avg_gf * home_adv
    la = a_att * h_def * avg_gf

    # Ajuste por forma reciente (+-12.5% max)
    home_form_mod = 1.0 + (home_stats["form_pct"] - 50) / 400
    away_form_mod = 1.0 + (away_stats["form_pct"] - 50) / 400
    lh *= home_form_mod
    la *= away_form_mod

    # Ajuste por bajas (estimado desde noticias)
    home_bajas = sum(1 for n in home_news if n["type"] == "BAJA")
    away_bajas = sum(1 for n in away_news if n["type"] == "BAJA")
    home_dudas = sum(1 for n in home_news if n["type"] == "DUDA")
    away_dudas = sum(1 for n in away_news if n["type"] == "DUDA")

    home_injury_impact = min(home_bajas * 0.04 + home_dudas * 0.02, 0.20)
    away_injury_impact = min(away_bajas * 0.04 + away_dudas * 0.02, 0.20)
    lh *= (1.0 - home_injury_impact)
    la *= (1.0 - away_injury_impact)

    lh = max(0.3, min(lh, 5.0))
    la = max(0.2, min(la, 4.5))

    # ─── Sub-modelo 1: Poisson ───────────────────────────
    poi_m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            poi_m[(h, a)] = poisson_pmf(h, lh) * poisson_pmf(a, la)
    pt = sum(poi_m.values())
    poi_m = {k: v / pt for k, v in poi_m.items()}

    # ─── Sub-modelo 2: Dixon-Coles ──────────────────────
    dc_m = build_dc_matrix(lh, la, DC_RHO)

    # ─── Sub-modelo 3: ELO ──────────────────────────────
    elh, ela = elo_expected_goals(home_elo, away_elo, avg_gf)
    elh *= (1.0 - home_injury_impact) * home_form_mod
    ela *= (1.0 - away_injury_impact) * away_form_mod
    elh = max(0.3, min(elh, 5.0))
    ela = max(0.2, min(ela, 4.5))

    elo_m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            elo_m[(h, a)] = poisson_pmf(h, elh) * poisson_pmf(a, ela)
    et = sum(elo_m.values())
    elo_m = {k: v / et for k, v in elo_m.items()}

    # ─── Ensemble (40/30/30) ─────────────────────────────
    ens_m = {}
    for key in poi_m:
        ens_m[key] = W_POISSON * poi_m[key] + W_DIXON_COLES * dc_m[key] + W_ELO * elo_m[key]
    ens_t = sum(ens_m.values())
    ens_m = {k: v / ens_t for k, v in ens_m.items()}

    ens = extract_markets(ens_m)
    poi = extract_markets(poi_m)
    dc = extract_markets(dc_m)
    elo_p = extract_markets(elo_m)

    sorted_scores = sorted(ens_m.items(), key=lambda x: x[1], reverse=True)
    top_scores = [(f"{h}-{a}", round(p * 100, 1)) for (h, a), p in sorted_scores[:5]]

    return {
        "home_team": home_name, "away_team": away_name,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "lambda_home": round(lh, 3), "lambda_away": round(la, 3),
        "lambda_home_elo": round(elh, 3), "lambda_away_elo": round(ela, 3),
        "elo_home": home_elo, "elo_away": away_elo,
        "p_home_win": round(ens["1"] * 100, 1),
        "p_draw": round(ens["X"] * 100, 1),
        "p_away_win": round(ens["2"] * 100, 1),
        "p_btts_yes": round(ens["btts"] * 100, 1),
        "p_btts_no": round((1 - ens["btts"]) * 100, 1),
        "p_over_25": round(ens["o25"] * 100, 1),
        "p_under_25": round((1 - ens["o25"]) * 100, 1),
        "p_over_15": round(ens["o15"] * 100, 1),
        "top_scores": top_scores,
        "sub_poisson": {k: round(v * 100, 1) for k, v in poi.items()},
        "sub_dixon_coles": {k: round(v * 100, 1) for k, v in dc.items()},
        "sub_elo": {k: round(v * 100, 1) for k, v in elo_p.items()},
        "home_news": home_news, "away_news": away_news,
        "home_injury_impact": round(home_injury_impact * 100, 1),
        "away_injury_impact": round(away_injury_impact * 100, 1),
        "home_form": home_stats["form_str"],
        "away_form": away_stats["form_str"],
        "home_form_pct": home_stats["form_pct"],
        "away_form_pct": away_stats["form_pct"],
        "home_matches": home_stats["matches_played"],
        "away_matches": away_stats["matches_played"],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  7. SELECCION DE TOP PICKS
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_bet(pred, market, prob_key):
    """Evalua si una apuesta cumple los criterios de seleccion."""
    prob = pred.get(prob_key, 0)
    if prob < MIN_PROBABILITY:
        return None

    # Consistencia en sub-modelos
    sub_map = {
        "p_home_win": "1", "p_draw": "X", "p_away_win": "2",
        "p_btts_yes": "btts", "p_over_25": "o25", "p_over_15": "o15",
    }
    sk = sub_map.get(prob_key)

    agree = 0
    threshold = prob * 0.80

    if sk:
        poi_val = pred["sub_poisson"].get(sk, 0)
        dc_val = pred["sub_dixon_coles"].get(sk, 0)
        elo_val = pred["sub_elo"].get(sk, 0)
    elif prob_key == "p_under_25":
        poi_val = 100 - pred["sub_poisson"].get("o25", 50)
        dc_val = 100 - pred["sub_dixon_coles"].get("o25", 50)
        elo_val = 100 - pred["sub_elo"].get("o25", 50)
    elif prob_key == "p_btts_no":
        poi_val = 100 - pred["sub_poisson"].get("btts", 50)
        dc_val = 100 - pred["sub_dixon_coles"].get("btts", 50)
        elo_val = 100 - pred["sub_elo"].get("btts", 50)
    else:
        poi_val = dc_val = elo_val = prob

    if poi_val >= threshold: agree += 1
    if dc_val >= threshold: agree += 1
    if elo_val >= threshold: agree += 1

    if agree < MIN_SUBMODELS_AGREE:
        return None

    fair_odds = prob_to_odds(prob)
    return {
        "match": f"{pred['home_team']} vs {pred['away_team']}",
        "market": market,
        "probability": prob,
        "fair_odds": fair_odds,
        "confidence": "ALTA" if prob >= 75 else "MEDIA",
        "sub_agreement": agree,
        "sub_detail": f"Poi={poi_val:.0f}% DC={dc_val:.0f}% ELO={elo_val:.0f}%",
    }


def select_top_picks(predictions):
    all_picks = []
    for pred in predictions:
        bets = [
            ("1 (Local)", "p_home_win"),
            ("X (Empate)", "p_draw"),
            ("2 (Visitante)", "p_away_win"),
            ("BTTS Si", "p_btts_yes"),
            ("BTTS No", "p_btts_no"),
            ("Over 2.5", "p_over_25"),
            ("Under 2.5", "p_under_25"),
            ("Over 1.5", "p_over_15"),
        ]
        for market, prob_key in bets:
            pick = evaluate_bet(pred, market, prob_key)
            if pick:
                all_picks.append(pick)

    all_picks.sort(key=lambda x: x["probability"], reverse=True)
    return all_picks[:3]


# ═══════════════════════════════════════════════════════════════════════════
#  8. HISTORIAL (resultados.json)
# ═══════════════════════════════════════════════════════════════════════════

def save_history(predictions, picks):
    path = os.path.join(BASE_DIR, "resultados.json")
    history = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "predictions": [{k: v for k, v in p.items() if k not in ("home_news", "away_news")}
                        for p in predictions],
        "top_picks": picks,
        "results": None,
        "accuracy": None,
    }
    history.append(entry)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, default=str)
    return path


def update_result(match_str, hg, ag):
    path = os.path.join(BASE_DIR, "resultados.json")
    if not os.path.exists(path):
        print("  No hay historial guardado.")
        return

    with open(path, encoding="utf-8") as f:
        history = json.load(f)

    updated = False
    for entry in reversed(history):
        if entry.get("results") is not None:
            continue
        for pred in entry.get("predictions", []):
            label = f"{pred['home_team']} vs {pred['away_team']}"
            if match_str.lower() in label.lower():
                if entry["results"] is None:
                    entry["results"] = {}
                entry["results"][label] = {"home_goals": hg, "away_goals": ag}

                correct = 0
                total = 3
                # 1X2
                pred_1x2 = "1" if pred["p_home_win"] > max(pred["p_draw"], pred["p_away_win"]) else (
                    "X" if pred["p_draw"] > pred["p_away_win"] else "2")
                real_1x2 = "1" if hg > ag else ("X" if hg == ag else "2")
                if pred_1x2 == real_1x2: correct += 1
                # O/U 2.5
                if (pred["p_over_25"] > 50) == (hg + ag > 2.5): correct += 1
                # BTTS
                if (pred["p_btts_yes"] > 50) == (hg > 0 and ag > 0): correct += 1

                entry["accuracy"] = round(correct / total * 100, 1)
                updated = True
                print(f"  Resultado: {label} = {hg}-{ag}")
                print(f"  Prediccion 1X2: {pred_1x2} | Real: {real_1x2} | {'OK' if pred_1x2 == real_1x2 else 'FALLO'}")
                print(f"  Acierto: {correct}/{total} ({entry['accuracy']}%)")
                break

    if updated:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2, default=str)
    else:
        print(f"  No encontre '{match_str}' pendiente de resultado.")


def show_accuracy():
    path = os.path.join(BASE_DIR, "resultados.json")
    if not os.path.exists(path):
        print("  No hay historial guardado.")
        return
    with open(path, encoding="utf-8") as f:
        history = json.load(f)

    total = len(history)
    verified = [e for e in history if e.get("accuracy") is not None]
    if not verified:
        print(f"  {total} sesiones, ninguna con resultados verificados.")
        return

    accs = [e["accuracy"] for e in verified]
    print(f"\n  {'=' * 50}")
    print(f"  HISTORIAL DE ACIERTO")
    print(f"  {'=' * 50}")
    print(f"  Sesiones totales:    {total}")
    print(f"  Con resultados:      {len(verified)}")
    print(f"  Acierto promedio:    {sum(accs)/len(accs):.1f}%")
    print(f"  Mejor sesion:        {max(accs):.1f}%")
    print(f"  Peor sesion:         {min(accs):.1f}%")
    print(f"  {'=' * 50}")


# ═══════════════════════════════════════════════════════════════════════════
#  9. PRESENTACION
# ═══════════════════════════════════════════════════════════════════════════

def print_prediction(pred):
    home, away = pred["home_team"], pred["away_team"]

    print(f"\n  {'=' * 78}")
    print(f"  {home}  vs  {away}")
    print(f"  {'=' * 78}")

    # Noticias
    h_news = pred.get("home_news", [])
    a_news = pred.get("away_news", [])

    if h_news or a_news:
        print(f"\n  NOTICIAS ULTIMAS 72H:")
        for team_name, news in [(home, h_news), (away, a_news)]:
            if news:
                print(f"  {team_name}:")
                for n in news[:4]:
                    icon = {"BAJA": "X", "DUDA": "?", "ALINEACION": "~", "INFO": "i"}[n["type"]]
                    print(f"    [{icon}] [{n['type']}] {n['title'][:80]}")
                    print(f"        hace {n['hours_ago']}h")
        if pred["home_injury_impact"] > 0 or pred["away_injury_impact"] > 0:
            print(f"  Impacto bajas: {home} -{pred['home_injury_impact']:.1f}%"
                  f"  |  {away} -{pred['away_injury_impact']:.1f}%")
    else:
        print(f"\n  NOTICIAS: Sin noticias de lesiones encontradas")

    # Forma y ELO
    print(f"\n  Forma: {home} [{pred['home_form']}] {pred['home_form_pct']:.0f}% ({pred['home_matches']}p)"
          f"  |  {away} [{pred['away_form']}] {pred['away_form_pct']:.0f}% ({pred['away_matches']}p)")
    print(f"  ELO: {pred['elo_home']} vs {pred['elo_away']} ({pred['elo_home']-pred['elo_away']:+d})")
    print(f"  Lambda: {pred['lambda_home']:.2f} - {pred['lambda_away']:.2f}"
          f"  |  Lambda ELO: {pred['lambda_home_elo']:.2f} - {pred['lambda_away_elo']:.2f}")

    # Sub-modelos
    poi = pred["sub_poisson"]
    dc = pred["sub_dixon_coles"]
    elo = pred["sub_elo"]

    print(f"\n  {'Sub-modelo':<18s} {'1':>6s} {'X':>6s} {'2':>6s}  {'BTTS':>5s}  {'O2.5':>5s}")
    print(f"  {'-' * 55}")
    print(f"  {'Poisson (40%)':<18s} {poi['1']:5.1f}% {poi['X']:5.1f}% {poi['2']:5.1f}%  {poi['btts']:4.1f}%  {poi['o25']:4.1f}%")
    print(f"  {'Dixon-Coles (30%)':<18s} {dc['1']:5.1f}% {dc['X']:5.1f}% {dc['2']:5.1f}%  {dc['btts']:4.1f}%  {dc['o25']:4.1f}%")
    print(f"  {'ELO (30%)':<18s} {elo['1']:5.1f}% {elo['X']:5.1f}% {elo['2']:5.1f}%  {elo['btts']:4.1f}%  {elo['o25']:4.1f}%")
    print(f"  {'=' * 55}")
    print(f"  {'ENSEMBLE':<18s} {pred['p_home_win']:5.1f}% {pred['p_draw']:5.1f}% {pred['p_away_win']:5.1f}%"
          f"  {pred['p_btts_yes']:4.1f}%  {pred['p_over_25']:4.1f}%")

    # Cuotas justas
    print(f"\n  Cuotas justas:  1={prob_to_odds(pred['p_home_win']):.2f}"
          f"  X={prob_to_odds(pred['p_draw']):.2f}"
          f"  2={prob_to_odds(pred['p_away_win']):.2f}")

    # Mercados
    print(f"  O1.5: {pred['p_over_15']:.1f}%  |  O2.5: {pred['p_over_25']:.1f}%  U2.5: {pred['p_under_25']:.1f}%")
    print(f"  BTTS Si: {pred['p_btts_yes']:.1f}%  |  BTTS No: {pred['p_btts_no']:.1f}%")

    # Top scores
    print(f"  Marcadores: ", end="")
    print("  ".join(f"{sc}({pr:.1f}%)" for sc, pr in pred["top_scores"][:5]))

    # Warnings
    warnings = []
    if pred["home_matches"] < 5 or pred["away_matches"] < 5:
        warnings.append("Pocos datos historicos — prediccion menos fiable")
    if pred["home_injury_impact"] > 10:
        warnings.append(f"{home}: varias bajas ({pred['home_injury_impact']:.0f}% impacto)")
    if pred["away_injury_impact"] > 10:
        warnings.append(f"{away}: varias bajas ({pred['away_injury_impact']:.0f}% impacto)")
    max_p = max(pred["p_home_win"], pred["p_draw"], pred["p_away_win"])
    if max_p < 40:
        warnings.append("Partido muy parejo — alta incertidumbre en 1X2")
    if warnings:
        print(f"\n  ADVERTENCIAS:")
        for w in warnings:
            print(f"    [!] {w}")


def print_top_picks(picks):
    print(f"\n  {'=' * 78}")
    print(f"  TOP PICKS DEL DIA")
    print(f"  Criterios: Prob >{MIN_PROBABILITY:.0f}% | Consistencia >={MIN_SUBMODELS_AGREE}/3 sub-modelos")
    print(f"  {'=' * 78}")

    if not picks:
        print(f"\n  Sin picks que cumplan TODOS los criterios.")
        print(f"  Los partidos son muy parejos o no hay valor claro.")
        print(f"  Revisa las predicciones individuales para analisis manual.")
        return

    for i, pick in enumerate(picks, 1):
        print(f"\n  PICK #{i}: {pick['market']}")
        print(f"  Partido:      {pick['match']}")
        print(f"  Probabilidad: {pick['probability']:.1f}%")
        print(f"  Cuota justa:  {pick['fair_odds']:.2f}")
        print(f"  Confianza:    {pick['confidence']} ({pick['sub_agreement']}/3)")
        print(f"  Sub-modelos:  {pick['sub_detail']}")
        print(f"  {'─' * 40}")


# ═══════════════════════════════════════════════════════════════════════════
#  10. FLUJO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def run_predictions(match_text):
    print(f"\n{'=' * 78}")
    print(f"  PREDICTOR AUTONOMO DE APUESTAS v2.0")
    print(f"  Ensemble: Poisson(40%) + Dixon-Coles(30%) + ELO(30%)")
    print(f"  Datos: football-data.org | Noticias: Google News RSS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 78}")

    # 1. Parsear
    matches = parse_matches(match_text)
    if not matches:
        print("\n  [ERROR] No se encontraron partidos. Usa: 'Equipo1 vs Equipo2'")
        return

    print(f"\n  {len(matches)} partido(s):")
    for h, a in matches:
        print(f"    - {h} vs {a}")

    # 2. Procesar cada partido
    all_predictions = []

    for home_name, away_name in matches:
        print(f"\n  {'─' * 60}")
        print(f"  Procesando: {home_name} vs {away_name}")
        print(f"  {'─' * 60}")

        # Buscar equipos
        print(f"    Buscando equipos...")
        home_info = find_team(home_name)
        away_info = find_team(away_name)

        if not home_info:
            print(f"    [!] '{home_name}' no encontrado — usando valores por defecto")
            home_info = {"id": None, "name": home_name, "short": home_name}
        else:
            print(f"    {home_name} -> {home_info['name']} (ID: {home_info['id']})")

        if not away_info:
            print(f"    [!] '{away_name}' no encontrado — usando valores por defecto")
            away_info = {"id": None, "name": away_name, "short": away_name}
        else:
            print(f"    {away_name} -> {away_info['name']} (ID: {away_info['id']})")

        # Obtener partidos recientes
        home_matches_raw, away_matches_raw = [], []
        if home_info["id"]:
            print(f"    Cargando partidos de {home_info['short']}...")
            home_matches_raw = fetch_team_matches(home_info["id"], limit=15)
            print(f"    -> {len(home_matches_raw)} partidos")

        if away_info["id"]:
            print(f"    Cargando partidos de {away_info['short']}...")
            away_matches_raw = fetch_team_matches(away_info["id"], limit=15)
            print(f"    -> {len(away_matches_raw)} partidos")

        # Estadisticas
        home_stats = compute_stats(home_matches_raw, home_info["id"]) if home_info["id"] else compute_stats([], None)
        away_stats = compute_stats(away_matches_raw, away_info["id"]) if away_info["id"] else compute_stats([], None)

        home_elo = estimate_elo(home_stats)
        away_elo = estimate_elo(away_stats)

        # Noticias de lesiones (paralelo conceptual, secuencial por simpleza)
        print(f"    Buscando noticias de lesiones...")
        home_news = fetch_injury_news(home_info["name"])
        away_news = fetch_injury_news(away_info["name"])
        h_count = len(home_news)
        a_count = len(away_news)
        print(f"    -> {home_info['short']}: {h_count} noticias | {away_info['short']}: {a_count} noticias")

        # Predecir
        print(f"    Ejecutando modelo ensemble...")
        pred = predict_match(
            home_name, away_name,
            home_stats, away_stats,
            home_elo, away_elo,
            home_news, away_news,
        )
        all_predictions.append(pred)

    # 3. Presentar
    for pred in all_predictions:
        print_prediction(pred)

    # 4. Top picks
    picks = select_top_picks(all_predictions)
    print_top_picks(picks)

    # 5. Guardar
    path = save_history(all_predictions, picks)
    print(f"\n  Historial: {path}")
    print(f"\n  Para registrar resultado: python3 app.py --resultado 'Equipo' goles_L goles_V")
    print(f"  DISCLAIMER: Modelo estadistico con fines educativos. No es consejo de apuestas.\n")

    return all_predictions, picks


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--resultado":
            if len(sys.argv) >= 5:
                update_result(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
            else:
                print("  Uso: python3 app.py --resultado 'Equipo' goles_L goles_V")
            return

        if sys.argv[1] == "--accuracy":
            show_accuracy()
            return

        if sys.argv[1] == "--help":
            print("""
  PREDICTOR AUTONOMO DE APUESTAS v2.0
  ════════════════════════════════════

  Uso:
    python3 app.py "Real Madrid vs Barcelona, Man City vs Liverpool"
    python3 app.py                          # Modo interactivo
    python3 app.py --resultado "Madrid vs Barcelona" 2 1
    python3 app.py --accuracy               # Estadisticas de acierto

  Fuentes de datos:
    - football-data.org: PL, La Liga, Serie A, Bundesliga, Ligue 1,
      Champions League, Eredivisie, Liga Portugal, Championship, Serie A Brasil
    - Google News RSS: noticias de lesiones/bajas (gratis, ultimas 72h)

  Modelo: Poisson(40%) + Dixon-Coles(30%) + ELO(30%)

  Criterios TOP PICKS:
    - Probabilidad > 65%
    - Al menos 2 de 3 sub-modelos coinciden
            """)
            return

        match_text = " ".join(sys.argv[1:])
        run_predictions(match_text)

    else:
        print(f"\n{'=' * 60}")
        print(f"  PREDICTOR AUTONOMO DE APUESTAS v2.0")
        print(f"  Ingresa partidos: Equipo1 vs Equipo2, Equipo3 vs Equipo4")
        print(f"  'salir' para terminar")
        print(f"{'=' * 60}")

        while True:
            try:
                text = input("\n  Partidos > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Hasta luego!")
                break
            if text.lower() in ("salir", "exit", "quit", "q"):
                break
            if not text:
                continue
            run_predictions(text)


if __name__ == "__main__":
    main()
