#!/bin/bash
# ═══════════════════════════════════════════
# NEME BET v5.0 — Arranque automatico
# ═══════════════════════════════════════════
set -e
cd "$(dirname "$0")"

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │       NEME BET v5.0                 │"
echo "  │  Predictor con IA y Autoaprendizaje │"
echo "  └─────────────────────────────────────┘"
echo ""

# Python check
command -v python3 &>/dev/null || { echo "[ERROR] Python3 no encontrado"; exit 1; }

# Install pip if needed
echo "[1/3] Dependencias..."
if ! python3 -m pip --version &>/dev/null; then
    python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')" 2>/dev/null
    python3 /tmp/get-pip.py --user --break-system-packages 2>/dev/null || true
fi

# Install Flask
python3 -m pip install --user --break-system-packages --quiet flask pillow 2>/dev/null || true

# OCR (optional)
echo "[2/3] OCR..."
if command -v tesseract &>/dev/null; then
    echo "  tesseract OK"
    python3 -m pip install --user --break-system-packages --quiet pytesseract 2>/dev/null || true
else
    echo "  tesseract no instalado (OCR usara Claude Vision)"
fi

# .env check
echo "[3/3] Configuracion..."
[ ! -f .env ] && cat > .env << 'EOF'
FOOTBALL_DATA_API_KEY=dd3d5d1c1bb940ddb78096ea7abd6db7
API_FOOTBALL_KEY=a1572eeacc1837fb47d69dba3f1958ae
# ANTHROPIC_API_KEY=sk-ant-...
EOF

# Get IP
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP="localhost"

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │  LISTO                              │"
echo "  │                                     │"
echo "  │  PC:       http://localhost:5000     │"
echo "  │  Telefono: http://${IP}:5000  │"
echo "  │                                     │"
echo "  │  Para instalar en Android:          │"
echo "  │  Abre en Chrome > menu > Instalar   │"
echo "  │                                     │"
echo "  │  Ctrl+C para detener                │"
echo "  └─────────────────────────────────────┘"
echo ""

exec python3 webapp.py
