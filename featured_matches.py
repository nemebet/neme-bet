import os, json, time, urllib.request
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join('/app/data' if os.path.isdir('/app/data') else BASE_DIR, 'featured_matches.json')
CACHE_TTL = 300

def fetch_partidos(force=False):
    now = time.time()
    
    # Leer cache si es fresco
    if not force and os.path.exists(CACHE_FILE):
        try:
            if now - os.path.getmtime(CACHE_FILE) < CACHE_TTL:
                with open(CACHE_FILE, encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('partidos'):
                    return data
        except:
            pass
    
    # Fetch de API-Football
    key = 'a1572eeacc1837fb47d69dba3f1958ae'
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    try:
        url = f'https://v3.football.api-sports.io/fixtures?date={today}&timezone=America/Bogota'
        req = urllib.request.Request(url)
        req.add_header('x-apisports-key', key)
        req.add_header('User-Agent', 'Mozilla/5.0')
        
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read().decode())
        
        partidos = []
        for f in raw.get('response', []):
            try:
                status = f['fixture']['status']['short']
                home = f['teams']['home']['name']
                away = f['teams']['away']['name']
                liga = f['league']['name']
                pais = f['league']['country']
                hora_utc = f['fixture']['date']
                is_live = status in ['1H','2H','HT','ET','P','BT']
                
                partidos.append({
                    'id': str(f['fixture']['id']),
                    'home': home,
                    'away': away,
                    'local': home,
                    'visitante': away,
                    'competition': liga,
                    'liga': liga,
                    'pais': pais,
                    'hora': hora_utc[11:16] if len(hora_utc) > 10 else '',
                    'utc_date': hora_utc,
                    'timestamp': f['fixture']['timestamp'],
                    'is_live': is_live,
                    'is_top': any(t in home.lower() or t in away.lower() for t in ['manchester','real madrid','barcelona','psg','liverpool','bayern','juventus','chelsea','arsenal','milan']),
                    'region': 'EU' if pais in ['England','Spain','Germany','France','Italy','Portugal'] else 'LATAM' if pais in ['Colombia','Argentina','Brazil','Mexico','Chile'] else 'OTHER',
                    'recommended': False,
                    'countdown': 'EN VIVO' if is_live else '',
                    'relevance': 70 if is_live else 50,
                    'source': 'api-football'
                })
            except:
                continue
        
        # Ordenar: en vivo primero
        partidos.sort(key=lambda x: (0 if x['is_live'] else 1, x.get('timestamp', 0)))
        if partidos:
            partidos[0]['recommended'] = True
        
        resultado = {
            'partidos': partidos,
            'total': len(partidos),
            'en_vivo': sum(1 for p in partidos if p['is_live']),
            'fuente': 'API-Football',
            'actualizado': datetime.now().isoformat(),
            'rango_horas': 24,
            'regions': {},
            'live_count': sum(1 for p in partidos if p['is_live'])
        }
        
        # Guardar cache
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(resultado, f, ensure_ascii=False)
        except Exception as e:
            print(f'[CACHE] Error: {e}')
        
        print(f'[FEATURED] {len(partidos)} partidos obtenidos')
        return resultado
        
    except Exception as e:
        print(f'[FEATURED] Error: {e}')
        # Retornar cache viejo si existe
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'partidos': [], 'total': 0, 'en_vivo': 0, 'fuente': 'error', 'actualizado': datetime.now().isoformat(), 'rango_horas': 24, 'regions': {}, 'live_count': 0}

def _env_key(name):
    return os.environ.get(name, '') or {'API_FOOTBALL_KEY': 'a1572eeacc1837fb47d69dba3f1958ae', 'FOOTBALL_DATA_API_KEY': 'dd3d5d1c1bb940ddb78096ea7abd6db7'}.get(name, '')
