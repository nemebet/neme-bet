"""
EMAIL_SERVICE.PY — Emails automaticos para NEME BET
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER = os.environ.get("EMAIL_SENDER", "swatfest2026@gmail.com")
PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
APP_URL = os.environ.get("APP_URL", "https://neme-bet-production.up.railway.app")


def _send(to, subject, html_body):
    """Envia email via SMTP."""
    if not PASSWORD:
        print(f"[EMAIL] No password configured, skipping email to {to}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"NEME BET <{SENDER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER, PASSWORD)
            server.sendmail(SENDER, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def send_welcome(email, token, plan):
    plan_names = {"basico": "Basico", "pro": "Pro", "vip": "VIP"}
    _send(email, "Bienvenido a NEME BET", f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;background:#0A0A0A;color:#F0F0F0;padding:30px;border-radius:12px">
        <h1 style="color:#1AE89B;text-align:center">NEME BET</h1>
        <p>Tu suscripcion <strong>{plan_names.get(plan, plan)}</strong> esta activa.</p>
        <p>Tu token de acceso:</p>
        <div style="background:#1A1A1A;padding:15px;border-radius:8px;font-family:monospace;word-break:break-all;color:#1AE89B">{token}</div>
        <p style="margin-top:20px"><a href="{APP_URL}/login" style="background:#0F6E56;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Ingresar a NEME BET</a></p>
        <p style="color:#888;font-size:12px;margin-top:20px">Guarda este email. El token es tu clave de acceso.</p>
    </div>""")


def send_renewal_reminder(email, days_left):
    _send(email, f"NEME BET - Tu suscripcion vence en {days_left} dias", f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;background:#0A0A0A;color:#F0F0F0;padding:30px;border-radius:12px">
        <h2 style="color:#F5A623">Tu suscripcion vence en {days_left} dias</h2>
        <p>Renueva para seguir recibiendo picks diarios con +75% de precision.</p>
        <p><a href="{APP_URL}" style="background:#0F6E56;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Renovar ahora</a></p>
    </div>""")


def send_expired(email):
    _send(email, "NEME BET - Tu suscripcion vencio", f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;background:#0A0A0A;color:#F0F0F0;padding:30px;border-radius:12px">
        <h2 style="color:#FF4757">Tu suscripcion ha vencido</h2>
        <p>Renueva para recuperar acceso a tus picks diarios.</p>
        <p><a href="{APP_URL}" style="background:#0F6E56;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Renovar suscripcion</a></p>
    </div>""")
