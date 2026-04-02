"""
AUTH.PY — Sistema de autenticacion para NEME BET
"""

import functools
from flask import session, redirect, url_for, flash
from stripe_handler import find_user_by_email, verify_token, PLANS


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash("Inicia sesion para acceder")
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def get_current_user():
    """Retorna el usuario actual o None."""
    # New system: email-based
    email = session.get("user_email")
    if email:
        _, user = find_user_by_email(email)
        if user and user.get("active"):
            return user
        # User expired/inactive
        session.pop("user_email", None)
        return None

    # Legacy: token-based (backwards compat)
    token = session.get("token")
    if token:
        user = verify_token(token)
        if user:
            return user
        session.pop("token", None)

    return None


def get_current_plan():
    user = get_current_user()
    if not user:
        return None
    return user.get("plan", "basico")


def plan_allows(feature):
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
