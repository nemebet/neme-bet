"""
EMAIL_SERVICE.PY — Emails con Resend para NEME BET
"""

import json
import os
import urllib.request
import urllib.error

RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER = os.environ.get("EMAIL_FROM", "NEME BET <noreply@swatlatam.com>")
APP_URL = os.environ.get("APP_URL", "https://web-production-940b9.up.railway.app")

LOGO = f'{APP_URL}/static/logo.svg'
ICON = f'{APP_URL}/static/icon-192.png'

# ─── Base HTML template ───
def _wrap(content):
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#050505;font-family:-apple-system,sans-serif">
<div style="max-width:480px;margin:0 auto;padding:24px">
<div style="text-align:center;padding:20px 0"><img src="{ICON}" alt="NEME BET" width="48" height="48" style="border-radius:12px"></div>
<div style="background:#0A0A0A;border:1px solid #1A1A1A;border-radius:16px;padding:28px;color:#F0F0F0">
{content}
</div>
<div style="text-align:center;padding:16px 0;font-size:11px;color:#444">
NEME BET &copy; 2026 | Analisis estadistico de futbol<br>
Los analisis son orientativos. Apuesta responsablemente.
</div>
</div></body></html>'''


def _btn(text, url):
    return f'<div style="text-align:center;margin:20px 0"><a href="{url}" style="display:inline-block;background:#0F6E56;color:white;padding:14px 32px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px">{text}</a></div>'


# ─── Send via Resend API ───
def _send(to, subject, html):
    if not RESEND_KEY:
        print(f"[EMAIL] No RESEND_API_KEY, skipping -> {to}: {subject}")
        return False

    payload = json.dumps({
        "from": SENDER,
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode("utf-8")

    req = urllib.request.Request("https://api.resend.com/emails",
                                 data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {RESEND_KEY}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            print(f"[EMAIL] Sent to {to}: {result.get('id', 'ok')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, 'read') else ''
        print(f"[EMAIL ERROR] {e.code}: {body[:200]}")
        return False
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


# ─── Email templates ───

def send_welcome(email, token, plan):
    plan_names = {"basico": "Basico", "pro": "Pro", "vip": "VIP"}
    html = _wrap(f'''
    <h1 style="color:#1AE89B;text-align:center;margin:0 0 16px;font-size:22px">Bienvenido a NEME BET</h1>
    <p style="text-align:center;color:#888;margin:0 0 20px">Tu suscripcion <strong style="color:#1AE89B">{plan_names.get(plan, plan)}</strong> esta activa</p>
    <div style="background:#111;border:1px solid #222;border-radius:10px;padding:16px;margin:16px 0">
        <div style="font-size:12px;color:#888;margin-bottom:6px">Tu token de acceso:</div>
        <div style="font-family:monospace;font-size:13px;word-break:break-all;color:#1AE89B;line-height:1.4">{token}</div>
    </div>
    <p style="font-size:13px;color:#888">Copia este token y usalo para ingresar en la app. Tambien lo puedes encontrar siempre en este email.</p>
    {_btn("Ingresar a NEME BET", f"{APP_URL}/login")}
    <p style="font-size:11px;color:#555;text-align:center">Guarda este email. El token es tu unica clave de acceso.</p>
    ''')
    _send(email, "Bienvenido a NEME BET - Tu token de acceso", html)


def send_renewal_reminder(email, days_left):
    html = _wrap(f'''
    <h2 style="color:#F5A623;text-align:center;margin:0 0 16px">Tu suscripcion vence en {days_left} dias</h2>
    <p style="color:#ccc;text-align:center">Renueva para seguir recibiendo analisis diarios con +75% de precision.</p>
    {_btn("Renovar ahora", APP_URL)}
    ''')
    _send(email, f"NEME BET - Tu suscripcion vence en {days_left} dias", html)


def send_expired(email):
    html = _wrap(f'''
    <h2 style="color:#FF4757;text-align:center;margin:0 0 16px">Tu suscripcion ha vencido</h2>
    <p style="color:#ccc;text-align:center">Renueva para recuperar acceso a tus analisis diarios.</p>
    {_btn("Renovar suscripcion", APP_URL)}
    ''')
    _send(email, "NEME BET - Tu suscripcion vencio", html)


def send_daily_picks(email, picks):
    picks_html = ""
    for p in picks[:5]:
        picks_html += f'''
        <div style="background:#111;border-left:3px solid #1AE89B;border-radius:8px;padding:12px;margin:8px 0">
            <div style="font-weight:700;font-size:14px">{p.get("bet", "")}</div>
            <div style="font-size:13px;color:#888">{p.get("match", "")}</div>
            <div style="color:#1AE89B;font-weight:700;font-size:16px;margin-top:4px">{p.get("prob", "")}%</div>
        </div>'''

    html = _wrap(f'''
    <h2 style="color:#1AE89B;text-align:center;margin:0 0 16px">Picks del dia</h2>
    <p style="color:#888;text-align:center;font-size:13px">{len(picks)} analisis con alta confianza</p>
    {picks_html}
    {_btn("Ver analisis completo", f"{APP_URL}/picks")}
    ''')
    _send(email, f"NEME BET - {len(picks)} picks del dia", html)
