#!/bin/bash
set -e

echo "=== Installing Caddy ==="
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy

echo "=== Configuring Caddy ==="
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
amdlxd.duckdns.org {
    # Remove Caddy's own Server and Via headers
    header -Server
    header -Via

    # Security & OPSEC anti-indexing headers
    header {
        X-Robots-Tag "noindex, nofollow, noarchive"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    reverse_proxy localhost:8000 {
        # Remove backend upstream Server and Via headers if present
        header_down -Server
        header_down -Via
    }
}
EOF

echo "=== Restarting Caddy ==="
sudo systemctl enable caddy
sudo systemctl restart caddy

echo "=== Caddy Status ==="
sudo systemctl status caddy --no-pager

echo "=== Done! Testing HTTPS ==="
sleep 5
curl -s -o /dev/null -w "%{http_code}" https://amdlxd.duckdns.org/api/config || echo "May take a moment for cert to provision"
