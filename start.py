import os
import subprocess

port = os.environ.get('PORT', '5000')

# Pasar todas las variables de entorno al proceso gunicorn
subprocess.run(
    ['gunicorn', 'webapp:app', '--bind', f'0.0.0.0:{port}', '--workers', '1', '--timeout', '120'],
    env=os.environ.copy()
)
