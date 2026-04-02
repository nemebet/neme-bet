"""
DATA_DIR.PY — Directorio centralizado para datos persistentes.
En Railway usa /app/data (volumen montado).
En local usa la raiz del proyecto.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Railway volume mount: /app/data
# Local dev: same as project root
_vol = "/app/data"
DATA_DIR = _vol if os.path.isdir(_vol) else BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)


def data_path(filename):
    """Retorna la ruta completa de un archivo de datos."""
    return os.path.join(DATA_DIR, filename)
