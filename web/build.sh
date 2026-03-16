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

# Inject Firebase config (optional — falls back to hardcoded dev values)
FIREBASE_API_KEY="${FIREBASE_API_KEY:-}"
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-}"
FIREBASE_APP_ID="${FIREBASE_APP_ID:-}"

if [ -n "$FIREBASE_API_KEY" ]; then
    echo "Injecting Firebase config for project: $FIREBASE_PROJECT_ID"
    sed -i "s|<meta name=\"firebase-api-key\" content=\"\">|<meta name=\"firebase-api-key\" content=\"$FIREBASE_API_KEY\">|" index.html
    sed -i "s|<meta name=\"firebase-project-id\" content=\"\">|<meta name=\"firebase-project-id\" content=\"$FIREBASE_PROJECT_ID\">|" index.html
    sed -i "s|<meta name=\"firebase-app-id\" content=\"\">|<meta name=\"firebase-app-id\" content=\"$FIREBASE_APP_ID\">|" index.html
else
    echo "No FIREBASE_API_KEY set, using hardcoded fallback in firebase-config.js"
fi
