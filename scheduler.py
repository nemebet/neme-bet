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

    # Cada 6 horas — Captura de resultados
    scheduler.add_job(
        func=job_check_results,
        trigger=IntervalTrigger(hours=6),
        id="check_results",
        name="Captura resultados automatica",
        replace_existing=True,
    )

    scheduler.start()
    atexit.register(scheduler.shutdown)

    print("[SCHEDULER] Tareas programadas:")
    for job in scheduler.get_jobs():
        print(f"  - {job.name}: {job.trigger}")

    return scheduler


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
        subs_path = os.path.join(BASE_DIR, "push_subscriptions.json")
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
    log_path = os.path.join(BASE_DIR, "scheduler_log.json")
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
