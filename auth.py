"""
AUTH.PY — Sistema de autenticacion por token para NEME BET
"""

import functools
from flask import session, redirect, url_for, request, flash
from stripe_handler import verify_token, get_user_plan, PLANS


def login_required(f):
    """Decorator: requiere login con token activo."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = session.get("token")
        if not token:
            flash("Inicia sesion para acceder")
            return redirect(url_for("login_page"))
        user = verify_token(token)
        if not user:
            session.pop("token", None)
            flash("Tu suscripcion vencio. Renueva para continuar.")
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return wrapper


def get_current_user():
    """Retorna el usuario actual o None."""
    token = session.get("token")
    if not token:
        return None
    return verify_token(token)


def get_current_plan():
    """Retorna el plan actual del usuario."""
    token = session.get("token")
    if not token:
        return None
    return get_user_plan(token)


def plan_allows(feature):
    """Verifica si el plan actual permite una feature."""
    plan = get_current_plan()
    if not plan:
        return False
    if feature == "unlimited_picks":
        return plan in ("pro", "vip")
    if feature == "scanner":
        return plan in ("pro", "vip")
    if feature == "push_alerts":
        return plan in ("pro", "vip")
    if feature == "full_history":
        return plan in ("pro", "vip")
    if feature == "vip_analysis":
        return plan == "vip"
    return True
