#!/bin/bash
set -e

echo "============================================"
echo "  gamdl — Hugging Face Spaces Startup"
echo "============================================"

# Start the Wrapper in the background
if [ -x /app/Wrapper/wrapper ]; then
    echo "[1/2] Starting Wrapper (ports 10020, 20020, 30020)..."
    cd /app/Wrapper
    ./wrapper -H 0.0.0.0 &
    WRAPPER_PID=$!
    cd /app
    sleep 2

    if kill -0 "$WRAPPER_PID" 2>/dev/null; then
        echo "  ✓ Wrapper running (PID $WRAPPER_PID)"
    else
        echo "  ✗ Wrapper failed to start — continuing without it"
    fi
else
    echo "[1/2] Wrapper binary not found — skipping"
fi

# Start auto-cleanup for old download temp files (every 5 minutes, deletes dirs older than 15 minutes)
echo "[2/2] Starting auto-cleanup (removing /tmp/gamdl_* older than 15 min, every 5 min)..."
(while true; do
    find /tmp -maxdepth 1 -type d -name 'gamdl_*' -mmin +15 -exec rm -rf {} + 2>/dev/null
    sleep 300
done) &

# Start the FastAPI backend
echo "[3/3] Starting Gamdl Backend on port ${PORT:-8000}..."
exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
