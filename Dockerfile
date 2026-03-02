# Dockerfile — Hugging Face Spaces (Docker SDK)
# Bundles: Python 3.12 + FFmpeg + mp4decrypt + Wrapper + Gamdl Backend

FROM python:3.12-slim

# ── Install system dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ── Install mp4decrypt (Bento4) ──────────────────────────────────────────────
RUN wget -qO /tmp/bento4.zip \
    https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip \
    && unzip /tmp/bento4.zip -d /tmp/bento4 \
    && cp /tmp/bento4/*/bin/mp4decrypt /usr/local/bin/ \
    && chmod +x /usr/local/bin/mp4decrypt \
    && rm -rf /tmp/bento4*

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
RUN pip install --no-cache-dir .

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
ENV PORT=7860
ENV CLOUD_MODE=true
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/api/config')" || exit 1

CMD ["bash", "start.sh"]
