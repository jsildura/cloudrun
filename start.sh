#!/bin/bash
set -e

echo "============================================"
echo "  gamdl — Hugging Face Spaces Startup"
echo "============================================"

# Wait for proxy if configured to ensure wrapper doesn't fail on cold boot
if [ -n "$ALL_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
    echo "Waiting for proxy to become ready..."
    for i in $(seq 1 20); do
        if python3 -c "import socket; s=socket.create_connection(('127.0.0.1', 9091), timeout=1); s.close()" 2>/dev/null; then
            echo "  ✓ Proxy is ready"
            break
        fi
        sleep 1
    done
fi

# Start the Wrapper in the background
if [ -x /app/Wrapper/wrapper ]; then
    echo "[1/2] Starting Wrapper (ports 10020, 20020, 30020)..."
    mkdir -p /app/Wrapper/rootfs/dev /app/Wrapper/rootfs/proc /app/Wrapper/rootfs/sys
    mount --bind /dev /app/Wrapper/rootfs/dev 2>/dev/null || true
    cd /app/Wrapper
    ./wrapper -H 0.0.0.0 > /tmp/wrapper.log 2>&1 &
    cd /app
    
    WRAPPER_OK=false
    for i in $(seq 1 15); do
        if python3 -c "import socket; s=socket.create_connection(('127.0.0.1', 30020), timeout=0.5); s.close()" 2>/dev/null; then
            echo "  ✓ Wrapper running and healthy on ports 10020, 20020, 30020"
            WRAPPER_OK=true
            break
        fi
        sleep 0.5
    done
    if [ "$WRAPPER_OK" != "true" ]; then
        echo "  ✗ Wrapper failed to start — log output:"
        cat /tmp/wrapper.log 2>/dev/null || true
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
exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --no-server-header --proxy-headers
