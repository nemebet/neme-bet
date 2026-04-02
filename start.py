import os
import subprocess
port = os.environ.get('PORT', '5000')
subprocess.run(['gunicorn', 'webapp_minimal:app', '--bind', f'0.0.0.0:{port}', '--workers', '1'])
