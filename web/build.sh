#!/bin/bash
# build.sh — Inject API URL into index.html for Cloudflare Pages deployment
#
# Usage:
#   API_URL="https://gamdl-api-xxxxx-uc.a.run.app" bash build.sh
#
# Cloudflare Pages settings:
#   Build command:           cd web && bash build.sh
#   Build output directory:  web
#   Environment variable:    API_URL = https://gamdl-api-xxxxx-uc.a.run.app

API_URL="${API_URL:-}"

if [ -n "$API_URL" ]; then
    echo "Injecting API URL: $API_URL"
    sed -i "s|<meta name=\"api-url\" content=\"\">|<meta name=\"api-url\" content=\"$API_URL\">|" index.html
else
    echo "No API_URL set, using same-origin fallback"
fi
