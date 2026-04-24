"""Script independiente para generar picks - llamado desde webapp."""
import os, json, urllib.request
from datetime import datetime

def generar_picks_ahora(path, hoy, anthropic_key):
    """Genera picks usando Claude con conocimiento propio."""
    
    prompt = (
        f"Eres NEMEBET v5, experto en pronosticos deportivos. Hoy es {hoy}.\n\n"
        "Genera picks para los mejores partidos de HOY en las principales ligas europeas "
        "(Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, UCL, UEL). "
        "Usa tu conocimiento real de la temporada 2025-26.\n\n"
        "REGLAS:\n"
        "1. Solo picks con probabilidad real mayor al 63%\n"
        "2. Valor matematico: (prob x cuota) - 1 mayor a 0.08\n"
        "3. Cuotas entre 1.65 y 2.50\n"
        "4. BTTS mas seguro que Over 2.5 en partidos europeos\n"
        "5. Considerar bajas, H2H reciente e importancia del partido\n"
        "6. Si visitante juega en bloque bajo, apostar corners local\n\n"
        "Responde SOLO con JSON valido sin markdown:\n"
        '{"fecha":"' + hoy + '",'
        '"generado":"' + datetime.now().isoformat() + '",'
        '"high_confidence_picks":['
        '{"id":"ejemplo_id",'
        '"local":"Equipo Local",'
        '"visitante":"Equipo Visitante",'
        '"match":"Local vs Visitante",'
        '"liga":"Nombre Liga",'
        '"hora":"21:00",'
        '"confianza":70,'
        '"prob":70,'
        '"mercado":"Under 2.5 Goles",'
        '"bet":"Under 2.5 Goles",'
        '"cuota_referencia":1.75,'
        '"odds":1.75,'
        '"edge":22,'
        '"justificacion":"H2H Under en 4/5. Valor: 0.70x1.75-1=+22%",'
        '"importancia":"descripcion",'
        '"bajas_consideradas":"ninguna critica",'
        '"estado":"pendiente",'
        '"recomendado":true,'
        '"tipo":"goles"}'
        '],'
        '"medium_confidence_picks":[],'
        '"picks_corners":[],'
        '"picks_remates":[]}'
    )

    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
    req.add_header("x-api-key", anthropic_key)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")

    with urllib.request.urlopen(req, timeout=90) as r:
        resp = json.loads(r.read().decode())

    texto = resp["content"][0]["text"].strip()
    
    # Limpiar markdown si viene
    if "```" in texto:
        partes = texto.split("```")
        for p in partes:
            p = p.strip().lstrip("json").strip()
            if p.startswith("{"):
                texto = p
                break

    picks = json.loads(texto)
    picks["generado"] = datetime.now().isoformat()
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)
    
    return len(picks.get("high_confidence_picks", []))
