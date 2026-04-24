"""
SCHEDULER.PY — Tareas programadas en background para NEME BET
════════════════════════════════════════════════════════════
Usa APScheduler para ejecutar en background dentro de gunicorn.
- 08:00 AM: Scraping partidos del dia
- 09:00 AM: Analisis automatico
- Cada 6h: Captura de resultados para autoaprendizaje
"""

import os
import sys
import json
import atexit
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def init_scheduler(app):
    """Inicializa el scheduler dentro de la app Flask."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        print("[SCHEDULER] APScheduler no disponible, tareas manuales")
        return None

    scheduler = BackgroundScheduler(daemon=True)

    # 8:00 AM — Scraping de partidos
    scheduler.add_job(
        func=job_scrape,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_scrape",
        name="Scraping diario BeSoccer",
        replace_existing=True,
    )

    # 9:00 AM — Analisis automatico
    scheduler.add_job(
        func=job_analyze,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_analyze",
        name="Analisis diario automatico",
        replace_existing=True,
    )

    # Cada 5 minutos — Actualizar cache de partidos (ejecutar inmediatamente al arrancar)
    scheduler.add_job(
        func=job_update_matches,
        trigger=IntervalTrigger(minutes=5),
        id="scanner_partidos",
        name="Scanner partidos cada 5 min",
        replace_existing=True,
        next_run_time=datetime.now(),
    )

    # Cada 6 horas — Captura de resultados
    scheduler.add_job(
        func=job_check_results,
        trigger=IntervalTrigger(hours=6),
        id="check_results",
        name="Captura resultados automatica",
        replace_existing=True,
    )

    # 3:00 AM — Backup diario + integridad
    scheduler.add_job(
        func=job_backup,
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_backup",
        name="Backup diario + verificacion integridad",
        replace_existing=True,
    )

    # Cada 3 horas — Generar picks frescos con Claude
    scheduler.add_job(
        func=job_generar_picks,
        trigger=IntervalTrigger(hours=3),
        id="auto_picks",
        name="Auto-picks NEMEBET cada 3h",
        replace_existing=True,
        next_run_time=datetime.now(),
    )

    scheduler.start()
    atexit.register(scheduler.shutdown)

    print("[SCHEDULER] Tareas programadas:")
    for job in scheduler.get_jobs():
        print(f"  - {job.name}: {job.trigger}")

    return scheduler


def job_update_matches():
    """Tarea: actualizar cache de partidos cada 5 min."""
    try:
        from featured_matches import fetch_partidos
        result = fetch_partidos(force=True)
        _log_job("scanner", f"{result.get('total', 0)} partidos ({result.get('en_vivo', 0)} live)")
    except Exception as e:
        _log_job("scanner", f"ERROR: {e}")


def job_scrape():
    """Tarea: scraping de partidos del dia."""
    print(f"\n[JOB] Scraping {datetime.now()}")
    try:
        from besoccer_scraper import scrape_today
        result = scrape_today()
        if result:
            _log_job("scrape", f"{result['relevant']} partidos relevantes")
    except Exception as e:
        print(f"[JOB ERROR] scrape: {e}")
        _log_job("scrape", f"ERROR: {e}")


def job_analyze():
    """Tarea: analisis automatico."""
    print(f"\n[JOB] Analisis {datetime.now()}")
    try:
        from auto_analyze import analyze_today
        result = analyze_today()
        if result:
            _log_job("analyze", f"{result['total_picks']} picks ({len(result['high_confidence_picks'])} high)")

            # Trigger notifications for high picks
            if result["high_confidence_picks"]:
                _notify_picks(result["high_confidence_picks"])
    except Exception as e:
        print(f"[JOB ERROR] analyze: {e}")
        _log_job("analyze", f"ERROR: {e}")


def job_backup():
    """Tarea: backup diario + verificacion de integridad."""
    print(f"\n[JOB] Backup {datetime.now()}")
    try:
        from security import create_backup, verify_data_integrity
        corrupted = verify_data_integrity()
        if corrupted:
            _log_job("backup", f"CORRUPTION DETECTED: {corrupted} -> restored from backup")
        path = create_backup()
        _log_job("backup", f"Created: {os.path.basename(path)}")
    except Exception as e:
        print(f"[JOB ERROR] backup: {e}")
        _log_job("backup", f"ERROR: {e}")


def job_check_results():
    """Tarea: captura automatica de resultados."""
    print(f"\n[JOB] Check results {datetime.now()}")
    try:
        from calibration import check_pending_results
        updated = check_pending_results()
        _log_job("check_results", f"{updated} resultados capturados")
    except Exception as e:
        print(f"[JOB ERROR] check_results: {e}")
        _log_job("check_results", f"ERROR: {e}")


def _notify_picks(picks):
    """Envia notificaciones push para picks de alta confianza."""
    try:
        from data_dir import data_path as _dp2
        subs_path = _dp2("push_subscriptions.json")
        if not os.path.exists(subs_path):
            return

        with open(subs_path, encoding="utf-8") as f:
            subscriptions = json.load(f)

        if not subscriptions:
            return

        from push_notify import send_push
        for pick in picks[:3]:
            payload = {
                "title": f"NEME BET - Pick {pick['prob']}%",
                "body": f"{pick['match']} - {pick['bet']}",
                "tag": "nemebet-pick",
                "url": "/picks",
            }
            for sub in subscriptions:
                try:
                    send_push(sub, payload)
                except Exception:
                    pass
    except Exception:
        pass


def _log_job(name, message):
    """Log de jobs ejecutados."""
    from data_dir import data_path as _dp
    log_path = _dp("scheduler_log.json")
    logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append({
        "job": name,
        "time": datetime.now().isoformat(),
        "message": message,
    })
    logs = logs[-50:]  # Keep last 50

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def job_generar_picks():
    """Genera picks frescos con Claude + partidos reales cada 3h."""
    print(f"\n[JOB-PICKS] Generando picks {datetime.now()}")
    try:
        import urllib.request, json, os
        from datetime import datetime as dt

        # Obtener partidos de football-data.org
        key = os.environ.get('FOOTBALL_DATA_API_KEY', 'dd3d5d1c1bb940ddb78096ea7abd6db7')
        hoy = dt.now().strftime('%Y-%m-%d')
        url = f'https://api.football-data.org/v4/matches?dateFrom={hoy}&dateTo={hoy}'
        req = urllib.request.Request(url)
        req.add_header('X-Auth-Token', key)
        req.add_header('User-Agent', 'NEMEBET/1.0')

        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode())

        partidos = raw.get('matches', [])

        # Si no hay partidos de football-data, usar API-Football
        if not partidos:
            key2 = os.environ.get('API_FOOTBALL_KEY', '')
            if key2:
                url2 = f'https://v3.football.api-sports.io/fixtures?date={hoy}'
                req2 = urllib.request.Request(url2)
                req2.add_header('x-apisports-key', key2)
                req2.add_header('User-Agent', 'Mozilla/5.0')
                with urllib.request.urlopen(req2, timeout=30) as r2:
                    raw2 = json.loads(r2.read().decode())
                for f in raw2.get('response', [])[:15]:
                    partidos.append({
                        'homeTeam': {'name': f['teams']['home']['name']},
                        'awayTeam': {'name': f['teams']['away']['name']},
                        'competition': {'name': f['league']['name']},
                        'utcDate': f['fixture']['date'],
                        'status': f['fixture']['status']['short']
                    })

        if not partidos:
            _log_job("picks", "0 partidos disponibles hoy")
            return

        # Filtrar solo partidos proximos o en juego
        proximos = []
        for p in partidos[:20]:
            estado = p.get('status', '')
            nombre_estado = estado if isinstance(estado, str) else estado.get('short', '')
            if nombre_estado not in ['FT', 'AET', 'PEN', 'CANC', 'PST', 'ABD']:
                home = p.get('homeTeam', {}).get('name', p.get('home', ''))
                away = p.get('awayTeam', {}).get('name', p.get('away', ''))
                liga = p.get('competition', {}).get('name', p.get('league', ''))
                hora = p.get('utcDate', '')[:16].replace('T', ' ') if p.get('utcDate') else ''
                proximos.append(f"- {home} vs {away} ({liga}, {hora} UTC)")

        if not proximos:
            _log_job("picks", "Solo partidos terminados hoy")
            return

        lista = chr(10).join(proximos)

        # Prompt NEMEBET v5
        prompt = f"""Eres NEMEBET v5, experto en pronosticos deportivos. Hoy es {hoy}.

PARTIDOS DISPONIBLES:
{lista}

REGLAS OBLIGATORIAS:
1. Solo picks con probabilidad real >= 63% y valor matematico >= +8%
2. Calcular valor: (prob_real x cuota) - 1 > 0.08
3. BTTS mas seguro que Over 2.5 en partidos europeos
4. Si visitante juega en bloque bajo -> apostar corners local, no goles
5. H2H reciente es el indicador mas confiable
6. Cuotas entre 1.65 y 2.50 = zona de valor optimo
7. NUNCA cuotas menores a 1.40
8. Bajas de mediocampo impactan mas que bajas de ataque
9. Importancia del partido multiplica la motivacion
10. Partido sin nada en juego = omitir

Responde SOLO JSON sin markdown:
{{
  "fecha": "{hoy}",
  "generado": "{dt.now().isoformat()}",
  "high_confidence_picks": [
    {{
      "id": "liga_local_visit",
      "local": "Local",
      "visitante": "Visitante",
      "match": "Local vs Visitante",
      "liga": "Liga",
      "hora": "HH:MM",
      "confianza": 70,
      "prob": 70,
      "mercado": "Under 2.5 Goles",
      "bet": "Under 2.5 Goles",
      "cuota_referencia": 1.75,
      "odds": 1.75,
      "edge": 22,
      "justificacion": "H2H Under en 4/5. Visitante defensivo. Valor: (0.70x1.75)-1=+22%",
      "importancia": "descripcion importancia",
      "bajas_consideradas": "bajas conocidas",
      "estado": "pendiente",
      "recomendado": true,
      "tipo": "goles"
    }}
  ],
  "medium_confidence_picks": [],
  "picks_corners": [],
  "picks_remates": []
}}"""

        anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not anthropic_key:
            _log_job("picks", "Sin ANTHROPIC_API_KEY")
            return

        body = json.dumps({
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 3000,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()

        req3 = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body)
        req3.add_header('x-api-key', anthropic_key)
        req3.add_header('anthropic-version', '2023-06-01')
        req3.add_header('content-type', 'application/json')

        with urllib.request.urlopen(req3, timeout=90) as r3:
            resp = json.loads(r3.read().decode())

        texto = resp['content'][0]['text'].strip()

        # Limpiar markdown
        if '```' in texto:
            partes = texto.split('```')
            for p in partes:
                p = p.strip().lstrip('json').strip()
                if p.startswith('{'):
                    texto = p
                    break

        picks_data = json.loads(texto)
        picks_data['generado'] = dt.now().isoformat()

        from data_dir import data_path as _dp
        path = _dp('picks_del_dia.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(picks_data, f, ensure_ascii=False, indent=2)

        total = len(picks_data.get('high_confidence_picks', []))
        _log_job("picks", f"{total} picks generados para {hoy}")
        print(f"[JOB-PICKS] {total} picks guardados correctamente")

    except Exception as e:
        import traceback
        print(f"[JOB-PICKS] ERROR: {e}")
        _log_job("picks", f"ERROR: {e}")
