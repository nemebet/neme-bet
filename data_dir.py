import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# En Railway el directorio de trabajo es /app
# Intentar /app/data, luego /tmp/nemebet, luego BASE_DIR
def _get_data_dir():
    for candidate in ["/app/data", "/app", "/tmp/nemebet", BASE_DIR]:
        try:
            os.makedirs(candidate, exist_ok=True)
            # Verificar que podemos escribir
            test = os.path.join(candidate, ".write_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            print(f"[DATA_DIR] Usando: {candidate}")
            return candidate
        except Exception as e:
            print(f"[DATA_DIR] No se puede usar {candidate}: {e}")
            continue
    return BASE_DIR

DATA_DIR = _get_data_dir()

def data_path(filename):
    return os.path.join(DATA_DIR, filename)
