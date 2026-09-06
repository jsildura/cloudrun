# Dockerfile — Hugging Face Spaces (Docker SDK)
# Bundles: Python 3.12 + FFmpeg + mp4decrypt + Wrapper + Gamdl Backend

FROM python:3.12-slim

# ── Install system dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gpac \
    wget \
    tar \
    unzip \
    tini \
    && rm -rf /var/lib/apt/lists/*

# ── Install mp4decrypt (Bento4) ──────────────────────────────────────────────
RUN wget -qO /tmp/bento4.zip \
    https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip \
    && unzip /tmp/bento4.zip -d /tmp/bento4 \
    && cp /tmp/bento4/*/bin/mp4decrypt /usr/local/bin/ \
    && chmod +x /usr/local/bin/mp4decrypt \
    && rm -rf /tmp/bento4*

# ── Install N_m3u8DL-RE with fallback ────────────────────────────────────────
RUN set -e; \
    RELEASE_URL="https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.6.0-beta/N_m3u8DL-RE_v0.6.0-beta_linux-x64_20260629.tar.gz"; \
    wget -qO /tmp/nm3u8dlre.tar.gz "$RELEASE_URL" || \
    wget -qO /tmp/nm3u8dlre.tar.gz "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.6.0-beta/N_m3u8DL-RE_v0.6.0-beta_linux-x64.tar.gz" || \
    wget -qO /tmp/nm3u8dlre.tar.gz "https://github.com/nilaoda/N_m3u8DL-RE/releases/latest/download/N_m3u8DL-RE_linux-x64.tar.gz" \
    && tar -xzf /tmp/nm3u8dlre.tar.gz -C /tmp \
    && (cp /tmp/N_m3u8DL-RE*/N_m3u8DL-RE /usr/local/bin/N_m3u8DL-RE 2>/dev/null || cp /tmp/N_m3u8DL-RE /usr/local/bin/N_m3u8DL-RE) \
    && chmod +x /usr/local/bin/N_m3u8DL-RE \
    && rm -rf /tmp/nm3u8dlre* /tmp/N_m3u8DL-RE*

# ── Install yt-dlp ───────────────────────────────────────────────────────────
RUN pip install --no-cache-dir yt-dlp

# ── Set up application directory ─────────────────────────────────────────────
WORKDIR /app

# ── Copy and prepare Wrapper ─────────────────────────────────────────────────
COPY Wrapper/ Wrapper/
RUN chmod +x Wrapper/wrapper 2>/dev/null || true

# ── Install gamdl package ────────────────────────────────────────────────────
COPY pyproject.toml .
COPY gamdl/ gamdl/
RUN pip install --no-cache-dir . socksio

# ── Install server dependencies ──────────────────────────────────────────────
COPY server/requirements.txt server/
RUN pip install --no-cache-dir -r server/requirements.txt

# ── Copy server code and web frontend ────────────────────────────────────────
COPY server/ server/
COPY web/ web/

# ── Copy startup script ──────────────────────────────────────────────────────
COPY start.sh .
RUN chmod +x start.sh

# ── Runtime configuration ────────────────────────────────────────────────────
ENV PORT=8000
ENV CLOUD_MODE=true
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/api/health')" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "start.sh"]
