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

# Start the FastAPI backend
echo "[2/2] Starting Gamdl Backend on port 7860..."
exec uvicorn server.main:app --host 0.0.0.0 --port 7860 --workers 1
