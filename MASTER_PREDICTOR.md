# MASTER PREDICTOR - Contexto Maestro del Sistema de Prediccion de Apuestas

> **Proyecto:** predictor-apuestas
> **Ubicacion:** `/home/swatnemesiz/predictor-apuestas/`
> **Objetivo:** Sistema autonomo de prediccion de resultados de futbol con multiples modelos estadisticos
> **Evento actual:** Playoffs clasificatorios UEFA para el Mundial 2026 (31 marzo 2026)
> **Ultima actualizacion:** 2026-04-01

---

## 1. ESTRUCTURA DE ARCHIVOS

```
predictor-apuestas/
|
|-- MODELOS DE PREDICCION
|   |-- predict.py                 # v1: Poisson basico
|   |-- predict_v3.py              # v3: Ensemble (Poisson + Dixon-Coles + ELO)
|   |-- predict_v4.py              # v4: v3 + Contexto competitivo y psicologico
|   |-- predict_v5.py              # v5: v4 + Datos reales de plantilla/jugadores
|
|-- MODULOS AUXILIARES
|   |-- player_form.py             # Datos de plantilla: 8 equipos x 11 jugadores
|   |-- fetch_stats.py             # Descarga stats de football-data.org
|   |-- fetch_corners.py           # Descarga corners de API-Football
|   |-- scrape_national_teams.py   # Scraping de partidos desde Wikipedia
|
|-- DATOS (JSON)
|   |-- national_matches.json      # 2,745 lineas - Partidos selecciones (2024-2026)
|   |-- team_stats.json            # 4,510 lineas - Estadisticas por liga
|   |-- corner_stats.json          # 616 lineas - Estadisticas de corners
|   |-- corners_matches.json       # 771 lineas - Corners por partido
|   |-- data_matches.json          # 47,509 lineas - Datos crudos de ligas
|
|-- SALIDAS DE PREDICCION (JSON)
|   |-- predictions.json           # Salida v1
|   |-- predictions_v3.json        # Salida v3
|   |-- predictions_v4.json        # Salida v4
|   |-- predictions_v5.json        # Salida v5 (973 lineas, mas completa)
|
|-- CONFIGURACION
|   |-- .env                       # API keys (NO commitear)
|   |-- .env.example               # Plantilla de keys
|   |-- .gitignore                 # Exclusiones de git
|   |-- .claude/settings.local.json # Permisos Claude Code
```

---

## 2. APIs CONECTADAS Y CREDENCIALES

### 2.1 football-data.org (v4)
- **Base URL:** `https://api.football-data.org/v4`
- **Key:** `dd3d5d1c1bb940ddb78096ea7abd6db7`
- **Plan:** Free (10 requests/minuto)
- **Uso:** Estadisticas de equipos, resultados de partidos
- **Competiciones:** PL, BL1, SA, PD, FL1, CL, EC, WC
- **Rango:** Ultimos 730 dias
- **Archivo:** `fetch_stats.py`
- **Registro:** https://www.football-data.org/client/register

### 2.2 API-Football (v3)
- **Base URL:** `https://v3.football.api-sports.io`
- **Key:** `a1572eeacc1837fb47d69dba3f1958ae`
- **Plan:** Free (100 requests/dia)
- **Uso:** Estadisticas de corners por partido
- **Archivo:** `fetch_corners.py`
- **Registro:** https://dashboard.api-football.com/register

### 2.3 Wikipedia (Scraping)
- **Uso:** Resultados de partidos de selecciones nacionales
- **Archivo:** `scrape_national_teams.py`
- **Sin key** (scraping directo de tablas HTML)

---

## 3. MODELOS IMPLEMENTADOS

### 3.1 Modelo v1 - Poisson Basico (`predict.py`)

**Concepto:** Distribucion de Poisson para estimar probabilidad de cada marcador posible.

**Variables principales:**
| Variable | Valor | Descripcion |
|----------|-------|-------------|
| `MAX_GOALS` | 8 | Maximo goles en la distribucion |
| `FORM_WEIGHT` | 0.20 | Peso del factor de forma reciente |
| `RECENCY_WEIGHT` | 0.10 | Bonus/penalizacion por antiguedad |

**Formulas:**

```
Poisson PMF: P(k) = (lambda^k * e^-lambda) / k!

lambda_home = (attack_rating_home / avg_gf) * (defense_rating_away / avg_ga) * home_advantage
lambda_away = (attack_rating_away / avg_gf) * (defense_rating_home / avg_ga)

P(marcador h-a) = P_poisson(h, lambda_home) * P_poisson(a, lambda_away)
```

**Funciones clave:**
- `poisson_pmf(k, lam)` - Funcion de masa de probabilidad
- `prob_to_odds(prob_pct)` - Convierte probabilidad % a cuotas decimales
- `predict_corners(home, away, stats, avg_total=10.5)` - Prediccion de corners
- `compute_national_stats(matches)` - Estadisticas por equipo
- `compute_league_averages(stats)` - Promedios de normalizacion
- `get_team_ratings(team, stats, avg_gf, avg_ga)` - Ratings normalizados

**Mercados:**
- 1X2 (Local / Empate / Visitante)
- BTTS (Ambos marcan Si/No)
- Over/Under 1.5 y 2.5 goles
- Corners Over 8.5, 9.5, 10.5

---

### 3.2 Modelo v2 - (No implementado como archivo separado)

> Nota: No existe `predict_v2.py`. La evolucion fue v1 -> v3 directamente.

---

### 3.3 Modelo v3 - Ensemble (`predict_v3.py`)

**Concepto:** Combina 3 sub-modelos con pesos fijos + decaimiento temporal + ajustes por ausencias.

**Pesos del Ensemble:**
| Sub-modelo | Peso | Funcion |
|------------|------|---------|
| Poisson | 0.40 (40%) | Prediccion basada en frecuencia |
| Dixon-Coles | 0.30 (30%) | Correccion para marcadores bajos |
| ELO | 0.30 (30%) | Prediccion basada en fuerza relativa |

**Constantes:**
```python
W_POISSON = 0.40
W_DIXON_COLES = 0.30
W_ELO = 0.30
DC_RHO = -0.13              # Parametro de dependencia Dixon-Coles
DECAY_HALF_LIFE = 365        # Dias (partido de 1 ano = 50% peso)
REFERENCE_DATE = "2026-03-31"
ELO_INITIAL = 1500
ELO_K = 40
ELO_HOME_ADVANTAGE = 100     # Puntos ELO de ventaja local
```

**Dixon-Coles - Correccion para marcadores dependientes:**
```
tau(0,0) = 1 - rho * lambda * mu
tau(1,0) = 1 + rho * mu
tau(0,1) = 1 + rho * lambda
tau(1,1) = 1 - rho
(donde rho = DC_RHO = -0.13)
```
Esto ajusta las probabilidades de 0-0, 1-0, 0-1 y 1-1 que en Poisson puro no captura la correlacion entre goles.

**Decaimiento Temporal:**
```
peso = exp(-decay_rate * dias_desde_partido)
decay_rate = ln(2) / DECAY_HALF_LIFE

Ejemplos:
  Partido de hace 1 mes  -> peso ~99%
  Partido de hace 6 meses -> peso ~71%
  Partido de hace 1 ano  -> peso ~50%
  Partido de hace 2 anos -> peso ~25%
```

**Sistema ELO:**
```
P_esperada = 1 / (1 + 10^((elo_rival - elo_propio - home_adv) / 400))
nuevo_elo = elo_anterior + K * (resultado - P_esperada) * multiplicador_goles
```

**Ajustes por Ausencias (hardcoded):**
| Equipo | Jugador | Razon | Ataque | Defensa |
|--------|---------|-------|--------|---------|
| Italy | Barella | Lesion | -0.15 | -0.05 |
| Bosnia | Dzeko | Retirado | -0.25 | 0 |
| Sweden | Isak | Lesion muscular | -0.30 | 0 |
| Poland | Lewandowski | Edad (37) | -0.10 | 0 |

**Factores de Motivacion (boost al ataque local):**
| Equipo | Factor | Razon |
|--------|--------|-------|
| Kosovo | 1.15x | Historica primera clasificacion |
| Bosnia | 1.10x | Solo 1 Mundial (2014) |
| Turkey | 1.08x | 24 anos sin Mundial |
| Sweden | 1.05x | No fue en 2022 |

**Corners v3:**
```
wing_play_index = corners_favor / 5.0
```

---

### 3.4 Modelo v4 - Contexto Competitivo (`predict_v4.py`)

**Concepto:** Agrega contexto del tipo de partido, nivel del torneo, historial mundialista y presion psicologica.

**Importa todo de v3** + agrega capas contextuales.

#### 3.4.1 Clasificacion del Tipo de Partido

| Tipo | Factor | Descripcion |
|------|--------|-------------|
| `FRIENDLY` | 1.00x | Amistoso |
| `QUALIFIER_NORMAL` | 1.05x | Fase de grupos normal |
| `QUALIFIER_DECISIVE` | 1.10x | Jornada decisiva |
| `PLAYOFF_FIRST_LEG` | 1.15x | Ida de playoff |
| `PLAYOFF_SECOND_ADVANTAGE` | 0.90x | Vuelta con ventaja |
| `PLAYOFF_SECOND_BEHIND` | 1.20x | Vuelta en desventaja |
| `FINAL_DIRECT` | **1.25x** | **Final directa (ESTE torneo)** |

#### 3.4.2 Niveles de Torneo

| Nivel | Torneo | Draw Boost | Goals Mod |
|-------|--------|------------|-----------|
| 1 | Amistoso FIFA | 0.00 | 1.00 |
| 2 | Nations League Grupo | 0.00 | 1.00 |
| 3 | Nations League Final4 | 0.02 | 0.95 |
| 4 | WCQ Grupo | 0.00 | 0.98 |
| **5** | **WCQ Playoff** | **0.04** | **0.92** |
| 6 | Euro Grupo | 0.02 | 0.95 |
| 7 | Euro Knockout | 0.05 | 0.90 |
| 8 | Mundial Final | 0.06 | 0.88 |

#### 3.4.3 Historial Mundialista y Presion Psicologica

| Equipo | Mundiales | Consecutivos sin ir | Tipo presion | Ataque mod | Defensa mod |
|--------|-----------|---------------------|--------------|------------|-------------|
| Kosovo | 0 (NUNCA) | N/A | `historic` | 1.12x | 0.97x |
| Turkey | 3 | 5 (2006-2022) | `desperate` | 1.10x | 1.05x (fragilidad) |
| Bosnia | 1 (2014) | 2 | `hungry` | 1.08x | 0.98x |
| Sweden | 5 | 1 (2022) | `motivated` | 1.05x | 1.00x |
| Czechia | 1 (2006) | 4 (2010-2022) | `moderate` | 1.03x | 1.00x |
| Italy | 18 (tetracampeon) | 2 (2018, 2022) | `negative` (trauma) | 0.92x | 1.04x |
| Denmark | 6 | 0 (fue en 2022) | `relaxed` | 1.00x | 1.00x |
| Poland | 9 | 0 (fue en 2022) | `relaxed` | 1.00x | 1.00x |

**Formula de presion negativa (Italia):**
```
attack_penalty = 1.0 - (0.02 * mundiales_consecutivos_perdidos)
Italy: 1.0 - (0.02 * 2) = 0.96 -> luego * 0.96 = 0.92 con factor adicional
```

#### 3.4.4 Tension Tactica (Final Directa)

```python
tactical_tension = 1.15      # Mas faltas, paradas, interrupciones
corners_tension_mod = 1.08   # Presion ofensiva forzada -> mas corners
goals_modifier *= 0.95       # Conservadurismo inicial

# goals_modifier final = tournament.goals_mod * 0.95
# Para WCQ Playoff: 0.92 * 0.95 = 0.874
```

#### 3.4.5 Narrativa Contextual

Cada equipo tiene un campo `context` con analisis narrativo en espanol sobre su situacion psicologica, ejemplo:
```
Kosovo: "NUNCA han ido a un Mundial. Momento historico para todo el pais.
         Motivacion desbordante, el estadio sera un infierno."
Italy:  "Trauma de no ir en 2018 y 2022 pesa. Visitante en eliminatoria
         directa. Presion extrema negativa."
```

---

### 3.5 Modelo v5 - Forma de Jugadores (`predict_v5.py` + `player_form.py`)

**Concepto:** Integra datos reales de plantilla (11 titulares por equipo) con ratings individuales, goles, posicion y calidad de liga.

**Importa todo de v4** + modulo `player_form.py`.

#### 3.5.1 Pesos por Posicion (`POSITION_WEIGHTS`)

| Posicion | Peso Ataque | Peso Defensa |
|----------|-------------|--------------|
| GK | 0.00 | 0.15 |
| CB | 0.05 | 0.20 |
| FB | 0.10 | 0.15 |
| CDM | 0.10 | 0.20 |
| CM | 0.15 | 0.15 |
| CAM | 0.25 | 0.05 |
| W (extremo) | 0.25 | 0.05 |
| ST (delantero) | 0.30 | 0.00 |

#### 3.5.2 Calidad de Liga (`LEAGUE_QUALITY`)

| Liga | Factor |
|------|--------|
| Premier League | 1.00 |
| La Liga | 0.98 |
| Serie A | 0.97 |
| Bundesliga | 0.96 |
| Ligue 1 | 0.93 |
| Liga Portugal | 0.90 |
| Super Lig (Turquia) | 0.85 |
| Championship | 0.82 |
| Saudi Pro | 0.75 |
| Romanian Liga | 0.72 |
| UAE Pro | 0.70 |

#### 3.5.3 Datos de Plantilla (`SQUAD_DATA`)

8 equipos x 11 jugadores. Cada jugador tiene:
```python
{
    "name": "Muriqi",
    "position": "ST",
    "club": "Mallorca",
    "league": "La Liga",
    "apps": 30,          # Apariciones en temporada
    "goals": 18,         # Goles
    "assists": 4,        # Asistencias
    "rating": 7.2,       # Rating (escala 1-10)
    "starter": True,     # Titular habitual
    "absent": False,     # Ausente para el partido
    "injury": None,      # Razon de ausencia
    "league_discount": 0.98  # Factor de liga
}
```

**Goleadores Peligrosos por Equipo:**

| Equipo | Goleador | Goles | Club | Liga |
|--------|----------|-------|------|------|
| Kosovo | **Muriqi** | **18** | Mallorca | La Liga |
| Italy | Retegui | 18 | Al-Nassr | Saudi Pro |
| Italy | Kean | 9 | Fiorentina | Serie A |
| Sweden | Gyokeres | 16 | Sporting | Liga Portugal |
| Sweden | ~~Isak~~ | ~~18~~ | Newcastle | PL (**LESIONADO**) |
| Poland | Lewandowski | 15 | Barcelona | La Liga |
| Turkey | Yildiz | 11 | Juventus | Serie A |
| Turkey | Calhanoglu | 9 | Inter | Serie A |
| Denmark | Hojlund | 14 | Man United | PL |
| Denmark | Wind | 8 | Wolfsburg | Bundesliga |
| Czechia | Schick | 9 | Leverkusen | Bundesliga |
| Bosnia | Demirovic | 12 | Stuttgart | Bundesliga |

#### 3.5.4 Calculo del Modificador de Plantilla

```python
def compute_squad_metrics(team_name):
    # 1. Rating promedio del XI
    avg_rating = sum(player.rating for p in xi) / len(xi)

    # 2. Ataque/defensa ponderados por posicion
    weighted_attack = sum(p.rating * POSITION_WEIGHTS[p.pos].attack * LEAGUE_QUALITY[p.league])
    weighted_defense = sum(p.rating * POSITION_WEIGHTS[p.pos].defense * LEAGUE_QUALITY[p.league])

    # 3. Modificadores basados en rating promedio
    if avg_rating > 7.0:
        attack_mod = 1.08
        defense_mod = 0.95
    elif avg_rating >= 6.0:
        # Gradual: +/- 0.04 por punto de rating
        attack_mod = 1.0 + (avg_rating - 6.5) * 0.04
        defense_mod = 1.0 - (avg_rating - 6.5) * 0.04
    else:
        attack_mod = 0.90
        defense_mod = 1.08

    # 4. Bonus por goleadores peligrosos
    scorer_xg_bonus = 0.0
    for player in xi:
        if player.goals >= 5 and player.league in TOP_5:
            scorer_xg_bonus += 0.15  # +0.15 xG por goleador

    return {
        "team", "xi_count", "avg_rating",
        "weighted_attack", "weighted_defense",
        "attack_mod", "defense_mod",
        "scorer_xg_bonus",
        "dangerous_scorers", "best_form", "worst_form", "absent"
    }
```

#### 3.5.5 Integracion en la Prediccion

```python
# En predict_v5.py:
h_squad = compute_squad_metrics(home_team)
a_squad = compute_squad_metrics(away_team)

# Aplicar modificadores al lambda
lambda_home *= h_squad["attack_mod"]
lambda_home += h_squad["scorer_xg_bonus"]
lambda_away *= a_squad["attack_mod"]
lambda_away += a_squad["scorer_xg_bonus"]
```

---

## 4. PIPELINE COMPLETO DE PREDICCION

### 4.1 Flujo de Datos

```
[APIs Externas]                    [Scraping]
     |                                  |
     v                                  v
fetch_stats.py -----> team_stats.json   scrape_national_teams.py --> national_matches.json
fetch_corners.py ---> corner_stats.json
                      corners_matches.json
                                        |
                    [Datos Consolidados] |
                           |            |
                           v            v
                    +-------------------+
                    | MODELOS (v1-v5)   |
                    |                   |
                    | 1. Cargar datos   |
                    | 2. Calcular ELO   |
                    | 3. Calcular stats |
                    | 4. Aplicar decay  |
                    | 5. Ensemble       |
                    | 6. Contexto       |
                    | 7. Jugadores      |
                    +-------------------+
                           |
                           v
                    predictions_vX.json
```

### 4.2 Cadena de Calculo (v5 completa)

```
1. Cargar national_matches.json + corner_stats.json
2. Calcular ELO para cada equipo (K=40, home_adv=100)
3. Calcular stats por equipo (goles a favor/contra, local/visitante)
4. Aplicar decaimiento temporal (half-life=365 dias)
5. Calcular lambda_home y lambda_away (Poisson)
6. Aplicar correccion Dixon-Coles (rho=-0.13) para marcadores bajos
7. Calcular probabilidad ELO
8. Ensemble: 40% Poisson + 30% Dixon-Coles + 30% ELO
9. Aplicar ausencias (Isak -0.30, Barella -0.15, etc.)
10. Aplicar motivacion (Kosovo 1.15x, Bosnia 1.10x, etc.)
11. Aplicar contexto de torneo (draw_boost +0.04, goals_mod *0.92)
12. Aplicar tipo de partido (FINAL_DIRECT *1.25)
13. Aplicar tension tactica (corners *1.08, goals *0.95)
14. Aplicar presion mundialista (Kosovo 1.12x, Italy 0.92x, etc.)
15. Aplicar forma de plantilla (squad attack/defense mods)
16. Aplicar bonus goleadores peligrosos (+0.15 xG por goleador top)
17. Generar matriz de probabilidad de marcadores (0-0 a 8-8)
18. Calcular mercados: 1X2, BTTS, O/U 1.5, O/U 2.5, Corners
19. Exportar a predictions_v5.json
```

---

## 5. FORMATO DE SALIDA (predictions_v5.json)

Cada partido genera un objeto con esta estructura:

```json
{
  "home_team": "Bosnia-Herzegovina",
  "away_team": "Italy",
  "date": "2026-03-31",

  "lambda_home": 1.234,
  "lambda_away": 1.567,
  "exp_home_goals": 1.23,
  "exp_away_goals": 1.57,

  "p_home_win": 38.5,
  "p_draw": 26.7,
  "p_away_win": 34.8,

  "odds_home": 2.60,
  "odds_draw": 3.75,
  "odds_away": 2.87,

  "p_btts_yes": 52.3,
  "p_btts_no": 47.7,
  "p_over_25": 48.2,
  "p_under_25": 51.8,
  "p_over_15": 72.4,

  "top_scores": [["1-1", 18.5], ["1-0", 14.2], ["0-1", 12.8]],

  "corners": {
    "exp_total_corners": 10.5,
    "p_over_10_5": 48.3,
    "p_over_9_5": 62.1,
    "p_over_8_5": 74.5
  },

  "elo_home": 1572,
  "elo_away": 1619,

  "sub_poisson": { "1": 0.385, "X": 0.267, "2": 0.348 },
  "sub_dixon_coles": { "1": 0.392, "X": 0.271, "2": 0.337 },
  "sub_elo": { "1": 0.378, "X": 0.263, "2": 0.359 },

  "home_pressure": { "attack_mod": 1.08, "defense_mod": 0.98, "label": "HAMBRIENTO" },
  "away_pressure": { "attack_mod": 0.96, "defense_mod": 1.04, "label": "PRESION NEGATIVA" },
  "home_wc_context": "Solo 1 Mundial en su historia...",
  "away_wc_context": "Trauma de no ir en 2018 y 2022...",

  "context": {
    "match_type": { "factor": 1.25, "label": "Final directa" },
    "tournament": { "level": 5, "draw_boost": 0.04, "goals_mod": 0.92 },
    "goals_modifier": 0.874,
    "tactical_tension": 1.15,
    "corners_tension_mod": 1.08
  },

  "home_squad": {
    "team": "Bosnia-Herzegovina",
    "xi_count": 10,
    "avg_rating": 6.31,
    "weighted_attack": 9.02,
    "weighted_defense": 7.72,
    "attack_mod": 0.993,
    "defense_mod": 1.004,
    "scorer_xg_bonus": 0.3,
    "dangerous_scorers": [
      { "name": "Demirovic", "goals": 12, "club": "Stuttgart" }
    ],
    "absent": [
      { "name": "Dzeko", "pos": "ST", "reason": "Retirado seleccion" }
    ]
  },
  "away_squad": { "..." : "..." },

  "context_narrative": "FINAL DIRECTA (nivel 5/8) -- Bosnia: HAMBRIENTO | Italy: PRESION NEGATIVA"
}
```

---

## 6. PARTIDOS OBJETIVO

| # | Local | Visitante | Fecha | Contexto |
|---|-------|-----------|-------|----------|
| 1 | Bosnia-Herzegovina | Italy | 31/03/2026 | Bosnia hambriento (1 WC) vs Italia trauma (perdio 2018+2022) |
| 2 | Czechia | Denmark | 31/03/2026 | Chequia 20 anos sin WC vs Dinamarca relajada |
| 3 | Kosovo | Turkey | 31/03/2026 | Kosovo historico (0 WC) vs Turquia desesperada (24 anos) |
| 4 | Sweden | Poland | 31/03/2026 | Suecia sin Isak vs Polonia con Lewandowski (37) |

---

## 7. IDs DE EQUIPOS EN API-FOOTBALL

```python
TARGET_TEAMS = {
    1113: "Bosnia-Herzegovina",
    768:  "Italy",
    770:  "Czechia",
    21:   "Denmark",
    1111: "Kosovo",
    777:  "Turkey",
    5:    "Sweden",
    24:   "Poland",
}
```

**Competiciones:**
- WCQ UEFA: league 32, season 2024
- Nations League: league 5, seasons 2024 y 2022

---

## 8. EJECUCION

```bash
# 1. Recolectar datos (solo si necesitas actualizar)
cd /home/swatnemesiz/predictor-apuestas
python3 fetch_stats.py           # -> team_stats.json, data_matches.json
python3 fetch_corners.py         # -> corner_stats.json, corners_matches.json
python3 scrape_national_teams.py # -> national_matches.json

# 2. Ejecutar predicciones
python3 predict.py               # -> predictions.json (v1)
python3 predict_v3.py            # -> predictions_v3.json
python3 predict_v4.py            # -> predictions_v4.json
python3 predict_v5.py            # -> predictions_v5.json (mas completa)
```

---

## 9. RESUMEN DE EVOLUCION DE MODELOS

| Version | Archivo | Tecnicas | Precision vs v1 |
|---------|---------|----------|-----------------|
| **v1** | predict.py | Poisson puro | Base |
| **v2** | (no existe) | - | - |
| **v3** | predict_v3.py | Ensemble (Poisson 40% + Dixon-Coles 30% + ELO 30%) + decay temporal + ausencias + motivacion | Mejor calibracion en empates y marcadores bajos |
| **v4** | predict_v4.py | v3 + contexto competitivo + niveles de torneo + presion mundialista + tension tactica | Captura dinamicas psicologicas |
| **v5** | predict_v5.py | v4 + datos reales de plantilla + pesos por posicion + calidad de liga + bonus goleadores | Modelo mas granular y completo |

---

## 10. PENDIENTES Y PROXIMOS PASOS

- [ ] Modelo v6: Integrar clima, arbitro, historial directo H2H
- [ ] Modelo v7: Machine Learning (Random Forest / XGBoost) con features de v1-v5
- [ ] Dashboard web para visualizar predicciones en tiempo real
- [ ] Sistema de backtesting con partidos historicos para medir precision
- [ ] Alertas automaticas cuando las cuotas de casas de apuestas difieren >10% de la prediccion (value bets)
- [ ] Expansion a mas competiciones (Copa America, AFC, CAF)
- [ ] API propia para servir predicciones
- [ ] Integracion con Telegram bot para notificaciones

---

> **NOTA DE SEGURIDAD:** Las API keys estan en `.env` y NO deben commitearse a repositorios publicos. El `.gitignore` ya las excluye.
