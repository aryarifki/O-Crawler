#!/usr/bin/env bash
# 🦅 O-Crawler SaaS GUI Launcher (Local Browser & Desktop)

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

PORT="${PORT:-8080}"
VENV_BIN="$DIR/venv/bin"

if [ ! -f "$VENV_BIN/python" ]; then
    echo "⚠️  Virtual environment belum ditemukan. Menyiapkan..."
    python3 -m venv "$DIR/venv"
    "$VENV_BIN/pip" install --upgrade pip
    "$VENV_BIN/pip" install -r "$DIR/requirements.txt"
fi

echo "===================================================================="
echo "      🦅  O-CRAWLER: MODERN LEGAL CRAWLER & INGESTION SAAS"
echo "===================================================================="
echo " 🌐 Dashboard Lokal  : http://localhost:$PORT"
echo " 🌐 Subdomain Publik : https://ocrawler.sugarate.me (atau https://ocrawler.cugarete.me)"
echo " 🗄️  Database        : PostgreSQL (owlexia_db) / SQLite Local Fallback"
echo " ☁️  Cloudflare R2   : Streaming Storage (Zero Egress)"
echo " ⚖️  Sumber Didukung : Peraturan.go.id, Mahkamah Agung, Mahkamah Konstitusi"
echo "===================================================================="
echo ""

# Buka browser otomatis jika ada Display Desktop / xdg-open
if [ -n "$DISPLAY" ] && command -v xdg-open >/dev/null 2>&1; then
    (sleep 1.5 && xdg-open "http://localhost:$PORT" 2>/dev/null || true) &
fi

exec "$VENV_BIN/python" -m uvicorn server:app --host 0.0.0.0 --port "$PORT"
