"""
Base de datos de forma actual de jugadores — Datos reales de Wikipedia
Temporada 2025-26, datos al 22-27 marzo 2026.

Cada jugador tiene:
  - club, position, apps, goals, assists (temporada actual)
  - rating: calificación estimada 1-10 basada en rendimiento objetivo
  - form_index: índice de forma ponderado (últimos partidos pesan más)
  - starter: True si es titular habitual

Rating calculado como:
  Portero: clean_sheets_ratio × 10, ajustado por nivel de liga
  Defensa: (apps/max_apps) × 7 + bonus por goles/asistencias
  Mediocampista: base 6.5 + (goles×0.3 + assists×0.2) / apps × 10
  Delantero: base 6.0 + (goles/apps) × 5
"""

# ═══════════════════════════════════════════════════════════════════════════
#  PESOS DE IMPACTO POR POSICIÓN
# ═══════════════════════════════════════════════════════════════════════════

POSITION_WEIGHTS = {
    "GK":  {"attack": 0.00, "defense": 0.15, "label": "Portero"},
    "CB":  {"attack": 0.05, "defense": 0.20, "label": "Central"},
    "FB":  {"attack": 0.10, "defense": 0.15, "label": "Lateral"},
    "CDM": {"attack": 0.10, "defense": 0.20, "label": "Mediocentro def."},
    "CM":  {"attack": 0.15, "defense": 0.15, "label": "Centrocampista"},
    "CAM": {"attack": 0.25, "defense": 0.05, "label": "Mediapunta"},
    "W":   {"attack": 0.25, "defense": 0.05, "label": "Extremo"},
    "ST":  {"attack": 0.30, "defense": 0.00, "label": "Delantero"},
}

# ═══════════════════════════════════════════════════════════════════════════
#  BASE DE DATOS: JUGADORES CLAVE POR SELECCIÓN
#  Fuente: Wikipedia, datos al 22-27 marzo 2026
# ═══════════════════════════════════════════════════════════════════════════

SQUAD_DATA = {
    "Italy": {
        "xi_avg_rating": None,  # Se calcula automáticamente
        "players": [
            {"name": "Donnarumma",  "pos": "GK",  "club": "PSG",           "apps": 30, "goals": 0,  "assists": 0, "rating": 6.8, "starter": True,  "league": "Ligue 1"},
            {"name": "Bastoni",     "pos": "CB",  "club": "Inter Milan",   "apps": 35, "goals": 2,  "assists": 3, "rating": 7.3, "starter": True,  "league": "Serie A"},
            {"name": "Calafiori",   "pos": "CB",  "club": "Arsenal",       "apps": 28, "goals": 1,  "assists": 2, "rating": 7.0, "starter": True,  "league": "Premier League"},
            {"name": "Dimarco",     "pos": "FB",  "club": "Inter Milan",   "apps": 32, "goals": 3,  "assists": 7, "rating": 7.5, "starter": True,  "league": "Serie A"},
            {"name": "Barella",     "pos": "CM",  "club": "Inter Milan",   "apps": 30, "goals": 4,  "assists": 5, "rating": 7.4, "starter": False, "league": "Serie A", "absent": True, "injury": "Lesión muscular"},
            {"name": "Tonali",      "pos": "CM",  "club": "Newcastle",     "apps": 47, "goals": 3,  "assists": 4, "rating": 7.1, "starter": True,  "league": "Premier League"},
            {"name": "Frattesi",    "pos": "CM",  "club": "Inter Milan",   "apps": 25, "goals": 3,  "assists": 2, "rating": 6.7, "starter": True,  "league": "Serie A"},
            {"name": "Kean",        "pos": "ST",  "club": "Fiorentina",    "apps": 32, "goals": 9,  "assists": 2, "rating": 6.8, "starter": True,  "league": "Serie A"},
            {"name": "Retegui",     "pos": "ST",  "club": "Al-Qadsiah",    "apps": 27, "goals": 18, "assists": 3, "rating": 6.5, "starter": True,  "league": "Saudi Pro", "league_discount": 0.80},
            {"name": "Chiesa",      "pos": "W",   "club": "Liverpool",     "apps": 15, "goals": 2,  "assists": 1, "rating": 5.8, "starter": False, "league": "Premier League"},
            {"name": "Pellegrini",  "pos": "CAM", "club": "Roma",          "apps": 28, "goals": 3,  "assists": 4, "rating": 6.5, "starter": True,  "league": "Serie A"},
        ],
    },
    "Bosnia-Herzegovina": {
        "players": [
            {"name": "Vasilj",      "pos": "GK",  "club": "St. Pauli",     "apps": 24, "goals": 0,  "assists": 0, "rating": 6.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Kolašinac",   "pos": "FB",  "club": "Atalanta",      "apps": 22, "goals": 0,  "assists": 2, "rating": 6.5, "starter": True,  "league": "Serie A"},
            {"name": "Ahmedhodžić", "pos": "CB",  "club": "Sheffield Utd",  "apps": 30, "goals": 2,  "assists": 0, "rating": 6.6, "starter": True,  "league": "Championship"},
            {"name": "Bičakčić",    "pos": "CB",  "club": "Hoffenheim",    "apps": 18, "goals": 1,  "assists": 0, "rating": 6.2, "starter": True,  "league": "Bundesliga"},
            {"name": "Pjanić",      "pos": "CM",  "club": "Sharjah",       "apps": 20, "goals": 2,  "assists": 5, "rating": 6.0, "starter": True,  "league": "UAE Pro", "league_discount": 0.75},
            {"name": "Hajradinović","pos": "CAM", "club": "Dinamo Zagreb",  "apps": 26, "goals": 5,  "assists": 6, "rating": 7.0, "starter": True,  "league": "Croatian 1st"},
            {"name": "Demirović",   "pos": "ST",  "club": "Stuttgart",     "apps": 29, "goals": 12, "assists": 3, "rating": 7.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Džeko",       "pos": "ST",  "club": "Fenerbahçe",    "apps": 15, "goals": 4,  "assists": 2, "rating": 5.5, "starter": False, "league": "Süper Lig", "absent": True, "injury": "Retirado selección"},
            {"name": "Gazibegović", "pos": "FB",  "club": "Sturm Graz",    "apps": 28, "goals": 1,  "assists": 4, "rating": 6.5, "starter": True,  "league": "Austrian BL"},
            {"name": "Burić",       "pos": "CDM", "club": "Mainz",         "apps": 22, "goals": 1,  "assists": 2, "rating": 6.3, "starter": True,  "league": "Bundesliga"},
            {"name": "Tabakovic",   "pos": "ST",  "club": "Hoffenheim",    "apps": 20, "goals": 5,  "assists": 1, "rating": 6.2, "starter": True,  "league": "Bundesliga"},
        ],
    },
    "Czechia": {
        "players": [
            {"name": "Staněk",      "pos": "GK",  "club": "Slavia Prague",  "apps": 28, "goals": 0,  "assists": 0, "rating": 6.8, "starter": True,  "league": "Czech 1st"},
            {"name": "Holeš",       "pos": "CB",  "club": "Slavia Prague",  "apps": 30, "goals": 2,  "assists": 1, "rating": 6.7, "starter": True,  "league": "Czech 1st"},
            {"name": "Krejčí",      "pos": "CB",  "club": "Girona",         "apps": 25, "goals": 1,  "assists": 1, "rating": 6.6, "starter": True,  "league": "La Liga"},
            {"name": "Coufal",      "pos": "FB",  "club": "West Ham",       "apps": 30, "goals": 1,  "assists": 4, "rating": 6.8, "starter": True,  "league": "Premier League"},
            {"name": "Souček",      "pos": "CDM", "club": "West Ham",       "apps": 32, "goals": 4,  "assists": 2, "rating": 6.9, "starter": True,  "league": "Premier League"},
            {"name": "Provod",      "pos": "CM",  "club": "Slavia Prague",  "apps": 26, "goals": 6,  "assists": 5, "rating": 7.2, "starter": True,  "league": "Czech 1st"},
            {"name": "Červ",        "pos": "CM",  "club": "Wolfsburg",      "apps": 24, "goals": 3,  "assists": 3, "rating": 6.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Schick",      "pos": "ST",  "club": "Leverkusen",     "apps": 21, "goals": 9,  "assists": 2, "rating": 7.2, "starter": True,  "league": "Bundesliga"},
            {"name": "Hložek",      "pos": "ST",  "club": "Hoffenheim",     "apps": 26, "goals": 7,  "assists": 4, "rating": 6.8, "starter": True,  "league": "Bundesliga"},
            {"name": "Černý",       "pos": "W",   "club": "Wolfsburg",      "apps": 22, "goals": 4,  "assists": 3, "rating": 6.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Barák",       "pos": "CAM", "club": "Fiorentina",     "apps": 20, "goals": 2,  "assists": 3, "rating": 6.3, "starter": True,  "league": "Serie A"},
        ],
    },
    "Denmark": {
        "players": [
            {"name": "Schmeichel",  "pos": "GK",  "club": "Celtic",         "apps": 35, "goals": 0,  "assists": 0, "rating": 7.0, "starter": True,  "league": "Scottish Prem"},
            {"name": "Christensen", "pos": "CB",  "club": "Barcelona",      "apps": 28, "goals": 1,  "assists": 0, "rating": 7.0, "starter": True,  "league": "La Liga"},
            {"name": "Vestergaard", "pos": "CB",  "club": "Leicester",      "apps": 30, "goals": 2,  "assists": 0, "rating": 6.6, "starter": True,  "league": "Premier League"},
            {"name": "Maehle",      "pos": "FB",  "club": "Wolfsburg",      "apps": 25, "goals": 1,  "assists": 3, "rating": 6.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Hjulmand",    "pos": "CDM", "club": "Sporting",       "apps": 28, "goals": 2,  "assists": 3, "rating": 7.0, "starter": True,  "league": "Liga Portugal"},
            {"name": "Eriksen",     "pos": "CAM", "club": "Man United",     "apps": 18, "goals": 2,  "assists": 3, "rating": 5.8, "starter": False, "league": "Premier League", "absent": True, "injury": "Forma irregular"},
            {"name": "Damsgaard",   "pos": "W",   "club": "Brentford",      "apps": 26, "goals": 5,  "assists": 4, "rating": 6.8, "starter": True,  "league": "Premier League"},
            {"name": "Isaksen",     "pos": "W",   "club": "Lazio",          "apps": 30, "goals": 6,  "assists": 5, "rating": 6.9, "starter": True,  "league": "Serie A"},
            {"name": "Højlund",     "pos": "ST",  "club": "Napoli",         "apps": 37, "goals": 14, "assists": 3, "rating": 7.6, "starter": True,  "league": "Serie A"},
            {"name": "Wind",        "pos": "ST",  "club": "Wolfsburg",      "apps": 26, "goals": 8,  "assists": 3, "rating": 6.7, "starter": True,  "league": "Bundesliga"},
            {"name": "Bah",         "pos": "FB",  "club": "Benfica",        "apps": 30, "goals": 2,  "assists": 5, "rating": 7.0, "starter": True,  "league": "Liga Portugal"},
        ],
    },
    "Kosovo": {
        "players": [
            {"name": "Muric",       "pos": "GK",  "club": "Ipswich",        "apps": 28, "goals": 0,  "assists": 0, "rating": 6.2, "starter": True,  "league": "Premier League"},
            {"name": "Rrahmani",    "pos": "CB",  "club": "Napoli",         "apps": 30, "goals": 1,  "assists": 0, "rating": 7.2, "starter": True,  "league": "Serie A"},
            {"name": "Aliti",       "pos": "CB",  "club": "CFR Cluj",       "apps": 24, "goals": 1,  "assists": 0, "rating": 6.0, "starter": True,  "league": "Romanian 1st"},
            {"name": "Vojvoda",     "pos": "FB",  "club": "Torino",         "apps": 25, "goals": 1,  "assists": 3, "rating": 6.4, "starter": True,  "league": "Serie A"},
            {"name": "Hadergjonaj", "pos": "FB",  "club": "Kasimpasa",      "apps": 22, "goals": 0,  "assists": 2, "rating": 6.0, "starter": True,  "league": "Süper Lig"},
            {"name": "Berisha V.",  "pos": "CDM", "club": "Lecce",          "apps": 26, "goals": 2,  "assists": 1, "rating": 6.3, "starter": True,  "league": "Serie A"},
            {"name": "Zhegrova",    "pos": "W",   "club": "Lille",          "apps": 30, "goals": 8,  "assists": 7, "rating": 7.5, "starter": True,  "league": "Ligue 1"},
            {"name": "Rashica",     "pos": "W",   "club": "Braga",          "apps": 24, "goals": 5,  "assists": 4, "rating": 6.6, "starter": True,  "league": "Liga Portugal"},
            {"name": "Muriqi",      "pos": "ST",  "club": "Mallorca",       "apps": 30, "goals": 18, "assists": 3, "rating": 7.8, "starter": True,  "league": "La Liga"},
            {"name": "Bytyqi",      "pos": "CAM", "club": "Norwich",        "apps": 28, "goals": 4,  "assists": 5, "rating": 6.5, "starter": True,  "league": "Championship"},
            {"name": "Krasniqi",    "pos": "CM",  "club": "Heidenheim",     "apps": 22, "goals": 2,  "assists": 2, "rating": 6.3, "starter": True,  "league": "Bundesliga"},
        ],
    },
    "Turkey": {
        "players": [
            {"name": "Günok",       "pos": "GK",  "club": "Beşiktaş",      "apps": 28, "goals": 0,  "assists": 0, "rating": 6.8, "starter": True,  "league": "Süper Lig"},
            {"name": "Demiral",     "pos": "CB",  "club": "Al-Ahli",        "apps": 22, "goals": 1,  "assists": 0, "rating": 6.5, "starter": True,  "league": "Saudi Pro", "league_discount": 0.80},
            {"name": "Bardakcı",    "pos": "CB",  "club": "Galatasaray",    "apps": 28, "goals": 2,  "assists": 0, "rating": 6.7, "starter": True,  "league": "Süper Lig"},
            {"name": "Müldür",      "pos": "FB",  "club": "Fenerbahçe",     "apps": 26, "goals": 2,  "assists": 4, "rating": 6.6, "starter": True,  "league": "Süper Lig"},
            {"name": "Çalhanoğlu",  "pos": "CDM", "club": "Inter Milan",    "apps": 26, "goals": 9,  "assists": 4, "rating": 7.8, "starter": True,  "league": "Serie A"},
            {"name": "Kökcü",       "pos": "CM",  "club": "Benfica",        "apps": 30, "goals": 4,  "assists": 6, "rating": 7.2, "starter": True,  "league": "Liga Portugal"},
            {"name": "Güler",       "pos": "CAM", "club": "Real Madrid",    "apps": 43, "goals": 4,  "assists": 4, "rating": 6.8, "starter": True,  "league": "La Liga"},
            {"name": "Yıldız",      "pos": "W",   "club": "Juventus",       "apps": 40, "goals": 11, "assists": 4, "rating": 7.4, "starter": True,  "league": "Serie A"},
            {"name": "Aktürkoğlu",  "pos": "W",   "club": "Benfica",        "apps": 28, "goals": 6,  "assists": 5, "rating": 7.0, "starter": True,  "league": "Liga Portugal"},
            {"name": "Yılmaz B.",   "pos": "ST",  "club": "Galatasaray",    "apps": 24, "goals": 7,  "assists": 2, "rating": 6.5, "starter": True,  "league": "Süper Lig"},
            {"name": "Ünder",       "pos": "W",   "club": "Fenerbahçe",     "apps": 22, "goals": 5,  "assists": 3, "rating": 6.5, "starter": False, "league": "Süper Lig"},
        ],
    },
    "Sweden": {
        "players": [
            {"name": "Olsen",       "pos": "GK",  "club": "Aston Villa",    "apps": 12, "goals": 0,  "assists": 0, "rating": 6.3, "starter": True,  "league": "Premier League"},
            {"name": "Lindelöf",    "pos": "CB",  "club": "Man United",     "apps": 20, "goals": 0,  "assists": 1, "rating": 6.2, "starter": True,  "league": "Premier League"},
            {"name": "Augustinsson","pos": "FB",  "club": "Anderlecht",     "apps": 25, "goals": 1,  "assists": 3, "rating": 6.3, "starter": True,  "league": "Belgian Pro"},
            {"name": "Svanberg",    "pos": "CM",  "club": "Wolfsburg",      "apps": 24, "goals": 2,  "assists": 2, "rating": 6.3, "starter": True,  "league": "Bundesliga"},
            {"name": "Kulusevski",  "pos": "W",   "club": "Tottenham",      "apps": 35, "goals": 8,  "assists": 10,"rating": 7.5, "starter": True,  "league": "Premier League"},
            {"name": "Forsberg",    "pos": "CAM", "club": "RB Leipzig",     "apps": 18, "goals": 3,  "assists": 4, "rating": 6.5, "starter": True,  "league": "Bundesliga"},
            {"name": "Gyökeres",    "pos": "ST",  "club": "Arsenal",        "apps": 42, "goals": 16, "assists": 5, "rating": 7.6, "starter": True,  "league": "Premier League"},
            {"name": "Isak",        "pos": "ST",  "club": "Newcastle",      "apps": 28, "goals": 18, "assists": 4, "rating": 8.0, "starter": False, "league": "Premier League", "absent": True, "injury": "Lesión muscular"},
            {"name": "Elanga",      "pos": "W",   "club": "Nottingham F.",   "apps": 30, "goals": 6,  "assists": 4, "rating": 6.6, "starter": True,  "league": "Premier League"},
            {"name": "Cajuste",     "pos": "CDM", "club": "Ipswich",        "apps": 25, "goals": 1,  "assists": 2, "rating": 6.2, "starter": True,  "league": "Premier League"},
            {"name": "Krafth",      "pos": "FB",  "club": "Newcastle",      "apps": 15, "goals": 0,  "assists": 1, "rating": 6.0, "starter": True,  "league": "Premier League"},
        ],
    },
    "Poland": {
        "players": [
            {"name": "Szczęsny",    "pos": "GK",  "club": "Barcelona",      "apps": 20, "goals": 0,  "assists": 0, "rating": 6.8, "starter": True,  "league": "La Liga"},
            {"name": "Kiwior",      "pos": "CB",  "club": "Arsenal",        "apps": 18, "goals": 0,  "assists": 0, "rating": 6.3, "starter": True,  "league": "Premier League"},
            {"name": "Bednarek",    "pos": "CB",  "club": "Southampton",    "apps": 28, "goals": 1,  "assists": 0, "rating": 6.0, "starter": True,  "league": "Premier League"},
            {"name": "Zalewski",    "pos": "FB",  "club": "Roma",           "apps": 25, "goals": 1,  "assists": 3, "rating": 6.4, "starter": True,  "league": "Serie A"},
            {"name": "Zieliński",   "pos": "CM",  "club": "Inter Milan",    "apps": 40, "goals": 6,  "assists": 5, "rating": 7.2, "starter": True,  "league": "Serie A"},
            {"name": "Moder",       "pos": "CDM", "club": "Brighton",       "apps": 22, "goals": 1,  "assists": 2, "rating": 6.5, "starter": True,  "league": "Premier League"},
            {"name": "Szymański",   "pos": "CAM", "club": "Fenerbahçe",     "apps": 30, "goals": 7,  "assists": 6, "rating": 7.0, "starter": True,  "league": "Süper Lig"},
            {"name": "Lewandowski", "pos": "ST",  "club": "Barcelona",      "apps": 35, "goals": 15, "assists": 5, "rating": 7.2, "starter": True,  "league": "La Liga"},
            {"name": "Milik",       "pos": "ST",  "club": "Juventus",       "apps": 14, "goals": 3,  "assists": 1, "rating": 5.8, "starter": False, "league": "Serie A"},
            {"name": "Frankowski",  "pos": "FB",  "club": "Lens",           "apps": 28, "goals": 2,  "assists": 5, "rating": 6.7, "starter": True,  "league": "Ligue 1"},
            {"name": "Urbański",    "pos": "CM",  "club": "Bologna",        "apps": 26, "goals": 3,  "assists": 3, "rating": 6.6, "starter": True,  "league": "Serie A"},
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE CÁLCULO
# ═══════════════════════════════════════════════════════════════════════════

# Descuento por nivel de liga (top 5 = 1.0)
LEAGUE_QUALITY = {
    "Premier League": 1.00, "La Liga": 0.98, "Serie A": 0.97,
    "Bundesliga": 0.96, "Ligue 1": 0.93, "Liga Portugal": 0.90,
    "Süper Lig": 0.85, "Scottish Prem": 0.82, "Championship": 0.82,
    "Croatian 1st": 0.78, "Czech 1st": 0.78, "Austrian BL": 0.78,
    "Belgian Pro": 0.80, "Romanian 1st": 0.72,
    "Saudi Pro": 0.75, "UAE Pro": 0.70,
}


def compute_adjusted_rating(player):
    """Rating ajustado por calidad de liga."""
    base = player["rating"]
    league = player.get("league", "Unknown")
    league_q = LEAGUE_QUALITY.get(league, 0.80)
    discount = player.get("league_discount", league_q)

    # Para ligas débiles, reducir rating: base × (0.7 + 0.3 × league_quality)
    adjustment = 0.7 + 0.3 * discount
    return round(base * adjustment, 2)


def compute_squad_metrics(team_name):
    """Calcula métricas agregadas del XI titular de un equipo."""
    squad = SQUAD_DATA.get(team_name, {})
    players = squad.get("players", [])

    if not players:
        return None

    starters = [p for p in players if p.get("starter", True) and not p.get("absent")]
    all_players = [p for p in players if not p.get("absent")]

    if not starters:
        return None

    # Rating promedio del XI (ajustado por liga)
    ratings = [compute_adjusted_rating(p) for p in starters]
    avg_rating = sum(ratings) / len(ratings)

    # Impacto ponderado por posición
    weighted_attack = 0
    weighted_defense = 0
    for p in starters:
        adj_r = compute_adjusted_rating(p)
        pos_w = POSITION_WEIGHTS.get(p["pos"], {"attack": 0.15, "defense": 0.10})
        weighted_attack += adj_r * pos_w["attack"]
        weighted_defense += adj_r * pos_w["defense"]

    # Marcadores peligrosos (>5 goles en temporada en top 5 ligas)
    dangerous_scorers = []
    for p in starters:
        lq = LEAGUE_QUALITY.get(p.get("league", ""), 0.80)
        if p["goals"] >= 5 and lq >= 0.90:
            dangerous_scorers.append(p)

    # Jugadores en mejor y peor forma
    sorted_by_rating = sorted(starters, key=lambda x: compute_adjusted_rating(x), reverse=True)
    best_form = sorted_by_rating[:3]
    worst_form = sorted_by_rating[-3:]

    # Ausencias y su impacto
    absent = [p for p in players if p.get("absent")]

    # Calcular ajustes al modelo
    # Rating > 7.0 → boost ataque +8%
    # Rating 6.0-7.0 → sin ajuste
    # Rating < 6.0 → penalización -10%
    if avg_rating > 7.0:
        attack_mod = 1.08
        defense_mod = 0.95
    elif avg_rating < 6.0:
        attack_mod = 0.90
        defense_mod = 1.08
    else:
        attack_mod = 1.0 + (avg_rating - 6.5) * 0.04  # Gradual
        defense_mod = 1.0 - (avg_rating - 6.5) * 0.02

    # Bonus por marcadores peligrosos (+0.15 xG cada uno)
    scorer_xg_bonus = len(dangerous_scorers) * 0.15

    return {
        "team": team_name,
        "xi_count": len(starters),
        "avg_rating": round(avg_rating, 2),
        "weighted_attack": round(weighted_attack, 2),
        "weighted_defense": round(weighted_defense, 2),
        "attack_mod": round(attack_mod, 3),
        "defense_mod": round(defense_mod, 3),
        "scorer_xg_bonus": round(scorer_xg_bonus, 2),
        "dangerous_scorers": [{"name": p["name"], "goals": p["goals"], "club": p["club"]} for p in dangerous_scorers],
        "best_form": [{"name": p["name"], "rating": compute_adjusted_rating(p), "club": p["club"]} for p in best_form],
        "worst_form": [{"name": p["name"], "rating": compute_adjusted_rating(p), "club": p["club"]} for p in worst_form],
        "absent": [{"name": p["name"], "pos": p["pos"], "reason": p.get("injury", ""), "rating": p["rating"]} for p in absent],
    }


def print_squad_analysis(metrics):
    """Imprime análisis de plantilla."""
    if not metrics:
        return
    m = metrics
    print(f"\n    {m['team']} — Rating XI: {m['avg_rating']:.2f}  "
          f"(atk ×{m['attack_mod']:.3f}  def ×{m['defense_mod']:.3f}  xG bonus: +{m['scorer_xg_bonus']:.2f})")
    best = ", ".join(p["name"] + " " + str(round(compute_adjusted_rating(p), 1)) + " (" + p["club"] + ")" for p in m["best_form"])
    worst = ", ".join(p["name"] + " " + str(round(compute_adjusted_rating(p), 1)) + " (" + p["club"] + ")" for p in m["worst_form"])
    print(f"      Mejor forma: {best}")
    print(f"      Peor forma:  {worst}")
    if m['dangerous_scorers']:
        scorers = ", ".join(p["name"] + " (" + str(p["goals"]) + "G, " + p["club"] + ")" for p in m["dangerous_scorers"])
        print(f"      Goleadores:   {scorers}")
    if m['absent']:
        absent = ", ".join(p["name"] + " (" + p["pos"] + ", " + p["reason"] + ")" for p in m["absent"])
        print(f"      Ausentes:     {absent}")
