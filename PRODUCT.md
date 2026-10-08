# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Audiophiles, music archivists, and everyday listeners wanting a zero-install web interface to download Apple Music songs, music videos, and synced lyrics without using command-line tools.

## Product Purpose
Amdlxd provides an elegant, web-native interface for Apple Music downloading powered by a FastAPI backend and Gamdl. It enables users to resolve Apple Music URLs, preview rich track and album metadata, inspect and extract synced lyrics, and download audio (AAC standard/spatial/downmix) and video assets directly via the browser.

## Positioning
A browser-based GUI for Gamdl featuring real-time Server-Sent Events (SSE) progress streaming, client-side Netscape cookie authentication, and an optional admin-managed accounts pool—delivering the power of terminal-grade downloaders within a zero-install, Cupertino-inspired web experience.

## Operating Context
- Static web frontend (`web/` directory) deployed on Cloudflare Pages or run locally, connecting to a containerized FastAPI backend on Cloud Run or Docker.
- Primary interaction starts from pasting an Apple Music URL (song, album, playlist, music video, post video).
- Authentication managed either via user-supplied Netscape `cookies.txt` or by unlocking an admin-provided reserve accounts pool with an access passcode.
- Real-time download progress streamed to the client using SSE, with recent download history persisted in browser storage.

## Capabilities and Constraints
- **URL Resolution & Preview**: Instant metadata extraction (cover artwork, title, artist, genre, release date, explicit tags, and tracklist).
- **Audio Options**: AAC 256kbps (stable), AAC-HE 64kbps, experimental 48kHz AAC, AAC binaural/spatial, and AAC downmix.
- **Video Options**: Music videos and post videos up to 1080p / 4K.
- **Lyrics & Artwork**: Synced lyrics (.lrc file and embedded tags) and full-resolution cover art extraction.
- **Authentication Constraint**: Decryption requires active Apple Music subscription credentials (Netscape cookie format).
- **Stateless Architecture**: Backend does not store persistent user sessions; credentials and download requests are client-coordinated.

## Brand Commitments
- **Name**: Amdlxd / amdlxd.
- **Visual Identity**: Apple-inspired dark aesthetic (`#1a1a1e` dark canvas, sleek borders, refined glassmorphism, Inter typography).
- **Voice & Tone**: Clean, precise, and unobtrusive.
- **Signature Touches**: Apple Event ribbon splash loader, live status indicators, and clean card-based previews.

## Evidence on Hand
- Frontend implementation in [web/](file:///c:/Users/Home%20PC/Documents/git/gamdl/web) (`index.html`, `css/style.css`, `css/splash.css`, `js/`).
- Python backend services in [server/](file:///c:/Users/Home%20PC/Documents/git/gamdl/server) and [gamdl/](file:///c:/Users/Home%20PC/Documents/git/gamdl/gamdl).
- Architecture specs in [Coding Guide.md](file:///c:/Users/Home%20PC/Documents/git/gamdl/Coding%20Guide.md) and deployment phase guides (`phase-1-client-side-auth.md` through `phase-5-frontend-cloudflare-pages.md`).

## Product Principles
1. **Zero-friction workflow**: Immediate URL preview and one-click downloading without CLI friction.
2. **Audio & metadata fidelity**: Strict preservation of official bitrates, embedded tags, synced lyrics, and high-resolution album artwork.
3. **Transparent live feedback**: Granular progress reporting across extraction, decryption, download, and remuxing phases via SSE.
4. **Privacy-first authentication**: Client-controlled credentials and cookie handling with no server-side retention.
