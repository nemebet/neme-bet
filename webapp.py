#!/usr/bin/env python3
"""
WEBAPP.PY — Predictor de Apuestas v3.0 — App Web Movil
═══════════════════════════════════════════════════════
Flask app con OCR de imagenes, modelo ensemble v5 completo,
scraping de noticias y historial de acierto.

Ejecutar: python3 webapp.py
Acceder:  http://<IP>:5000
"""

import os
import sys

# Cargar variables de entorno ANTES de todo
def _bootstrap_env():
    for path in [os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        k, v = k.strip(), v.strip()
                        if k not in os.environ:
                            os.environ[k] = v
_bootstrap_env()

import json
import os
import re
import secrets
import sys
import time
import base64
import urllib.request
import urllib.error
import urllib.parse
import traceback
from datetime import datetime, timedelta
from math import exp, lgamma, log
from collections import defaultdict
from werkzeug.utils import secure_filename

from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash, session)

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "51c21f72a41d003683cf0b0d1848f332bda785cbbbe0fb73dd0a552594461a0e")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Initialize security layer
try:
    from security import init_security
    init_security(app)
except Exception as e:
    print(f"[SECURITY] Init failed: {e}")


def load_env():
    env = {}
    # 1. Read .env file if exists (local dev)
    for path in [os.path.join(BASE_DIR, ".env"), os.path.expanduser("~/.env")]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
    # 2. System env vars override (Railway/Render inject these)
    for key in ["FOOTBALL_DATA_API_KEY", "API_FOOTBALL_KEY", "ANTHROPIC_API_KEY",
                "STRIPE_SECRET_KEY", "RESEND_API_KEY", "ADMIN_KEY"]:
        val = os.environ.get(key)
        if val:
            env[key] = val
    # 3. Export to os.environ so all modules (featured_matches, etc.) can see them
    for k, v in env.items():
        if k not in os.environ:
            os.environ[k] = v
    return env

ENV = load_env()
FOOTBALL_DATA_KEY = ENV.get("FOOTBALL_DATA_API_KEY", "")
API_FOOTBALL_KEY = ENV.get("API_FOOTBALL_KEY", "")
ANTHROPIC_API_KEY = ENV.get("ANTHROPIC_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# Modelo (defaults, pueden ser overridden por autolearn)
MAX_GOALS = 8
DC_RHO = -0.13
ELO_INITIAL = 1500
ELO_K = 40
ELO_HOME_ADVANTAGE = 100


def get_weights():
    """Carga pesos aprendidos si existen, o usa defaults."""
    from data_dir import data_path as _dp
    wp = _dp("learned_weights.json")
    if os.path.exists(wp):
        with open(wp, encoding="utf-8") as f:
            w = json.load(f)
            return {
                "w_poisson": w.get("w_poisson", 0.40),
                "w_dixon_coles": w.get("w_dixon_coles", 0.30),
                "w_elo": w.get("w_elo", 0.30),
                "home_advantage": w.get("home_advantage", 1.10),
                "injury_baja": w.get("injury_baja", 0.04),
                "injury_duda": w.get("injury_duda", 0.02),
                "injury_max": w.get("injury_max", 0.20),
                "form_impact": w.get("form_impact", 400),
                "draw_bias": w.get("draw_bias", 0.0),
                "over_bias": w.get("over_bias", 0.0),
                "btts_bias": w.get("btts_bias", 0.0),
            }
    return {
        "w_poisson": 0.40, "w_dixon_coles": 0.30, "w_elo": 0.30,
        "home_advantage": 1.10, "injury_baja": 0.04, "injury_duda": 0.02,
        "injury_max": 0.20, "form_impact": 400,
        "draw_bias": 0.0, "over_bias": 0.0, "btts_bias": 0.0,
    }

# Picks
HIGH_CONFIDENCE = 75.0
MED_CONFIDENCE = 65.0
MIN_SUBMODELS = 2

# Rate limit
_last_req = 0
REQ_INTERVAL = 6.5

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

# ═══════════════════════════════════════════════════════════════════════════
#  HTTP HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _rate_limit():
    global _last_req
    elapsed = time.time() - _last_req
    if elapsed < REQ_INTERVAL:
        time.sleep(REQ_INTERVAL - elapsed)
    _last_req = time.time()


def fd_get(endpoint, params=None):
    """football-data.org GET."""
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
            time.sleep(30)
            return fd_get(endpoint, params)
        return {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  MATH CORE (Poisson, Dixon-Coles, ELO)
# ═══════════════════════════════════════════════════════════════════════════

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(k * log(max(lam, 1e-10)) - lam - lgamma(k + 1))


def prob_to_odds(p):
    return round(100 / p, 2) if p > 0 else 99.99


def dc_tau(h, a, lh, la, rho=DC_RHO):
    if h == 0 and a == 0: return 1.0 - lh * la * rho
    if h == 0 and a == 1: return 1.0 + lh * rho
    if h == 1 and a == 0: return 1.0 + la * rho
    if h == 1 and a == 1: return 1.0 - rho
    return 1.0


def build_dc_matrix(lh, la, rho=DC_RHO):
    m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            tau = max(dc_tau(h, a, lh, la, rho), 0.001)
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
#  PARSER DE PARTIDOS
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
            h, a = teams[0].strip(), teams[1].strip()
            if h and a:
                matches.append((h, a))
    return matches


# ═══════════════════════════════════════════════════════════════════════════
#  OCR: IMAGEN -> TEXTO (EasyOCR / pytesseract / Claude Vision)
# ═══════════════════════════════════════════════════════════════════════════

def ocr_extract_matches(image_path):
    """Extrae nombres de equipos de una imagen.
    Intenta: 1) EasyOCR, 2) pytesseract, 3) Claude Vision API."""

    text = None
    method = None

    # 1. EasyOCR
    try:
        import easyocr
        reader = easyocr.Reader(["en", "es"], gpu=False, verbose=False)
        results = reader.readtext(image_path)
        text = "\n".join(r[1] for r in results)
        method = "EasyOCR"
    except Exception:
        pass

    # 2. pytesseract
    if not text:
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang="eng+spa")
            method = "pytesseract"
        except Exception:
            pass

    # 3. Claude Vision API (fallback)
    if not text and ANTHROPIC_API_KEY:
        text = claude_vision_extract(image_path)
        method = "Claude Vision"

    if not text:
        return [], "No se pudo leer la imagen. Instala easyocr o pytesseract, o configura ANTHROPIC_API_KEY."

    # Extraer partidos del texto OCR
    matches = parse_matches_from_ocr(text)
    if not matches:
        # Intento con Claude si hay key y no se uso aun
        if method != "Claude Vision" and ANTHROPIC_API_KEY:
            text2 = claude_vision_extract(image_path)
            if text2:
                matches = parse_matches_from_ocr(text2)
                method = "Claude Vision (fallback)"

    return matches, f"Metodo: {method} | Texto detectado: {len(text)} chars | {len(matches)} partidos"


def claude_vision_extract(image_path):
    """Usa Claude claude-sonnet-4-20250514 para leer partidos de una imagen."""
    if not ANTHROPIC_API_KEY:
        return None

    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    ext = image_path.rsplit(".", 1)[-1].lower()
    media_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                 "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
    media_type = media_map.get(ext, "image/jpeg")

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": media_type, "data": img_data}},
                {"type": "text", "text":
                 "Extract all football/soccer match pairs from this image. "
                 "Return ONLY the matches in this exact format, one per line:\n"
                 "Team1 vs Team2\n"
                 "Do not add any other text. Use the team names exactly as shown."}
            ]
        }]
    }).encode("utf-8")

    req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                 data=payload, method="POST")
    req.add_header("x-api-key", ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result.get("content", [{}])[0].get("text", "")
    except Exception as e:
        print(f"Claude Vision error: {e}")
        return None


def parse_matches_from_ocr(text):
    """Intenta extraer pares de equipos del texto OCR."""
    matches = []

    # Patron 1: "Team1 vs Team2" o "Team1 - Team2"
    direct = parse_matches(text)
    if direct:
        return direct

    # Patron 2: Lineas con dos equipos separados por marcador/hora
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        # "Real Madrid 2 - 1 Barcelona" o "Real Madrid 21:00 Barcelona"
        m = re.match(r'^(.+?)\s+\d+\s*[-:]\s*\d+\s+(.+)$', line)
        if m:
            h, a = m.group(1).strip(), m.group(2).strip()
            if len(h) > 2 and len(a) > 2:
                matches.append((h, a))
                continue
        # "Real Madrid - Barcelona" simple
        m = re.match(r'^(.+?)\s+[-–]\s+(.+)$', line)
        if m:
            h, a = m.group(1).strip(), m.group(2).strip()
            if len(h) > 2 and len(a) > 2 and not h.isdigit() and not a.isdigit():
                matches.append((h, a))

    return matches


# ═══════════════════════════════════════════════════════════════════════════
#  TEAM SEARCH (football-data.org)
# ═══════════════════════════════════════════════════════════════════════════

_teams_cache = None


def load_teams():
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache

    cache_path = os.path.join(BASE_DIR, ".teams_cache.json")
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < 7 * 86400:
            with open(cache_path, encoding="utf-8") as f:
                _teams_cache = json.load(f)
                return _teams_cache

    comps = ["PL", "PD", "SA", "BL1", "FL1", "CL", "DED", "PPL", "ELC", "BSA"]
    teams = {}
    for code in comps:
        data = fd_get(f"competitions/{code}/teams")
        for t in data.get("teams", []):
            tid = str(t["id"])
            if tid not in teams:
                teams[tid] = {
                    "id": t["id"], "name": t.get("name", ""),
                    "short": t.get("shortName", ""), "tla": t.get("tla", ""),
                }

    _teams_cache = teams
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)
    return teams


def find_team(name):
    teams = load_teams()
    nl = name.lower().strip()

    # Exact
    for t in teams.values():
        if nl in (t["name"].lower(), t["short"].lower(), t["tla"].lower()):
            return t

    # Prefix / cleaned
    cands = []
    for t in teams.values():
        for field in [t["name"], t["short"]]:
            fl = field.lower()
            if fl.startswith(nl) or nl.startswith(fl) and len(fl) >= 3:
                cands.append((t, 100 - len(fl)))
                break
            clean = re.sub(r'^(FC|CF|AC|AS|US|SS|RC|RCD|SC|SL|BSC|TSG|VfB|VfL|1\.)\s+', '', fl)
            if clean.startswith(nl) or nl.startswith(clean):
                cands.append((t, 95 - len(fl)))
                break
    if cands:
        cands.sort(key=lambda x: x[1], reverse=True)
        return cands[0][0]

    # Word match
    words = nl.split()
    best, best_s = None, 0
    for t in teams.values():
        full = f"{t['name']} {t['short']}".lower()
        hits = sum(1 for w in words if w in full)
        if hits == len(words) and words:
            s = hits * 100 - len(full)
            if s > best_s:
                best_s, best = s, t
    if best:
        return best

    for t in teams.values():
        full = f"{t['name']} {t['short']}".lower()
        hits = sum(1 for w in words if w in full)
        if words and hits / len(words) >= 0.5:
            s = hits * 100 - len(full)
            if s > best_s:
                best_s, best = s, t
    return best


# ═══════════════════════════════════════════════════════════════════════════
#  MATCH DATA + STATS (football-data.org)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_matches(team_id, limit=15):
    data = fd_get(f"teams/{team_id}/matches", {"status": "FINISHED", "limit": limit})
    out = []
    for m in data.get("matches", []):
        sc = m.get("score", {}).get("fullTime", {})
        hg, ag = sc.get("home"), sc.get("away")
        if hg is None or ag is None:
            continue
        out.append({
            "date": m["utcDate"][:10],
            "home_team": m["homeTeam"]["name"],
            "away_team": m["awayTeam"]["name"],
            "home_id": m["homeTeam"]["id"],
            "away_id": m["awayTeam"]["id"],
            "home_goals": hg, "away_goals": ag,
            "comp": m.get("competition", {}).get("name", ""),
        })
    return out


def compute_stats(matches, team_id):
    gfh, gah, gfa, gaa = [], [], [], []
    form = []
    for m in matches:
        is_h = m["home_id"] == team_id
        if is_h:
            gfh.append(m["home_goals"]); gah.append(m["away_goals"])
            form.append("W" if m["home_goals"] > m["away_goals"] else
                        "D" if m["home_goals"] == m["away_goals"] else "L")
        else:
            gfa.append(m["away_goals"]); gaa.append(m["home_goals"])
            form.append("W" if m["away_goals"] > m["home_goals"] else
                        "D" if m["home_goals"] == m["away_goals"] else "L")

    allgf = gfh + gfa
    allga = gah + gaa
    n = len(allgf)
    if n == 0:
        return {"avg_gf": 1.3, "avg_ga": 1.1, "home_avg_gf": 1.5,
                "home_avg_ga": 1.0, "away_avg_gf": 1.1, "away_avg_ga": 1.3,
                "n": 0, "form_pct": 50, "form_str": "?", "gd": 0}

    pts = sum(3 if r == "W" else 1 if r == "D" else 0 for r in form)
    avg_gf = sum(allgf) / n
    avg_ga = sum(allga) / n

    return {
        "avg_gf": round(avg_gf, 3), "avg_ga": round(avg_ga, 3),
        "home_avg_gf": round(sum(gfh) / len(gfh), 3) if gfh else round(avg_gf * 1.1, 3),
        "home_avg_ga": round(sum(gah) / len(gah), 3) if gah else round(avg_ga * 0.9, 3),
        "away_avg_gf": round(sum(gfa) / len(gfa), 3) if gfa else round(avg_gf * 0.9, 3),
        "away_avg_ga": round(sum(gaa) / len(gaa), 3) if gaa else round(avg_ga * 1.1, 3),
        "n": n,
        "form_pct": round(pts / (n * 3) * 100, 1),
        "form_str": "".join(form[-5:]),
        "gd": round(avg_gf - avg_ga, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NEWS SCRAPING (Google News RSS)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_news(team_name):
    queries = [f"{team_name} injury news", f"{team_name} lineup squad"]
    news = []
    seen = set()
    kw_baja = {"out", "miss", "ruled", "absent", "suspend", "ban", "baja"}
    kw_duda = {"doubt", "fitness", "injur", "duda", "lesion"}
    kw_alin = {"lineup", "team news", "squad", "return", "alineacion", "convocatoria"}

    for q in queries:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en&gl=US&ceid=US:en"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml = resp.read().decode("utf-8", errors="replace")
            items = re.findall(
                r"<item>.*?<title>([^<]+)</title>.*?<pubDate>([^<]+)</pubDate>.*?</item>",
                xml, re.DOTALL)
            cutoff = datetime.now() - timedelta(hours=72)
            for title, pubdate in items:
                try:
                    dt = datetime.strptime(pubdate.strip()[:25], "%a, %d %b %Y %H:%M:%S")
                except ValueError:
                    dt = datetime.now()
                if dt < cutoff:
                    continue
                tc = title.strip()
                if tc in seen:
                    continue
                seen.add(tc)
                tl = tc.lower()
                if any(k in tl for k in kw_baja):
                    ntype = "BAJA"
                elif any(k in tl for k in kw_duda):
                    ntype = "DUDA"
                elif any(k in tl for k in kw_alin):
                    ntype = "ALINEACION"
                else:
                    continue  # Skip irrelevant
                hours = max(0, int((datetime.now() - dt).total_seconds() / 3600))
                news.append({"title": tc, "type": ntype, "hours": hours})
        except Exception:
            pass

    news.sort(key=lambda x: x["hours"])
    return news[:8]


# ═══════════════════════════════════════════════════════════════════════════
#  PREDICTION ENGINE (Full v5 Ensemble)
# ═══════════════════════════════════════════════════════════════════════════

def predict(home_name, away_name, h_stats, a_stats, h_elo, a_elo, h_news, a_news):
    W = get_weights()  # Learned or default weights

    avg = (h_stats["avg_gf"] + a_stats["avg_gf"] +
           h_stats["avg_ga"] + a_stats["avg_ga"]) / 4
    if avg < 0.5:
        avg = 1.3

    h_att = h_stats["home_avg_gf"] / avg if avg > 0 else 1.0
    h_def = h_stats["home_avg_ga"] / avg if avg > 0 else 1.0
    a_att = a_stats["away_avg_gf"] / avg if avg > 0 else 1.0
    a_def = a_stats["away_avg_ga"] / avg if avg > 0 else 1.0

    lh = h_att * a_def * avg * W["home_advantage"]
    la = a_att * h_def * avg

    # Form (learned form_impact divisor)
    lh *= 1.0 + (h_stats["form_pct"] - 50) / W["form_impact"]
    la *= 1.0 + (a_stats["form_pct"] - 50) / W["form_impact"]

    # Injuries (learned impact values)
    h_bajas = sum(1 for n in h_news if n["type"] == "BAJA")
    a_bajas = sum(1 for n in a_news if n["type"] == "BAJA")
    h_dudas = sum(1 for n in h_news if n["type"] == "DUDA")
    a_dudas = sum(1 for n in a_news if n["type"] == "DUDA")
    h_imp = min(h_bajas * W["injury_baja"] + h_dudas * W["injury_duda"], W["injury_max"])
    a_imp = min(a_bajas * W["injury_baja"] + a_dudas * W["injury_duda"], W["injury_max"])
    lh *= (1.0 - h_imp)
    la *= (1.0 - a_imp)

    lh = max(0.3, min(lh, 5.0))
    la = max(0.2, min(la, 4.5))

    # Sub 1: Poisson
    poi_m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            poi_m[(h, a)] = poisson_pmf(h, lh) * poisson_pmf(a, la)
    pt = sum(poi_m.values())
    poi_m = {k: v / pt for k, v in poi_m.items()}

    # Sub 2: Dixon-Coles
    dc_m = build_dc_matrix(lh, la, DC_RHO)

    # Sub 3: ELO
    elh, ela = elo_expected_goals(h_elo, a_elo, avg)
    elh *= (1.0 - h_imp) * (1.0 + (h_stats["form_pct"] - 50) / W["form_impact"])
    ela *= (1.0 - a_imp) * (1.0 + (a_stats["form_pct"] - 50) / W["form_impact"])
    elh = max(0.3, min(elh, 5.0))
    ela = max(0.2, min(ela, 4.5))
    elo_m = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            elo_m[(h, a)] = poisson_pmf(h, elh) * poisson_pmf(a, ela)
    et = sum(elo_m.values())
    elo_m = {k: v / et for k, v in elo_m.items()}

    # Ensemble (learned weights)
    ens_m = {}
    for key in poi_m:
        ens_m[key] = W["w_poisson"] * poi_m[key] + W["w_dixon_coles"] * dc_m[key] + W["w_elo"] * elo_m[key]

    # Apply learned biases
    if W["draw_bias"] != 0:
        for key in ens_m:
            h, a = key
            if h == a:
                ens_m[key] *= (1 + W["draw_bias"] * 5)
            else:
                ens_m[key] *= (1 - abs(W["draw_bias"]))

    ens_t = sum(ens_m.values())
    ens_m = {k: v / ens_t for k, v in ens_m.items()}

    ens = extract_markets(ens_m)
    poi = extract_markets(poi_m)
    dc = extract_markets(dc_m)
    elo_p = extract_markets(elo_m)

    scores = sorted(ens_m.items(), key=lambda x: x[1], reverse=True)
    top = [(f"{h}-{a}", round(p * 100, 1)) for (h, a), p in scores[:5]]

    return {
        "home": home_name, "away": away_name,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "lh": round(lh, 2), "la": round(la, 2),
        "lh_elo": round(elh, 2), "la_elo": round(ela, 2),
        "elo_h": h_elo, "elo_a": a_elo,
        "p1": round(ens["1"] * 100, 1),
        "px": round(ens["X"] * 100, 1),
        "p2": round(ens["2"] * 100, 1),
        "btts_y": round(ens["btts"] * 100, 1),
        "btts_n": round((1 - ens["btts"]) * 100, 1),
        "o25": round(ens["o25"] * 100, 1),
        "u25": round((1 - ens["o25"]) * 100, 1),
        "o15": round(ens["o15"] * 100, 1),
        "u15": round((1 - ens["o15"]) * 100, 1),
        "scores": top,
        "poi": {k: round(v * 100, 1) for k, v in poi.items()},
        "dc": {k: round(v * 100, 1) for k, v in dc.items()},
        "elo": {k: round(v * 100, 1) for k, v in elo_p.items()},
        "h_news": h_news, "a_news": a_news,
        "h_imp": round(h_imp * 100, 1), "a_imp": round(a_imp * 100, 1),
        "h_form": h_stats["form_str"], "a_form": a_stats["form_str"],
        "h_fpct": h_stats["form_pct"], "a_fpct": a_stats["form_pct"],
        "h_n": h_stats["n"], "a_n": a_stats["n"],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  PICKS SELECTION
# ═══════════════════════════════════════════════════════════════════════════

def get_picks(predictions):
    all_picks = []
    for pred in predictions:
        bets = [
            ("Gana Local", "p1", "1"), ("Empate", "px", "X"), ("Gana Visitante", "p2", "2"),
            ("Ambos Marcan: Si", "btts_y", "btts"), ("Ambos Marcan: No", "btts_n", None),
            ("Mas de 2.5 goles", "o25", "o25"), ("Menos de 2.5 goles", "u25", None),
            ("Mas de 1.5 goles", "o15", "o15"),
        ]
        for label, key, sub_key in bets:
            prob = pred.get(key, 0)
            if prob < MED_CONFIDENCE:
                continue

            # Sub-model agreement
            agree = 0
            threshold = prob * 0.80
            if sub_key:
                pv = pred["poi"].get(sub_key, 0)
                dv = pred["dc"].get(sub_key, 0)
                ev = pred["elo"].get(sub_key, 0)
            elif key == "u25":
                pv = 100 - pred["poi"].get("o25", 50)
                dv = 100 - pred["dc"].get("o25", 50)
                ev = 100 - pred["elo"].get("o25", 50)
            elif key == "btts_n":
                pv = 100 - pred["poi"].get("btts", 50)
                dv = 100 - pred["dc"].get("btts", 50)
                ev = 100 - pred["elo"].get("btts", 50)
            else:
                pv = dv = ev = prob

            if pv >= threshold: agree += 1
            if dv >= threshold: agree += 1
            if ev >= threshold: agree += 1
            if agree < MIN_SUBMODELS:
                continue

            level = "high" if prob >= HIGH_CONFIDENCE else "med"
            all_picks.append({
                "match": f"{pred['home']} vs {pred['away']}",
                "bet": label, "prob": prob,
                "odds": prob_to_odds(prob), "level": level,
                "agree": agree,
                "subs": f"P={pv:.0f}% DC={dv:.0f}% E={ev:.0f}%",
            })

    all_picks.sort(key=lambda x: x["prob"], reverse=True)
    return all_picks


# ═══════════════════════════════════════════════════════════════════════════
#  HISTORY
# ═══════════════════════════════════════════════════════════════════════════

from data_dir import data_path as _dp
HIST_PATH = _dp("resultados.json")


def load_history():
    if os.path.exists(HIST_PATH):
        with open(HIST_PATH, encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_entry(predictions, picks):
    h = load_history()
    h.append({
        "ts": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "predictions": predictions,
        "picks": picks,
        "results": None, "accuracy": None,
    })
    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
#  PROCESS PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def process_matches(match_list):
    """Full pipeline: find teams -> fetch data -> predict -> picks."""
    predictions = []
    log = []

    for home_name, away_name in match_list:
        entry_log = {"home_input": home_name, "away_input": away_name, "steps": []}
        h_info = find_team(home_name)
        a_info = find_team(away_name)

        if h_info:
            entry_log["steps"].append(f"{home_name} -> {h_info['name']} (ID:{h_info['id']})")
        else:
            entry_log["steps"].append(f"{home_name} -> NO ENCONTRADO")
            h_info = {"id": None, "name": home_name, "short": home_name}

        if a_info:
            entry_log["steps"].append(f"{away_name} -> {a_info['name']} (ID:{a_info['id']})")
        else:
            entry_log["steps"].append(f"{away_name} -> NO ENCONTRADO")
            a_info = {"id": None, "name": away_name, "short": away_name}

        # Fetch matches
        h_matches = fetch_matches(h_info["id"], 15) if h_info["id"] else []
        a_matches = fetch_matches(a_info["id"], 15) if a_info["id"] else []
        entry_log["steps"].append(f"Partidos: {len(h_matches)} + {len(a_matches)}")

        # Stats
        h_stats = compute_stats(h_matches, h_info["id"]) if h_info["id"] else compute_stats([], None)
        a_stats = compute_stats(a_matches, a_info["id"]) if a_info["id"] else compute_stats([], None)
        h_elo = int(ELO_INITIAL + h_stats["gd"] * 150)
        a_elo = int(ELO_INITIAL + a_stats["gd"] * 150)

        # News
        h_news = fetch_news(h_info["name"])
        a_news = fetch_news(a_info["name"])
        entry_log["steps"].append(f"Noticias: {len(h_news)} + {len(a_news)}")

        # Predict
        pred = predict(home_name, away_name, h_stats, a_stats,
                       h_elo, a_elo, h_news, a_news)

        # Fetch lineups
        try:
            from lineups import get_lineup, format_lineup_html
            lineup_data = get_lineup(home_name, away_name)
            pred["lineup"] = lineup_data
            pred["lineup_html"] = format_lineup_html(lineup_data, home_name, away_name)
            pred["lineup_confirmed"] = bool(lineup_data and lineup_data.get("teams"))
            entry_log["steps"].append(f"Alineacion: {'confirmada' if pred['lineup_confirmed'] else 'pendiente'}")
        except Exception:
            pred["lineup"] = None
            pred["lineup_html"] = ""
            pred["lineup_confirmed"] = False

        predictions.append(pred)
        log.append(entry_log)

        # Save to results_db for auto-tracking
        try:
            from calibration import save_prediction
            save_prediction(pred)
        except Exception:
            pass

    picks = get_picks(predictions)
    save_entry(predictions, picks)
    return predictions, picks, log


# ═══════════════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
#  LANDING + AUTH + STRIPE ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def landing():
    """Landing page publica con precios y stats."""
    from auth import get_current_user
    user = get_current_user()
    if user:
        return redirect(url_for("app_home"))

    # Gather live stats
    stats = {"accuracy": None, "picks_week": 0, "total_analyzed": 0}
    hist_path = _dp("resultados.json")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                hist = json.load(f)
            verified = [e for e in hist if e.get("accuracy") is not None]
            if verified:
                stats["accuracy"] = round(sum(e["accuracy"] for e in verified) / len(verified), 0)
            stats["total_analyzed"] = sum(len(e.get("predictions", [])) for e in hist)
            # Picks this week
            from datetime import timedelta
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            week_entries = [e for e in hist if e.get("ts", e.get("timestamp", "")) >= week_ago]
            stats["picks_week"] = sum(len(e.get("picks", [])) for e in week_entries)
        except Exception:
            pass

    # Today's picks for preview
    today_picks = []
    picks_path = _dp("picks_del_dia.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                pd = json.load(f)
            today_picks = pd.get("high_confidence_picks", []) + pd.get("medium_confidence_picks", [])
        except Exception:
            pass

    # Next analysis countdown
    now = datetime.now()
    next_9am = now.replace(hour=9, minute=0, second=0)
    if now.hour >= 9:
        next_9am += timedelta(days=1)
    hours_until = max(0, int((next_9am - now).total_seconds() / 3600))

    import random
    viewer_count = random.randint(8, 23)

    # Featured matches
    featured = []
    try:
        from featured_matches import fetch_featured
        fm = fetch_featured()
        featured = fm.get("matches", [])
    except Exception:
        pass

    return render_template("landing.html", stats=stats, today_picks=today_picks,
                           hours_until_next=hours_until,
                           viewer_count=viewer_count,
                           featured=featured)


# ═══════════════════════════════════════════════════════════════════════════
#  FREE REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/register", methods=["POST"])
def register():
    """Registro gratuito con email."""
    email = request.form.get("email", "").strip().lower()
    nombre = request.form.get("nombre", "").strip()

    if not email or not nombre:
        flash("Completa todos los campos")
        return redirect(url_for("landing"))

    from stripe_handler import find_user_by_email, _load_users, _save_users
    _, existing = find_user_by_email(email)
    if existing:
        flash("Ya tienes cuenta. Inicia sesion.")
        return redirect(url_for("login_page"))

    # Create free trial user
    token = secrets.token_urlsafe(32)
    users = _load_users()
    users[token] = {
        "email": email,
        "nombre": nombre,
        "plan": "free_trial",
        "token": token,
        "stripe_customer": "free",
        "created": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=365)).isoformat(),
        "active": True,
        "free_analysis_used": False,
    }
    _save_users(users)

    # Send verification email
    try:
        from email_service import _send, _wrap, _btn
        APP_URL = os.environ.get("APP_URL", request.url_root.rstrip("/"))
        html = _wrap(f'''
        <h2 style="color:#1AE89B;text-align:center">Bienvenido a NEME BET, {nombre}!</h2>
        <p style="color:#ccc;text-align:center">Tu cuenta gratuita esta lista.</p>
        <p style="color:#888;text-align:center;font-size:13px">Tu token de acceso:</p>
        <div style="background:#111;border:1px solid #222;border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#1AE89B;word-break:break-all">{token}</div>
        {_btn("Ver partidos de hoy", f"{APP_URL}/partidos-hoy")}
        ''')
        _send(email, "NEME BET — Tu cuenta gratuita esta lista", html)
    except Exception:
        pass

    # Auto-login
    session["user_email"] = email
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

    flash(f"Cuenta creada! Tienes 1 analisis gratuito.")
    return redirect(url_for("partidos_hoy"))


# ═══════════════════════════════════════════════════════════════════════════
#  PARTIDOS HOY
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/partidos-hoy")
def partidos_hoy():
    from auth import get_current_user

    user = get_current_user()
    if not user:
        flash("Registrate para ver los partidos del dia")
        return redirect(url_for("landing"))

    # Check if free analysis available
    plan = user.get("plan", "free_trial")
    free_available = plan == "free_trial" and not user.get("free_analysis_used", False)
    is_paid = plan in ("basico", "pro", "vip")

    if is_paid:
        return redirect(url_for("picks_route"))

    # Load today's matches
    matches = []
    partidos_path = _dp("partidos_hoy.json")
    if os.path.exists(partidos_path):
        try:
            with open(partidos_path, encoding="utf-8") as f:
                data = json.load(f)
            matches = data.get("matches_relevant", data.get("matches_all", []))[:20]
        except Exception:
            pass

    # Find recommended (highest confidence from picks)
    recommended = None
    picks_path = _dp("picks_del_dia.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                pd = json.load(f)
            all_picks = pd.get("high_confidence_picks", [])
            if all_picks:
                best = all_picks[0]
                # Extract team names from "Team1 vs Team2"
                parts = best.get("match", "").split(" vs ")
                if len(parts) == 2:
                    recommended = {
                        "home": parts[0].strip(), "away": parts[1].strip(),
                        "confidence": best.get("prob", 0),
                        "liga": "", "hora": "",
                    }
        except Exception:
            pass

    return render_template("partidos_hoy.html",
                           matches=matches, recommended=recommended,
                           free_available=free_available)


@app.route("/analizar-partido", methods=["GET", "POST"])
def analizar_partido():
    """Analiza un partido — acceso libre sin restriccion."""
    home = request.form.get("home", "") or request.args.get("home", "")
    away = request.form.get("away", "") or request.args.get("away", "")

    if not home or not away:
        flash("Partido no valido")
        return redirect(url_for("landing"))

    # Run prediction
    predictions, picks, log = process_matches([(home, away)])

    return render_template("results.html",
                           predictions=predictions, picks=picks,
                           log=log, ocr_info=None,
                           HIGH=75.0, MED=65.0,
                           is_free=False,
                           show_upgrade=False)


@app.route("/app")
def app_home():
    """Dashboard personalizado por plan."""
    from auth import get_current_user
    from stripe_handler import filtrar_por_plan

    user = get_current_user()
    if not user:
        return redirect(url_for("landing"))

    plan = user.get("plan", "free_trial")
    rol = user.get("rol", "user")

    # Load picks filtered by plan
    picks = []
    picks_path = _dp("picks_del_dia.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                pd = json.load(f)
            all_picks = pd.get("high_confidence_picks", []) + pd.get("medium_confidence_picks", [])
            picks = filtrar_por_plan(all_picks, plan)
        except Exception:
            pass

    admin_key = os.environ.get("ADMIN_KEY", "")

    import hashlib
    ref_code = hashlib.md5(user.get("email", "").encode()).hexdigest()[:8].upper()
    nombre = user.get("nombre", user.get("email", "").split("@")[0])
    hour = datetime.now().hour
    greeting = "BUENAS NOCHES" if hour >= 18 else ("BUENAS TARDES" if hour >= 12 else "BUENOS DIAS")
    is_admin = rol == "admin"

    return render_template("app_home.html",
                           user=user, plan=plan, picks=picks,
                           user_rol=rol, admin_key=admin_key,
                           now_hour=hour, ref_code=ref_code,
                           nombre=nombre, greeting=greeting)


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        from security import check_honeypot, is_ip_blocked, record_failed_login, record_successful_login
        from stripe_handler import login_with_password, activate_with_token, find_user_by_email

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        if "," in ip:
            ip = ip.split(",")[0].strip()

        if check_honeypot(request.form):
            return redirect(url_for("landing"))

        if is_ip_blocked(ip):
            flash("Acceso bloqueado temporalmente. Intenta en 30 minutos.")
            return render_template("login.html")

        mode = request.form.get("mode", "password")
        email = request.form.get("email", "").strip().lower()

        if mode == "activate":
            # First time: token + create password
            token = request.form.get("token", "").strip()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            if not token or not password or not email:
                flash("Completa todos los campos")
                return render_template("login.html")
            if len(password) < 6:
                flash("La contrasena debe tener al menos 6 caracteres")
                return render_template("login.html")
            if password != password2:
                flash("Las contrasenas no coinciden")
                return render_template("login.html")

            user = activate_with_token(token, password)
            if user:
                record_successful_login(ip, email)
                session["user_email"] = email
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=30)
                # Create guarded session
                try:
                    from session_guard import create_session
                    stk, _ = create_session(email, request)
                    if stk:
                        session["session_token"] = stk
                except Exception:
                    pass
                flash(f"Cuenta activada! Tu contrasena ha sido guardada.")
                return redirect(url_for("app_home"))
            else:
                record_failed_login(ip)
                flash("Token invalido o suscripcion vencida")

        else:
            # Normal login: email + password
            password = request.form.get("password", "")
            if not email or not password:
                flash("Ingresa email y contrasena")
                return render_template("login.html")

            user = login_with_password(email, password)
            if user:
                record_successful_login(ip, email)
                session["user_email"] = email
                remember = request.form.get("remember")
                if remember:
                    session.permanent = True
                    app.permanent_session_lifetime = timedelta(days=30)
                else:
                    session.permanent = False
                # Create guarded session
                try:
                    from session_guard import create_session
                    stk, _ = create_session(email, request)
                    if stk:
                        session["session_token"] = stk
                except Exception:
                    pass
                flash(f"Bienvenido! Plan: {user['plan'].upper()}")
                return redirect(url_for("app_home"))
            else:
                record_failed_login(ip)
                # Check if user exists but has no password
                _, existing = find_user_by_email(email)
                if existing and not existing.get("password_hash"):
                    flash("Debes activar tu cuenta primero. Usa tu token de acceso para crear una contrasena.")
                else:
                    flash("Email o contrasena incorrectos")

    return render_template("login.html")


@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Ingresa tu email")
        return redirect(url_for("login_page"))

    from stripe_handler import create_reset_token
    reset_token = create_reset_token(email)

    if reset_token:
        base = request.url_root.rstrip("/")
        try:
            from email_service import _send, _wrap, _btn
            html = _wrap(f'''
            <h2 style="color:#1AE89B;text-align:center;margin:0 0 16px">Recuperar contrasena</h2>
            <p style="color:#ccc;text-align:center">Alguien solicito cambiar tu contrasena. Si fuiste tu, haz clic en el boton:</p>
            {_btn("Crear nueva contrasena", f"{base}/reset-password/{reset_token}")}
            <p style="font-size:11px;color:#555;text-align:center">Este link expira en 1 hora. Si no solicitaste esto, ignora este email.</p>
            ''')
            _send(email, "NEME BET - Recuperar contrasena", html)
        except Exception:
            pass

    # Always show success (don't reveal if email exists)
    flash("Si el email esta registrado, recibiras un link de recuperacion.")
    return redirect(url_for("login_page"))


@app.route("/reset-password/<reset_token>", methods=["GET", "POST"])
def reset_password_page(reset_token):
    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if len(password) < 6:
            flash("La contrasena debe tener al menos 6 caracteres")
            return render_template("reset_password.html", reset_token=reset_token)
        if password != password2:
            flash("Las contrasenas no coinciden")
            return render_template("reset_password.html", reset_token=reset_token)

        from stripe_handler import reset_password
        if reset_password(reset_token, password):
            flash("Contrasena actualizada. Inicia sesion.")
            return redirect(url_for("login_page"))
        else:
            flash("Link expirado o invalido. Solicita uno nuevo.")
            return redirect(url_for("login_page"))

    return render_template("reset_password.html", reset_token=reset_token)


@app.route("/logout")
def logout():
    session.pop("user_email", None)
    session.pop("token", None)
    flash("Sesion cerrada")
    return redirect(url_for("landing"))


@app.route("/logout-all", methods=["POST"])
def logout_all():
    email = session.get("user_email", "")
    if email:
        from stripe_handler import invalidate_all_sessions
        invalidate_all_sessions(email)
    session.clear()
    flash("Sesion cerrada en todos los dispositivos")
    return redirect(url_for("landing"))


@app.route("/checkout/<plan>")
def checkout(plan):
    if plan not in ("basico", "pro", "vip"):
        flash("Plan no valido")
        return redirect(url_for("landing"))

    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        flash("Stripe no configurado. Contacta al administrador.")
        return redirect(url_for("landing"))

    from stripe_handler import create_checkout_session
    base = request.url_root.rstrip("/")
    sess, error = create_checkout_session(
        plan,
        success_url=f"{base}/success",
        cancel_url=f"{base}/",
    )
    if error:
        flash(f"Error: {error}")
        return redirect(url_for("landing"))

    return redirect(sess.url, code=303)


@app.route("/success")
def success():
    session_id = request.args.get("session_id", "")
    user = None
    if session_id:
        from stripe_handler import handle_checkout_success
        user = handle_checkout_success(session_id)
        if user:
            session["token"] = user["token"]
            session.permanent = True
            app.permanent_session_lifetime = timedelta(days=30)

    plan = user["plan"] if user else "?"
    token = user["token"] if user else None
    return render_template("success.html", plan=plan, token=token)


@app.route("/cancel")
def cancel():
    flash("Pago cancelado. Puedes intentar de nuevo.")
    return redirect(url_for("landing"))


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    from stripe_handler import handle_webhook
    if handle_webhook(payload, sig):
        return "ok", 200
    return "error", 400


@app.route("/health")
def health():
    try:
        from security import get_health_status
        return jsonify(get_health_status())
    except Exception:
        return jsonify({"status": "ok"})


@app.route("/predict", methods=["POST"])
def predict_route():
    match_list = []
    ocr_info = None

    # Image upload
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ALLOWED_EXTENSIONS:
                fname = secure_filename(f"upload_{int(time.time())}.{ext}")
                fpath = os.path.join(UPLOAD_FOLDER, fname)
                file.save(fpath)
                match_list, ocr_info = ocr_extract_matches(fpath)

    # Manual text
    text = request.form.get("matches", "").strip()
    if text:
        manual = parse_matches(text)
        match_list.extend(manual)

    if not match_list:
        flash("No se detectaron partidos. Escribe manualmente o sube otra imagen.")
        return redirect(url_for("index"))

    # Deduplicate
    seen = set()
    unique = []
    for h, a in match_list:
        key = (h.lower(), a.lower())
        if key not in seen:
            seen.add(key)
            unique.append((h, a))
    match_list = unique

    try:
        predictions, picks, log = process_matches(match_list)
    except Exception as e:
        flash(f"Error procesando: {e}")
        traceback.print_exc()
        return redirect(url_for("index"))

    return render_template("results.html",
                           predictions=predictions, picks=picks,
                           log=log, ocr_info=ocr_info,
                           HIGH=HIGH_CONFIDENCE, MED=MED_CONFIDENCE)


@app.route("/history")
def history():
    h = load_history()
    h.reverse()

    total = len(h)
    verified = [e for e in h if e.get("accuracy") is not None]
    avg_acc = round(sum(e["accuracy"] for e in verified) / len(verified), 1) if verified else None

    return render_template("history.html", entries=h[:50],
                           total=total, verified=len(verified), avg_acc=avg_acc)


@app.route("/result", methods=["POST"])
def add_result():
    match = request.form.get("match", "")
    hg = request.form.get("home_goals", "")
    ag = request.form.get("away_goals", "")

    if not match or not hg.isdigit() or not ag.isdigit():
        flash("Datos invalidos")
        return redirect(url_for("history"))

    hg, ag = int(hg), int(ag)
    hist = load_history()
    updated = False

    for entry in reversed(hist):
        if entry.get("results") is not None:
            continue
        for pred in entry.get("predictions", []):
            label = f"{pred['home']} vs {pred['away']}"
            if match.lower() in label.lower():
                if entry["results"] is None:
                    entry["results"] = {}
                entry["results"][label] = {"hg": hg, "ag": ag}

                correct = 0
                p1x2 = "1" if pred["p1"] > max(pred["px"], pred["p2"]) else (
                    "X" if pred["px"] > pred["p2"] else "2")
                r1x2 = "1" if hg > ag else ("X" if hg == ag else "2")
                if p1x2 == r1x2: correct += 1
                if (pred["o25"] > 50) == (hg + ag > 2.5): correct += 1
                if (pred["btts_y"] > 50) == (hg > 0 and ag > 0): correct += 1

                entry["accuracy"] = round(correct / 3 * 100, 1)
                updated = True
                flash(f"Resultado guardado: {label} {hg}-{ag} | Acierto: {correct}/3")
                break
        if updated:
            break

    if updated:
        with open(HIST_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2, default=str)
    else:
        flash(f"No encontre '{match}' pendiente")

    return redirect(url_for("history"))


# ═══════════════════════════════════════════════════════════════════════════
#  ODDS SCANNER ROUTE
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/scanner", methods=["GET", "POST"])
def scanner():
    if request.method == "POST":
        # Obtener predicciones del ultimo analisis
        hist = load_history()
        if not hist:
            flash("Primero analiza algunos partidos")
            return redirect(url_for("index"))

        last = hist[-1]
        predictions = last.get("predictions", [])

        # Parsear cuotas manuales del formulario
        odds_list = []
        for i, pred in enumerate(predictions):
            h_odds = request.form.get(f"home_{i}", "")
            d_odds = request.form.get(f"draw_{i}", "")
            a_odds = request.form.get(f"away_{i}", "")
            if h_odds and d_odds and a_odds:
                try:
                    odds_list.append({
                        "home": float(h_odds),
                        "draw": float(d_odds),
                        "away": float(a_odds),
                    })
                except ValueError:
                    odds_list.append(None)
            else:
                odds_list.append(None)

        from odds_scanner import scan_all
        scan_results = scan_all(predictions, odds_list)

        return render_template("scanner.html",
                               predictions=predictions,
                               scan_results=scan_results)

    # GET: show form with last predictions
    hist = load_history()
    predictions = hist[-1].get("predictions", []) if hist else []
    return render_template("scanner.html",
                           predictions=predictions,
                           scan_results=None)


# ═══════════════════════════════════════════════════════════════════════════
#  DASHBOARD (Autoaprendizaje + Calibracion)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/learn")
def learn_redirect():
    return redirect(url_for("dashboard_route"))


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard_route():
    from calibration import get_dashboard, calibrate, check_pending_results

    cal_result = None
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "calibrate":
            result = calibrate()
            if result["status"] == "calibrated":
                cal_result = f"Calibrado con {result['n']} muestras. {result['errors']} errores analizados."
                flash("Calibracion completada")
            else:
                flash(f"Necesitas al menos {result.get('min', 3)} resultados verificados")
        elif action == "check_results":
            updated = check_pending_results()
            flash(f"{updated} resultados encontrados automaticamente" if updated else "Sin resultados nuevos")

    dash = get_dashboard()
    return render_template("dashboard.html", dash=dash, cal_result=cal_result)


# ═══════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/notifications")
def get_notifications():
    """Retorna notificaciones pendientes para el frontend."""
    notifs = []

    # Check for pending results
    db_path = _dp("results_db.json")
    if os.path.exists(db_path):
        with open(db_path, encoding="utf-8") as f:
            try:
                db = json.load(f)
                pending = [e for e in db if not e.get("verified")]
                overdue = [e for e in pending
                           if e.get("check_after", "") < datetime.now().isoformat()]
                if overdue:
                    notifs.append({
                        "type": "result",
                        "title": f"{len(overdue)} resultado(s) por verificar",
                        "body": "Toca para buscar resultados automaticamente",
                        "url": "/dashboard",
                    })
            except: pass

    # Check for value bets from last scan
    hist = load_history()
    if hist:
        last = hist[-1]
        for pick in last.get("picks", []):
            if pick.get("prob", 0) >= 75:
                notifs.append({
                    "type": "pick",
                    "title": f"Pick: {pick['bet']} ({pick['prob']}%)",
                    "body": pick.get("match", ""),
                    "url": "/history",
                })

    return jsonify(notifs)


# ═══════════════════════════════════════════════════════════════════════════
#  PICKS DEL DIA
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/picks")
def picks_route():
    from auth import get_current_user
    from stripe_handler import filtrar_por_plan

    user = get_current_user()
    plan = user.get("plan", "free_trial") if user else "free_trial"

    picks_path = _dp("picks_del_dia.json")
    data = None
    if os.path.exists(picks_path):
        with open(picks_path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                pass

    # Filter picks by plan confidence level
    if data:
        all_picks = data.get("high_confidence_picks", []) + data.get("medium_confidence_picks", [])
        data["filtered_picks"] = filtrar_por_plan(all_picks, plan)
        data["plan"] = plan

    return render_template("picks.html", data=data, plan=plan)


@app.route("/picks/scan", methods=["POST"])
def picks_scan():
    """Ejecuta scraping + analisis manualmente."""
    try:
        from besoccer_scraper import scrape_today
        scrape_result = scrape_today()
        flash(f"Scraping: {scrape_result['relevant']} partidos relevantes")
    except Exception as e:
        flash(f"Error scraping: {e}")
        return redirect(url_for("picks_route"))

    try:
        from auto_analyze import analyze_today
        analysis = analyze_today()
        if analysis:
            high = len(analysis["high_confidence_picks"])
            flash(f"Analisis: {analysis['analyzed']} partidos, {high} picks +75%")
        else:
            flash("Sin partidos para analizar")
    except Exception as e:
        flash(f"Error analisis: {e}")

    return redirect(url_for("picks_route"))


# ═══════════════════════════════════════════════════════════════════════════
#  PUSH NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/push/key")
def push_public_key():
    """Retorna clave publica VAPID para suscripcion push."""
    try:
        from push_notify import get_public_key
        return jsonify({"publicKey": get_public_key()})
    except Exception:
        return jsonify({"publicKey": None})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    """Registra suscripcion push de un cliente."""
    sub = request.get_json()
    if not sub:
        return jsonify({"error": "subscription required"}), 400
    try:
        from push_notify import save_subscription
        count = save_subscription(sub)
        return jsonify({"ok": True, "total": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
#  ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

def _admin_auth():
    admin_key = os.environ.get("ADMIN_KEY", "")
    provided = request.args.get("key", "") or request.form.get("key", "")
    if not admin_key or provided != admin_key:
        return None, provided
    return admin_key, provided


@app.route("/admin", methods=["GET", "POST"])
@app.route("/admin/create-user", methods=["GET", "POST"])
def admin_dashboard():
    key, provided = _admin_auth()
    if not key:
        return jsonify({"error": "Unauthorized. Use ?key=YOUR_ADMIN_KEY"}), 403

    users_path = _dp("users.json")
    users = {}
    if os.path.exists(users_path):
        with open(users_path, encoding="utf-8") as f:
            try: users = json.load(f)
            except: users = {}

    # Handle POST actions
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "create":
            import secrets as sec
            email = request.form.get("email", "").strip()
            plan = request.form.get("plan", "pro")
            days = int(request.form.get("days", "30"))
            if email:
                token = sec.token_urlsafe(32)
                users[token] = {
                    "email": email, "plan": plan, "token": token,
                    "stripe_customer": "admin_created",
                    "stripe_session": "admin_created",
                    "created": datetime.now().isoformat(),
                    "expires": (datetime.now() + timedelta(days=days)).isoformat(),
                    "active": True,
                }
                with open(users_path, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2)
                try:
                    from email_service import send_welcome
                    send_welcome(email, token, plan)
                except Exception:
                    pass
                flash(f"Usuario creado: {email} ({plan}) Token: {token[:15]}...")

        elif action == "cancel":
            cancel_token = request.form.get("token", "")
            if cancel_token in users:
                users[cancel_token]["active"] = False
                with open(users_path, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2)
                flash(f"Usuario cancelado: {users[cancel_token].get('email', '?')}")

        return redirect(f"/admin?key={provided}")

    # Compute stats
    prices = {"basico": 9.99, "pro": 24.99, "vip": 49.99}
    active = {t: u for t, u in users.items() if u.get("active")}
    plans = {}
    for u in active.values():
        p = u.get("plan", "?")
        plans[p] = plans.get(p, 0) + 1
    mrr = sum(prices.get(u.get("plan", ""), 0) for u in active.values())
    expired = len(users) - len(active)

    stats = {
        "total_users": len(users),
        "active_users": len(active),
        "mrr": f"{mrr:.2f}",
        "plan_basico": plans.get("basico", 0),
        "plan_pro": plans.get("pro", 0),
        "plan_vip": plans.get("vip", 0),
        "expired": expired,
    }

    # Picks data
    picks_path = _dp("picks_del_dia.json")
    picks_data = None
    if os.path.exists(picks_path):
        with open(picks_path, encoding="utf-8") as f:
            try: picks_data = json.load(f)
            except: pass

    # Accuracy
    accuracy = None
    try:
        from calibration import get_dashboard
        dash = get_dashboard()
        accuracy = {"acc_1x2": dash.get("acc_all"), "acc_ou": None, "n": dash.get("verified", 0)}
    except Exception:
        pass

    # Scheduler logs
    slog_path = _dp("scheduler_log.json")
    scheduler_logs = []
    if os.path.exists(slog_path):
        with open(slog_path, encoding="utf-8") as f:
            try: scheduler_logs = json.load(f)
            except: pass

    # Sharing suspects
    sharing_suspects = []
    try:
        from session_guard import get_multi_ip_users
        sharing_suspects = get_multi_ip_users(24)
    except Exception:
        pass

    return render_template("admin.html",
                           stats=stats, users=users, key=provided,
                           picks_data=picks_data, accuracy=accuracy,
                           scheduler_logs=scheduler_logs,
                           sharing_suspects=sharing_suspects)


# ═══════════════════════════════════════════════════════════════════════════
#  API: RECENT WINS (auto-refresh)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/recent-wins")
def _get_recent_wins():
    """Analisis acertados de las ultimas 48 horas."""
    cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
    wins = []
    db_path = _dp("results_db.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, encoding="utf-8") as f:
                db = json.load(f)
            for e in reversed(db):
                pa = e.get("predicted_at", e.get("created", ""))
                if pa and pa < cutoff:
                    continue
                if e.get("verified") and e.get("accuracy", {}).get("1x2_ok"):
                    p1x2 = e["accuracy"]["1x2_pred"]
                    prob = e["p1"] if p1x2 == "1" else (e["px"] if p1x2 == "X" else e["p2"])
                    label = {"1": "Gana Local", "X": "Empate", "2": "Gana Visitante"}.get(p1x2, p1x2)
                    wins.append({"match": f"{e['home']} vs {e['away']}", "market": label,
                                 "prob": prob, "result": f"{e['home_goals']}-{e['away_goals']}",
                                 "date": pa[:10] if pa else ""})
                if len(wins) >= 3:
                    break
        except Exception:
            pass
    return wins


# ═══════════════════════════════════════════════════════════════════════════
#  API: PARTIDOS HOY
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/picks-ahora")
def api_picks_ahora():
    """Retorna picks disponibles ahora — sin restriccion de horario."""
    from auth import get_current_user
    from stripe_handler import filtrar_por_plan

    user = get_current_user()
    plan = user.get("plan", "free_trial") if user else "free_trial"

    # Load existing picks
    picks_path = _dp("picks_del_dia.json")
    all_picks = []
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                pd = json.load(f)
            all_picks = pd.get("high_confidence_picks", []) + pd.get("medium_confidence_picks", [])
        except Exception:
            pass

    # All users see all picks
    filtered = filtrar_por_plan(all_picks, plan)

    return jsonify({
        "picks": filtered,
        "total": len(filtered),
        "all_total": len(all_picks),
        "plan": plan,
        "generado": datetime.now().isoformat(),
    })


@app.route("/api/partidos-hoy")
def api_partidos_hoy():
    """Retorna partidos proximos. ?force=true para forzar refresco."""
    try:
        force = request.args.get("force", "false").lower() == "true"
        from featured_matches import fetch_partidos
        data = fetch_partidos(force=force)
        return jsonify(data)
    except Exception as e:
        print(f"[ERROR] /api/partidos-hoy: {e}")
        return jsonify({"partidos": [], "total": 0, "error": str(e),
                        "actualizado": datetime.now().isoformat()})


@app.route("/api/version")
def api_version():
    import hashlib
    try:
        mtime = str(os.path.getmtime(os.path.abspath(__file__)))
        version = hashlib.md5(mtime.encode()).hexdigest()[:8]
    except Exception:
        version = "v1"
    return jsonify({"version": version, "ts": datetime.now().isoformat()})


@app.after_request
def cache_headers(response):
    if "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/api/status")
def api_status():
    """Estado del sistema en tiempo real."""
    try:
        from featured_matches import CACHE_FILE, _env_key
        cache_age = None
        if os.path.exists(CACHE_FILE):
            cache_age = int(time.time() - os.path.getmtime(CACHE_FILE))

        return jsonify({
            "status": "ok",
            "cache_age_seconds": cache_age,
            "cache_fresco": cache_age < 300 if cache_age else False,
            "scheduler_activo": _scheduler_started,
            "hora_servidor": datetime.now().isoformat(),
            "api_football_key": bool(os.environ.get("API_FOOTBALL_KEY") or ENV.get("API_FOOTBALL_KEY")),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
#  REFERIDOS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/r/<codigo>")
def referido(codigo):
    session["referido_por"] = codigo
    return redirect(url_for("landing"))


# ═══════════════════════════════════════════════════════════════════════════
#  API JSON ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/predict", methods=["POST"])
def api_predict():
    data = request.get_json()
    if not data or "matches" not in data:
        return jsonify({"error": "Campo 'matches' requerido"}), 400
    match_list = parse_matches(data["matches"])
    if not match_list:
        return jsonify({"error": "No se detectaron partidos"}), 400
    predictions, picks, log = process_matches(match_list)
    return jsonify({"predictions": predictions, "picks": picks,
                    "timestamp": datetime.now().isoformat()})


# ═══════════════════════════════════════════════════════════════════════════
#  CONTEXT PROCESSOR — badge count for nav
# ═══════════════════════════════════════════════════════════════════════════

@app.context_processor
def inject_picks_count():
    picks_path = _dp("picks_del_dia.json")
    count = 0
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                data = json.load(f)
                count = len(data.get("high_confidence_picks", []))
        except Exception:
            pass
    # Check if current user is admin
    is_admin = False
    user_plan = None
    try:
        from auth import get_current_user
        u = get_current_user()
        if u:
            is_admin = u.get("rol") == "admin"
            user_plan = u.get("plan", "")
    except Exception:
        pass

    return {"picks_count": count, "is_admin": is_admin, "user_plan": user_plan}


# ═══════════════════════════════════════════════════════════════════════════
#  SCHEDULER INIT
# ═══════════════════════════════════════════════════════════════════════════

_scheduler_started = False

def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    try:
        from scheduler import init_scheduler
        init_scheduler(app)
    except Exception as e:
        print(f"[SCHEDULER] No iniciado: {e}")


# Init DB + scheduler when app is imported by gunicorn
try:
    from init_db import init
    init()
except Exception as e:
    print(f"[INIT_DB] {e}")

try:
    from setup_railway import inicializar
    inicializar()
except Exception as e:
    print(f"[SETUP] {e}")

start_scheduler()


# ═══════════════════════════════════════════════════════════════════════════
#  ENSURE PICKS EXIST (Railway pierde /app/data en redeploys)
# ═══════════════════════════════════════════════════════════════════════════


def auto_generar_picks_hoy():
    """Toma partidos de API-Football y genera picks con Claude."""
    import urllib.request, json
    from featured_matches import fetch_partidos

    path = _dp('picks_del_dia.json')
    hoy = datetime.now().strftime('%Y-%m-%d')

    # Si ya hay picks de hoy no hacer nada
    # Siempre eliminar picks viejos al arrancar
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            fecha_picks = data.get('fecha', '')
            if fecha_picks == hoy and data.get('high_confidence_picks'):
                print('[AUTO-PICKS] Ya existen picks de hoy:', hoy)
                return
            else:
                os.remove(path)
                print('[AUTO-PICKS] Picks viejos eliminados, fecha era:', fecha_picks)
        except Exception:
            os.remove(path)
        except Exception:
            pass

    print('[AUTO-PICKS] Generando picks nuevos...')
    try:
        data_partidos = fetch_partidos(force=True)
        partidos = data_partidos.get('partidos', [])[:15]
        if not partidos:
            print('[AUTO-PICKS] No hay partidos disponibles hoy')
            return

        lista = chr(10).join([f"- {p['home']} vs {p['away']} ({p['liga']}, {p['hora']})" for p in partidos])

        prompt = f"""Eres NEMEBET, experto en predicciones deportivas. Hoy es {hoy}.

Partidos disponibles hoy:
{lista}

Selecciona los 3-5 mejores picks aplicando estas reglas:
1. BTTS es mas seguro que +2.5 en partidos europeos
2. Sistema defensivo del visitante es critico
3. Bajas de mediocampo impactan mas que bajas de ataque
4. H2H reciente es el indicador mas confiable
5. Solo picks con probabilidad real mayor al 62%
6. Si la cuota no justifica el riesgo, omitir

Responde SOLO con JSON valido, sin texto extra, sin markdown:
{{
  "fecha": "{hoy}",
  "high_confidence_picks": [
    {{
      "id": "unico_id",
      "local": "nombre local",
      "visitante": "nombre visitante",
      "match": "Local vs Visitante",
      "liga": "nombre liga",
      "hora": "HH:MM",
      "confianza": 70,
      "prob": 70,
      "mercado": "descripcion mercado",
      "bet": "descripcion apuesta",
      "cuota_referencia": 1.75,
      "odds": 1.75,
      "edge": 20,
      "justificacion": "razon matematica",
      "estado": "pendiente",
      "recomendado": true
    }}
  ],
  "medium_confidence_picks": []
}}"""

        key = os.environ.get('ANTHROPIC_API_KEY', ENV.get('ANTHROPIC_API_KEY', ''))
        if not key:
            print('[AUTO-PICKS] Sin ANTHROPIC_API_KEY')
            return

        body = json.dumps({
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 2000,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()

        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body)
        req.add_header('x-api-key', key)
        req.add_header('anthropic-version', '2023-06-01')
        req.add_header('content-type', 'application/json')

        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())

        texto = resp["content"][0]["text"].strip()
        texto = resp['content'][0]['text'].strip()
        # Limpiar markdown
        if '```' in texto:
            partes = texto.split('```')
            for p in partes:
                p = p.strip().lstrip('json').strip()
                if p.startswith('{'):
                    texto = p
                    break
            for p in partes:
                p = p.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    texto = p
                    break
        
        picks_data = json.loads(texto)
        picks_data['generado'] = datetime.now().isoformat()

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(picks_data, f, ensure_ascii=False, indent=2)
        print(f'[AUTO-PICKS] {len(picks_data.get("high_confidence_picks",[]))} picks guardados')

    except Exception as e:
        print(f'[AUTO-PICKS] Error: {e}')

def ensure_picks_del_dia():
    """Solo conserva picks si son de HOY. Si son viejos los elimina."""
    path = _dp("picks_del_dia.json")
    hoy = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("fecha") == hoy and data.get("high_confidence_picks"):
                return
        except Exception:
            pass
        os.remove(path)
        print("[PICKS] Picks viejos eliminados")
        return

    picks = {
        "fecha": "2026-04-09",
        "generado": datetime.now().isoformat(),
        "high_confidence_picks": [
            {
                "id": "uel_freiburg_celta", "local": "Freiburg", "visitante": "Celta Vigo",
                "match": "Freiburg vs Celta Vigo",
                "liga": "UEFA Europa League", "hora": "21:00",
                "confianza": 74, "prob": 74,
                "mercado": "Ambos Marcan \u2014 S\u00cd", "bet": "Ambos Marcan \u2014 S\u00cd",
                "cuota_referencia": 1.75, "odds": 1.75, "edge": 29, "agree": 3,
                "justificacion": "BTTS s\u00ed en 6 de 7 partidos de Celta. BTTS s\u00ed en 4 de 5 de Freiburg en casa. Celta m\u00e1ximo goleador UEL (21 goles). Freiburg 9 victorias seguidas en casa europea.",
                "mercados_adicionales": [
                    {"mercado": "M\u00e1s de 2.5 goles", "confianza": 68},
                    {"mercado": "Freiburg Gana", "confianza": 66}
                ],
                "estado": "pendiente", "recomendado": True
            },
            {
                "id": "uel_bologna_villa", "local": "Bologna", "visitante": "Aston Villa",
                "match": "Bologna vs Aston Villa",
                "liga": "UEFA Europa League", "hora": "21:00",
                "confianza": 77, "prob": 77,
                "mercado": "Aston Villa NO pierde", "bet": "Aston Villa NO pierde",
                "cuota_referencia": 1.65, "odds": 1.65, "edge": 22, "agree": 3,
                "justificacion": "Villa gan\u00f3 los 2 H2H vs Bologna sin conceder. 7 victorias UEL seguidas. Emery 4 t\u00edtulos UEL. Bologna sin Skorupski ni Vitik.",
                "mercados_adicionales": [
                    {"mercado": "Menos de 2.5 goles", "confianza": 72},
                    {"mercado": "McGinn Anytime scorer", "confianza": 47}
                ],
                "estado": "pendiente", "recomendado": False
            },
            {
                "id": "uel_porto_forest", "local": "Porto", "visitante": "Nottingham Forest",
                "match": "Porto vs Nottingham Forest",
                "liga": "UEFA Europa League", "hora": "21:00",
                "confianza": 62, "prob": 62,
                "mercado": "Porto Gana", "bet": "Porto Gana",
                "cuota_referencia": 2.10, "odds": 2.10, "edge": 12, "agree": 2,
                "justificacion": "Porto invicto en casa UEL (5V 0E 0P). L\u00edderes Liga Portugal. Forest ya gan\u00f3 2-0 a Porto esta temporada. Porto sin Aghehowa.",
                "mercados_adicionales": [
                    {"mercado": "Forest +0.25 Asian Handicap", "confianza": 61},
                    {"mercado": "Igor Jesus Anytime scorer", "confianza": 52}
                ],
                "estado": "pendiente", "recomendado": False
            }
        ],
        "medium_confidence_picks": []
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)
    print(f"[PICKS] Picks UEL recreados en {path}")

try:
    auto_generar_picks_hoy()
except Exception as e:
    print(f"[AUTO-PICKS] Error al inicio: {e}")
try:
    ensure_picks_del_dia()
except Exception as e:
    print(f"[PICKS] Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    import socket
    port = int(os.environ.get("PORT", 5000))

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "0.0.0.0"

    print(f"\n{'=' * 60}")
    print(f"  NEME BET v5.0 — Analisis Estadistico Avanzado")
    print(f"{'=' * 60}")
    print(f"\n  PC:       http://localhost:{port}")
    print(f"  Telefono: http://{local_ip}:{port}")
    print(f"\n  Ctrl+C para detener\n")

    app.run(host="0.0.0.0", port=port, debug=False)

@app.route('/admin/regenerar-picks')
def admin_regenerar_picks():
    try:
        auto_generar_picks_hoy()
        path = _dp('picks_del_dia.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'ok': True, 'picks': len(data.get('high_confidence_picks', [])), 'fecha': data.get('fecha')})
        return jsonify({'ok': False, 'error': 'Archivo no creado'})
    except Exception as e:
        import traceback
        return jsonify({'ok': False, 'error': str(e), 'trace': traceback.format_exc()})

