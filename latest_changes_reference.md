Note: When their is changes please record all changes in this file, follow the format.

SSH
Public IP: 52.62.161.146
Instance: amdlxd-backend (t3.micro, Ubuntu 24.04)
Container: gamdl-app (new), gamdl-backend (old)
SSH key: amdlxd-key-pair.pem 
path:"C:\Users\Home PC\Documents\git\gamdl\amdlxd-key-pair.pem"
Username: ubuntu (since it's Ubuntu AMI)
The Caddyfile was proxying to localhost:8000 (the old default port)
But the Docker container was now listening on localhost:7860
warp-proxy sidecar container (Cloudflare WARP) on port 9091

## Changes Made (March 4, 2026)

1. **Uploaded updated files** — `style.css`, `index.html`, `app.js`, `models.py`, `download_manager.py`, `config.py`
2. **Fixed port mismatch** — Added `-e PORT=7860` to Docker run command; updated Caddyfile from `localhost:8000` → `localhost:7860`
3. **Added 2GB swap file** — Prevents OOM crashes during Docker builds on the 1GB t3.micro
4. **Added auto-cleanup cron** — Background loop in `start.sh` deletes `/tmp/gamdl_*` older than 1 hour every 30 minutes

⚠️ When editing `.sh` files on Windows, fix line endings on the server: `sed -i 's/\r$//' /home/ubuntu/gamdl/start.sh`

## Changes Made (March 5, 2026)

### 1. Feature: Save Animated Artwork (.mp4)
Added a settings toggle to download animated album/playlist artwork as MP4 files alongside tracks.
- User enables "Save animated artwork (.mp4)" in Output settings
- After all tracks download, backend fetches `editorialVideo` metadata from Apple Music API
- Uses `ffmpeg` to remux HLS `.m3u8` streams into `.mp4` files
- Two variants saved when available: `animated_cover_square.mp4` (1:1) and `animated_cover_tall.mp4` (3:4)
- MP4 files are included in the final ZIP alongside audio, lyrics, and cover files
- **Files modified:** `config.py`, `models.py`, `download_manager.py`, `api_routes.py`, `index.html`, `app.js`

### 2. Fix: Auth badge "(restricted)" label
- Changed to only show "(restricted)" when explicit content is actually blocked (`explicit.allowed === false`)
- Previously showed it whenever any restrictions object existed (e.g. PH storefront always returned one)
- **File modified:** `app.js`

### 3. Expanded swap file to 3GB
- Added another 1GB swap file (`/swapfile2`) on EC2 for total of 3GB swap
- Prevents OOM crashes during Docker builds on the 1GB t3.micro

### 4. Feature: Cancel Download Button
Added a "Cancel" text link below the progress bar that immediately stops the current download, including backend processing.
- **Frontend (CSS):** `.status-cancel-text` — small clickable text with color `#eb5871`, hover underline
- **Frontend (JS):**
  - "Cancel" text rendered dynamically inside `updateStatusFromJob()` after the progress bar, only during active stages (queued/parsing/preparing/downloading)
  - Delegated click handler on `statusContainer` calls `api.cancelDownload(_activeJobId)`
  - Text disappears on terminal states (done/error/cancelled)
- **Backend (`download_manager.py`):**
  - Added `_job_tasks` dict to track each job's `asyncio.Task`
  - `submit_download()` now stores the task reference
  - `cancel_job()` now calls `task.cancel()` for immediate interruption (not just flag-based)
  - `_process_job()` catches `asyncio.CancelledError` and broadcasts `CANCELLED` status cleanly
- **Files modified:** `index.html`, `style.css`, `app.js`, `download_manager.py`

### 5. Fix: Disabled state for URL Input and Download Button
- When re-downloading from a preview card after a cancellation, the URL input bar and main Download button weren't being disabled/greyed out
- Added `urlInput.disabled = true` and `btnSubmit.disabled = true` to the preview download button handler
- Ensures UI correctly reflects that the app is busy downloading
- **File modified:** `app.js`

### 6. Fix: Vertical alignment of Restart Button
- Added `align-items: center` to the `.field-row` CSS class
- Fixes the vertical misalignment between the "Use Wrapper" checkbox label and the "Restart" wrapper button in the settings modal
- **File modified:** `style.css`

## Changes Made (March 6, 2026)

### 1. Feature: Disable Developer Tools (Production Only)
- Added `disable-devtool` library via CDN to block dev tools access (F12, Ctrl+Shift+I, etc.) when deployed
- Uses programmatic `DisableDevtool()` call with `ignore` option to skip `localhost` and `127.0.0.1` — dev tools work normally during development
- Right-click context menu preserved (`disableMenu: false`)
- **File modified:** `index.html`

### 2. Fix: Duplicate `<h1>` Title
- Removed duplicate `<h1 class="app-title">amdlxd</h1>` tag
- **File modified:** `index.html`

### 3. Feature: Paste from Clipboard Button
- Added a clipboard paste icon button inside the URL input bar (right side, absolutely positioned)
- Clicking reads clipboard text and validates it as an Apple Music URL (album, song, playlist, music-video, post patterns)
- Shows error toast if clipboard content is not a valid Apple Music URL or clipboard access fails
- Button disables/greys out in sync with the input and Download button during preview, loading, and download states
- Uses `url-input-inner` wrapper div for proper absolute positioning on both desktop and mobile
- **Files modified:** `index.html`, `style.css`, `app.js`

### 4. UI: Input & Button Height Adjustment
- Reduced URL input height from `52px` → `42px`
- Matched Download button height to `42px`
- Updated mobile responsive padding for consistency
- **File modified:** `style.css`

## Changes Made (March 7, 2026)

### 1. Feature: Settings Migration to LocalStorage
Migrated user settings from global backend `web_config.json` to per-browser `localStorage`, preventing one user's settings from affecting another.
- **Frontend (`app.js`):** Added `SETTINGS_KEY`, `DEFAULT_SETTINGS`, `loadLocalSettings()`, `saveLocalSettings()` — settings load from/save to `localStorage` instead of `api.getConfig()`/`api.updateConfig()`
- **Frontend (`api.js`):** `startDownload()` and `previewUrl()` now accept and send a `config` object in the request body
- **Backend (`models.py`):** Added optional `config: ConfigUpdate | None` to `DownloadRequest`
- **Backend (`api_routes.py`):** Added `_merge_user_config()` that overlays user overrides on server base config using an allowlist of safe fields (codec, lyrics, cover, etc.) — server infrastructure fields (paths, cloud mode, tool binaries) can never be overridden
- **Files modified:** `models.py`, `api_routes.py`, `api.js`, `app.js`

### 2. Feature: Restore Defaults Button
- Added "Restore Defaults" button to settings modal footer
- Resets all form fields to `DEFAULT_SETTINGS` and saves to `localStorage` immediately
- **Files modified:** `index.html`, `app.js`

### 3. Feature: Dolby Atmos & Lossless Badges on Track List
Added per-track Dolby Atmos and Lossless SVG icon badges in the preview song list.
- **Backend (`models.py`):** Added `has_dolby_atmos` and `is_lossless` fields to `PreviewTrack`
- **Backend (`download_manager.py`):** Extracts `audioTraits` per-track from Apple Music API (`"atmos"`, `"lossless"`, `"hi-res-lossless"`)
- **Frontend (`app.js`):** Renders Dolby (DD icon) and Lossless (waveform icon) SVGs inline next to each track title
- **Frontend (`style.css`):** `.dolby-badge` and `.lossless-badge` — same 16px height as explicit badge, `color: var(--text-muted)` (#6e6e73)
- **Files modified:** `models.py`, `download_manager.py`, `app.js`, `style.css`

### 4. Fix: Wrapper Restart UX
- After successful restart, the Restart button is hidden immediately to prevent spam-clicking
- Toast message updated: "Wrapper successfully started, please refresh the page"
- Backend message updated to match
- **Files modified:** `app.js`, `api_routes.py`

### 5. Feature: Wrapper Restart Cooldown (5 Minutes)
- Added server-side 5-minute cooldown on `/api/wrapper/restart` to prevent abuse
- Returns `"Please wait Xs before restarting again"` if called within cooldown period
- Uses module-level `_last_wrapper_restart` timestamp — cannot be bypassed from the browser
- **File modified:** `api_routes.py`

## Changes Made (March 8, 2026)

### 1. Security: Cloudflare WARP Proxy (Upstream IP Masking)
Added a Cloudflare WARP SOCKS5 proxy sidecar container to mask the backend's outbound IP address from Apple Music servers.
- **Architecture:** `gamdl-app` shares the `warp-proxy` container's network via `--network container:warp-proxy`. All `httpx` requests are routed through the WARP SOCKS5 proxy at `127.0.0.1:9091`.
- **Dockerfile:** Added `socksio` package (`pip install . socksio`) — required for `httpx` to support `socks5h://` proxy URLs
- **Docker run env vars:**
  - `HTTPS_PROXY=socks5h://127.0.0.1:9091`
  - `HTTP_PROXY=socks5h://127.0.0.1:9091`
  - `ALL_PROXY=socks5h://127.0.0.1:9091`
  - `NO_PROXY=localhost,127.0.0.1` (prevents healthcheck from routing through proxy)
- **Result:** Outbound IP changed from `16.176.205.50` (real EC2) → `104.28.228.199` (Cloudflare WARP)
- **Memory impact:** warp-proxy uses ~12MB, total ~92MB / 911MB
- **Container:** `warp-proxy` (image: `monius/docker-warp-socks`) owns port 7860 mapping; `gamdl-app` uses image `gamdl-app-warp` (committed with `socksio` installed)
- **File modified:** `Dockerfile`

## Changes Made (March 9, 2026)

### 1. Feature: Realtime EC2 System Stats Bar
Added a fixed bottom status bar displaying live CPU, RAM, and Swap usage of the EC2 host, updated every 3 seconds.
- **Backend (`api_routes.py`):** New `GET /api/system/stats` endpoint — unauthenticated, rate-limited only. Uses `psutil` to read `/proc` for host-level metrics. Includes a warm-up `psutil.cpu_percent()` call at import time so the first request returns accurate CPU data.
- **Backend (`requirements.txt`):** Added `psutil>=6.0.0`
- **Frontend (`index.html`):** Stats bar HTML (`#system-stats-bar`) with three spans: `stat-cpu`, `stat-ram`, `stat-swap`
- **Frontend (`style.css`):** `.system-stats-bar` — fixed bottom, glassmorphism background (`rgba(26,26,30,0.85)` + `backdrop-filter: blur(12px)`), monospace font for numbers. Color-coded states: `.stat-warning` (orange, ≥80%) and `.stat-danger` (red, ≥95%). Mobile responsive.
- **Frontend (`api.js`):** `getSystemStats()` — plain fetch without auth header since endpoint is public
- **Frontend (`app.js`):** `fetchSystemStats()` polls every 3s via `setInterval`, updates text and applies warning/danger CSS classes based on utilization thresholds
- **Files modified:** `server/requirements.txt`, `server/api_routes.py`, `web/index.html`, `web/css/style.css`, `web/js/api.js`, `web/js/app.js`

### 2. Feature: Multi-Disc Album Folder Organization in ZIP
Albums with multiple discs are now organized into subfolders (e.g., `Disc 1/`, `CD 2/`) inside the downloaded ZIP.
- **Backend (`download_manager.py`):** `disc_total` is now computed dynamically by finding `max(disc_number)` across all tracks, since `discCount` from the API was unreliable (always defaulted to 1). Fields `disc_number` and `disc_total` added to `TrackProgress`.
- **Backend (`models.py`):** Added `disc_number: int = 0` and `disc_total: int = 0` to `TrackProgress` model.
- **Frontend (`app.js`):** ZIP assembly logic uses `Math.max(discNumbers)` to detect multi-disc albums. If multi-disc is detected and the setting is enabled, tracks are placed into subfolders like `Disc 1/`, `CD 2/` etc.
- **Frontend (`index.html`):** Added settings UI — checkbox to enable disc folders + dropdown to pick label format ("Disc", "CD", etc.)
- **Files modified:** `server/models.py`, `server/download_manager.py`, `web/js/app.js`, `web/index.html`

### 3. Feature: ZIP Naming Conventions
- **Albums:** ZIP filename is now `Album Name - Artist.zip` (includes artist)
- **Playlists:** ZIP filename is `Playlist Name.zip` (excludes artist since it's often "Unknown")
- **File modified:** `web/js/app.js`

### 4. Fix: Preview First-Click Failure (Auto-Retry)
First-time users experienced a "Preview failed" error on their first click after authenticating, but it worked on the second try.
- **Root cause:** Transient cold-start failure when the Apple Music API's first call through the WARP proxy fails.
- **Fix (`api_routes.py`):** Added auto-retry loop (max 2 attempts, 1s delay) on the `POST /preview` endpoint. `ValueError` (invalid URL) is thrown immediately without retrying. Retry is logged: `[Preview] First attempt failed (<error>), retrying in 1s…`
- **File modified:** `server/api_routes.py`

### 5. Fix/Investigation: WARP Proxy & DRM Decryption
Downloading with experimental codecs (AAC 256kbps 48kHz, ALAC, Atmos, etc.) initially failed with `ConnectionResetError: [Errno 104] Connection reset by peer` and `Invalid CKC error`.
- **Initial Theory:** We suspected the WARP proxy was blocking DRM connections to `play.itunes.apple.com` and CDN connections to `.mzstatic.com`, and initially added them to `NO_PROXY`.
- **Investigation:** We ran container-internal curl/python HTTP tests to `play.itunes.apple.com` via WARP (single GET, rapid GETs, large POST). ZERO failures occurred. The WARP proxy successfully handles Apple DRM traffic and is actually faster than direct EC2 routing. The CDN traffic was also severely slowed down when bypassing WARP.
- **Actual Root cause:** The `ConnectionResetError` was transient. The persistent download crash was actually caused by the missing `disc_number` field (fixed in #2).
- **Final Config (`NO_PROXY`):** Recreated the Docker container to only exclude localhost:
  ```
  NO_PROXY=localhost,127.0.0.1
  ```
  - DRM decryption (`play.itunes.apple.com`) → routes through WARP ✅
  - Media CDN (`.mzstatic.com`) → routes through WARP ✅
  - API browsing (`amp-api.music.apple.com`) → routes through WARP ✅
  - **Result:** Full IP masking is maintained against Apple servers, with optimal Cloudflare CDN download speeds.

### 6. Fix: Download Retry on Transient Connection Errors
Extended the download retry logic to handle transient connection errors, not just 429 rate limits.
- **Previously:** Only retried on `429` rate-limit errors (10s/30s/60s delays)
- **Now:** Also retries on `ConnectionResetError`, `ConnectionError`, `TimeoutError`, `OSError` with shorter delays (2s/5s/10s)
- **File modified:** `server/download_manager.py`

### 7. Fix: Rate Limit Too Aggressive (429 on Blob Downloads)
After a download completed, fetching track/lyrics/cover blobs hit `429 Too Many Requests`.
- **Root cause:** Rate limit was 30 req/min. A 3-track download fires 9+ save requests simultaneously (track + lyrics + cover × 3), plus system stats polling every 3s (~20/min). Easily exceeds 30/min.
- **Fix (`api_routes.py`):**
  - Increased `MAX_REQUESTS_PER_MINUTE` from 30 → 120
  - Removed `_check_rate_limit()` from 5 high-frequency endpoints: `/api/system/stats`, `/api/save/{job_id}/{track_index}`, `.../lyrics`, `.../cover`, `.../animated-artwork`
  - These endpoints still require auth tokens but no longer count against rate limiting
- **File modified:** `server/api_routes.py`

### 8. Maintenance: Disable Developer Tools Protection
- **Action:** Temporarily commented out the `disable-devtool` script in `index.html` for debugging the production site.
- **Update:** Once debugging concluded, the `disable-devtool` script was re-enabled and deployed.
- **File modified:** `web/index.html`

## Changes Made (March 10, 2026)

### 1. Feature: Custom File & Folder Naming Templates
Exposed the backend's existing template engine to the frontend via settings UI, allowing users to customize file and folder naming.
- **Frontend (`index.html`):** Added "Templates" settings group with 5 text inputs: Album Folder, Compilation Folder, Single-Disc File, Multi-Disc File, Playlist File
- **Frontend (`app.js`):** Added template fields to `DEFAULT_SETTINGS`, `setConfigFields()`, `getConfigFields()` — values persist in `localStorage` and are sent with each download/preview request
- **Available tokens:** `{title}`, `{artist}`, `{album}`, `{album_artist}`, `{track}`, `{disc}`, `{year}`, `{genre}`, `{playlist_title}`, `{playlist_artist}`. Use `{track:02d}` for zero-padded numbers.
- **Files modified:** `web/index.html`, `web/js/app.js`

### 2. Feature: Automatic Codec Fallback
When an experimental codec (Atmos, ALAC, etc.) fails to download, the app can automatically retry with a user-selected stable codec.
- **Backend (`config.py`):** Added `codec_fallback: str = ""` field — empty string = disabled, `"aac-legacy"` or `"aac-he-legacy"` for fallback
- **Backend (`download_manager.py`):** Two fallback paths — catches `GamdlError` (first attempt) and generic `Exception` (second attempt). On failure, swaps `config.song_codec` to the fallback value, rebuilds the downloader, and retries the track. If the fallback also fails, marks the track as errored with context.
- **Frontend (`index.html`):** Added "Codec Fallback" dropdown selector with options: "Disabled", "AAC 256kbps (Stable)", "AAC-HE 64kbps (Stable)"
- **Frontend (`app.js`):** Added `codec_fallback` to `DEFAULT_SETTINGS` and config field mappings
- **Files modified:** `server/config.py`, `server/models.py`, `server/download_manager.py`, `web/index.html`, `web/js/app.js`

### 3. Fix: ZIP Folder Structure Preservation
Downloaded ZIP files were flat (all files in root) despite naming templates defining folder structure.
- **Root cause:** Files are saved to a temp directory (`/tmp/gamdl_xxx/...`), not `config.output_path`. The previous `X-Relative-Path` header used `relative_to(output_path)` which always failed silently, falling back to the basename.
- **Fix:** Added `relative_path: str | None = None` to `TrackProgress` model. Computed from the job's temp directory (`self._job_temp_dirs.get(job_id)`) in all 5 code paths: main download loop, both codec fallback branches, single retry, and batch retry-all. Frontend reads `track.relative_path` from SSE job data for JSZip assembly.
- **Multi-disc subfolder support:** Re-integrated disc subfolder logic — when "Enable per-disc subfolders" is checked and the album has multiple discs, disc subfolders (e.g., `CD 1/`, `CD 2/`) are inserted between the album folder and the filename. Lyrics follow the same disc subfolder; covers get a copy in each disc folder.
- **Files modified:** `server/models.py`, `server/download_manager.py`, `web/js/app.js`

### 4. Feature: Built-in Audio Previews (30-Second Snippets)
Added inline 30-second audio previews in the track list, powered by Apple Music's preview URLs.
- **Backend (`models.py`):** Added `preview_url: str = ""` to `PreviewTrack`
- **Backend (`download_manager.py`):** Extracts `attributes.previews[0].url` from Apple Music API response for both single songs and album/playlist tracks
- **Frontend (`app.js`):**
  - Global audio manager (`stopPreviewAudio()`, `togglePreviewAudio()`) — singleton playback, only one preview at a time
  - Track list renders play ▶ / animated equalizer 🎵 / pause ⏸ button per track
  - `hidePreview()` calls `stopPreviewAudio()` for cleanup
- **Frontend (`style.css`):**
  - Apple Music-style hover: track number hides → play icon appears
  - Playing state: animated equalizer bars (3 bars, staggered `eqBounce` animation), pink accent highlight
  - Hover while playing: equalizer swaps to pause icon
  - Mobile: play buttons always visible (no hover on touch)
- **UX flow:** Hover track → ▶ appears → click to play → animated EQ bars show → hover again → ⏸ appears → click to stop. Clicking a different track auto-stops the current one.
- **Files modified:** `server/models.py`, `server/download_manager.py`, `web/js/app.js`, `web/css/style.css`

### 5. UI: Template Help Text Styling
- Updated the help text below template inputs to use `<strong>` tags for placeholder names, improving readability
- **File modified:** `web/index.html`

### 6. Feature: Custom Compressed File (ZIP) Naming Templates
Replaced the "Album Folder" and "Compilation Folder" naming templates with user-customizable **ZIP filename templates** for albums, single songs, and playlists.
- **Backend (`config.py`):** Blanked out `album_folder_template`, `compilation_folder_template`, and `no_album_folder_template` defaults so the gamdl library places files flat (no outer folder hierarchy). ZIP-level folder structure is now handled entirely by the frontend's disc-subfolder logic.
- **Frontend (`index.html`):** Removed "Album Folder" and "Compilation Folder" inputs. Added three new inputs under a "Compressed File Naming" sub-header: **Album ZIP Name** (`{album} - {album_artist}`), **Single Song ZIP Name** (`{title} - {album_artist}`), **Playlist ZIP Name** (`{playlist} - {album_artist}`). Existing "File Naming Inside ZIP" inputs (Single-Disc File, Multi-Disc File, Playlist File) retained under a separate sub-header.
- **Frontend (`app.js`):**
  - Added `_previewMediaType` state variable to track the current media type (`song`, `album`, `playlist`) from the preview API response.
  - Replaced `album_folder_template`/`compilation_folder_template` in `DEFAULT_SETTINGS` with `compressed_album_template`, `compressed_single_template`, `compressed_playlist_template`.
  - Updated `setConfigFields()` and `getConfigFields()` to map the new input IDs.
  - Rewrote ZIP naming logic in `prepareSaveLink()`: selects the correct template based on `_previewMediaType`, performs token replacement (`{album}`, `{album_artist}`, `{title}`, `{playlist}`, etc.), and automatically cleans up dangling separators when artist is unavailable (e.g. playlists without a curator).
- **Defaults:**
  - Album → `At Midnight - Elevation Worship.zip`
  - Single Song → `Gone - Elevation Worship.zip`
  - Playlist → `Ariana Grande Essentials.zip` (artist omitted if unknown)

### 7. Feature: Authentication Guide Links
Added a guide to the Authentication settings dialog to help users export their Apple Music cookies.
- **Frontend (`index.html`):** Added links to the Chrome and Firefox "export cookies" extensions inside the `.cookie-guide` container.
- **Frontend (`style.css`):** Added specific styling to make the guide visually distinct with a top border, muted text, and accented links.
- **Multi-disc & label customization:** Fully retained. Disc subfolders (`Disc 1/`, `CD 2/`, etc.) are still inserted by the frontend inside the ZIP.
- **Files modified:** `server/config.py`, `web/index.html`, `web/js/app.js`

## Changes Made (March 11, 2026)

### 1. UI: Authentication Section Redesign
Completely redesigned the Authentication settings area with a premium, card-based layout.
- **Status Card** (`auth-status-card`): Shield icon + "Connected" / "Not Connected" label with timestamp. Card background turns green (`rgba(52,199,89,0.08)`) when authenticated. Icon color changes to green.
- **Drag-and-Drop Zone** (`cookie-dropzone`): Dashed-border area with upload icon and "Drop cookies.txt here or click to browse" prompt. Supports both click-to-browse and drag-and-drop file upload. Border turns accent pink on hover/drag-over.
- **Action Buttons**: Icon-enhanced "Disconnect" and "Reconnect" buttons with SVG icons. Disconnect button hidden when not connected.
- **Cookie Guide**: Retained below the action buttons with links to Chrome/Firefox cookie export extensions.
- **JavaScript**: Replaced `#btn-upload-cookie` handler with dropzone click + drag-and-drop event listeners. Added `updateCookieStatus()` to manage both the dropzone status text and the status card state.
- **Files modified:** `web/index.html`, `web/css/style.css`, `web/js/app.js`

### 2. Fix: Cookie Upload First-Try Failure (Auto-Retry)
After uploading cookies.txt, the first `connectAuth()` call often failed with 401/network error due to a transient race condition (server needs time to register the token through the WARP proxy).
- **Fix (`app.js`):** Added a retry-with-delay mechanism — on first `connectAuth()` failure, waits 1.5 seconds and retries once before propagating the error.
- **File modified:** `web/js/app.js`

### 3. Fix: "Missing Authorization header" Error on Page Load
On startup, the app attempted to load downloads and connect SSE even when no token was stored, causing `Missing Authorization header` errors in the console.
- **Fix (`app.js`):** Guarded the downloads fetch (`loadDownloads()`) and SSE connection (`eventStream.connect()`) inside the `init()` function with an `AuthStorage.hasToken()` check. These only run when a token exists.
- **File modified:** `web/js/app.js`

### 4. Fix: `config.py` Type Errors (Lines 98 & 127)
- Fixed type errors on lines 98 and 127 of `server/config.py`.
- **File modified:** `server/config.py`

### 5. Fix: Empty Error Message on CORS Auth Failures
Cookie upload showed "Failed:" with no error message, and the toast said "Cookie parsing failed" with no useful context. Root cause: CORS responses return empty `statusText`, so the error message was an empty string.
- **Frontend (`api.js`):** Added fallback in `_fetch()` — when `res.statusText` is empty, uses `"Request failed (HTTP ${res.status})"` instead.
- **Frontend (`app.js`):** Updated the cookie upload error handler to always show a meaningful message. Falls back to `"Connection failed — try again"` if `err.message` is empty.
- **Files modified:** `web/js/api.js`, `web/js/app.js`

### 6. Fix: 502 Bad Gateway After Docker Rebuild
After rebuilding the Docker image and restarting `gamdl-app`, the site returned HTTP 502 from Caddy.
- **Root cause:** The `docker run` command used `--network host` instead of `--network container:warp-proxy`, AND was missing `-e PORT=7860`. The Dockerfile defaults to `ENV PORT=8000`, but the warp-proxy container owns the port mapping `0.0.0.0:7860→7860`. Without `-e PORT=7860`, the app listened on port 8000 inside the warp-proxy's network namespace, which nothing was mapped to.
- **Fix:** Recreated the container with the correct flags:
  ```
  docker run -d --name gamdl-app \
    --network container:warp-proxy \
    --restart unless-stopped \
    -v /home/ubuntu/gamdl-data:/root/.gamdl \
    -e PORT=7860 \
    -e HTTPS_PROXY=socks5h://127.0.0.1:9091 \
    -e HTTP_PROXY=socks5h://127.0.0.1:9091 \
    -e ALL_PROXY=socks5h://127.0.0.1:9091 \
    -e NO_PROXY=localhost,127.0.0.1 \
    gamdl-app
  ```
- **Key lesson:** Always include `-e PORT=7860` and `--network container:warp-proxy` when recreating the `gamdl-app` container. Never use `--network host`.

## Changes Made (March 14, 2026)

### 1. Fix: "No Space Left on Device" Error Under Concurrent Downloads
Multiple users downloading simultaneously caused disk space exhaustion and 100% CPU on the t3.micro EC2 instance. Root cause: temp directories (`/tmp/gamdl_*`) were never cleaned up after job completion, and old job data accumulated in memory indefinitely.

**Change 1: Immediate temp dir cleanup after job completion**
- Added `_cleanup_job(job_id)` method that removes the temp directory (`shutil.rmtree`) and clears in-memory caches (`_job_download_queues`, `_job_configs`, `_job_tasks`)
- In cloud mode (`CLOUD_MODE=true`): cleanup happens immediately after the download finishes (files already uploaded to R2)
- In non-cloud mode: cleanup is scheduled 15 minutes after completion (giving browser save dialogs time to finish)
- Cancelled and errored jobs are cleaned up immediately
- **File modified:** `server/download_manager.py`

**Change 2: Global concurrent download limit (max 2)**
- Added `asyncio.Semaphore(2)` to limit concurrent download jobs across all users
- When all slots are occupied, new downloads show: *"Download queued — the server is currently processing other downloads. Your download will start automatically when a slot opens up. Please keep this page open."*
- Downloads proceed automatically once a slot opens — no user action needed
- **File modified:** `server/download_manager.py`

**Change 3: Disk space pre-check**
- Before starting any download, checks `shutil.disk_usage('/tmp')` for minimum 200MB free space
- If insufficient, rejects the download with: *"Server disk space is running low. Please wait for current downloads to finish and try again."*
- **File modified:** `server/download_manager.py`

**Change 4: Stale job eviction (10-minute TTL)**
- Completed/cancelled/errored jobs are automatically evicted from memory after 10 minutes
- Triggered lazily when a new download is submitted (`submit_download()` calls `_evict_stale_jobs()`)
- Frees both temp dirs on disk and data in RAM
- **File modified:** `server/download_manager.py`

**Change 5: Stale user manager eviction (30-minute TTL)**
- Per-user `DownloadManager` instances are evicted if no API activity for 30+ minutes
- Triggered lazily in `_get_user_dm()` — never evicts the currently active user
- Cleans up any remaining temp directories before eviction
- **File modified:** `server/api_routes.py`

**Change 6: Faster cron-based temp dir cleanup**
- Reduced cron interval from 30 minutes → 5 minutes
- Reduced file age threshold from 60 minutes → 15 minutes
- Acts as a safety net for any temp dirs that in-code cleanup misses
- **File modified:** `start.sh`

### 2. Feature: Live Queue Position Number
When downloads are queued (semaphore full), the user now sees their exact position in the queue, updated live every 3 seconds.
- **Backend (`download_manager.py`):** Added `_waiting_jobs` list to track queued jobs. `_process_job()` appends the job to the list while waiting for a semaphore slot. A background task (`_update_position`) runs every 3s, recalculates each waiting job's position, and broadcasts an updated queue message via SSE.
- **Queue message:** *"Download queued (Position 2 in queue) — the server is currently processing other downloads. Your download will start automatically in just a moment. Please keep this page open."*
- **File modified:** `server/download_manager.py`

### 3. Fix: "Failed to fetch track 1 for saving: HTTP 404" in Cloud Mode
Downloads completed successfully but the frontend failed to fetch the track files, showing a 404 error toast.
- **Root cause:** `CLOUD_MODE=true` was set in the Dockerfile, but R2 storage credentials were not configured on the EC2 instance. `self._storage` was `None`, so files were never uploaded to R2. However, the cleanup code only checked `config.cloud_mode` (always `True`) and immediately deleted the temp directory, assuming files had been uploaded. The frontend then tried to fetch track files from disk → 404.
- **Fix:** Changed the immediate cleanup condition from `if config.cloud_mode:` to `if config.cloud_mode and self._storage:` — temp files are only deleted immediately when R2 is confirmed available and files were actually uploaded.
- **File modified:** `server/download_manager.py`

### 4. Feature: Event-Driven Cleanup (Frontend Signals Backend After Save)
Replaced timer-based cleanup with an event-driven approach: the frontend tells the backend when saving is complete, and the backend cleans up temp files immediately.
- **Flow:** Download finishes → Frontend fetches blobs → ZIP assembled → Browser save dialog fires → Frontend calls `POST /api/downloads/{jobId}/cleanup` → Backend deletes temp dir + frees memory instantly
- **Frontend (`api.js`):** Added `cleanupJob(jobId)` method — `POST /api/downloads/${jobId}/cleanup` with auth header
- **Frontend (`app.js`):** After `triggerSave()` and blob memory cleanup in `prepareSaveLink()`, calls `api.cleanupJob(job.job_id)` as fire-and-forget (`.catch()` logs warning but doesn't block)
- **Backend (`api_routes.py`):** Added `POST /downloads/{job_id}/cleanup` endpoint — validates token and job existence, calls `dm._cleanup_job(job_id)`, returns `{"status": "cleaned"}`
- **Files modified:** `web/js/api.js`, `web/js/app.js`, `server/api_routes.py`

### 5. Feature: Background Cleanup Loop (Safety Net)
Added a proactive background `asyncio` task that runs every 60 seconds, catching orphaned temp files from abandoned sessions (user closes browser, JS crashes, network loss, etc.).
- **Backend (`main.py`):** Added `_periodic_cleanup_loop()` — `asyncio.create_task()` in `lifespan()` startup, cancelled on shutdown. Calls `api_routes.run_periodic_cleanup()` every 60s with exception-safe `try/except`.
- **Backend (`api_routes.py`):** Added `run_periodic_cleanup()` function — iterates all `_user_managers`, calls `_evict_stale_jobs()` on each, then evicts stale user managers (inactive 30+ min) with full temp dir cleanup.
- **Files modified:** `server/main.py`, `server/api_routes.py`

### 6. Change: Stale Job TTL Reduced (10min → 5min)
- Reduced `_STALE_JOB_TTL` from 600 seconds (10 min) to 300 seconds (5 min)
- This TTL is now a safety net only — primary cleanup is event-driven from the frontend
- **File modified:** `server/download_manager.py`

## Changes Made (March 16, 2026)

### 1. Feature: Real-Time Download History & Global Counter (Firebase Firestore)
Added a "Recent Downloads" panel and a global download counter powered by Firebase Firestore, providing persistent, real-time tracking of all downloads across sessions and users.
- **Firebase project:** `amdlxd-history-9553f` (Firestore region: `asia-southeast1`), open security rules (anyone can read/write)
- **Frontend (`firebase-config.js`):** [NEW] Firebase SDK initialization. Reads config from `<meta>` tags (injected at build time) with hardcoded fallbacks for local dev. Exports `window.db` Firestore instance.
- **Frontend (`download-history.js`):** [NEW] Service layer with 5 global functions:
  - `addDownloadHistory(item)` — writes a record (title, artist, type, codec, date, serverTimestamp) to `download_history` collection
  - `subscribeToDownloadHistory(callback, max)` — real-time `onSnapshot` listener returning last N items, returns unsubscribe fn
  - `clearDownloadHistory()` — batch-deletes all documents
  - `incrementDownloadCount()` — atomic `FieldValue.increment(1)` on `stats/general.total_downloads`, auto-creates doc on first call
  - `subscribeToDownloadCount(callback)` — real-time listener on the counter
- **Frontend (`index.html`):** Added Firebase SDK v11.5.0 compat CDN scripts, Firebase config `<meta>` tags, `<script>` tags for new modules, "Recent Downloads" section HTML (header + list container), and download counter `<span>` in system stats bar (hidden until count > 0)
- **Frontend (`style.css`):** Added ~148 lines: `.history-section`, `.history-header`, `.history-item` (card layout matching `.job-card` design), `.history-badge` (type + codec pill badges with accent color), `.stat-downloads` (accent-colored counter), `historyFadeIn` animation
- **Frontend (`app.js`):**
  - Added DOM refs for history section elements
  - Added `getCodecLabel()` — maps codec values to human-readable labels (e.g. `aac-legacy` → `AAC 256kbps`)
  - Added `renderHistoryList(items)` — renders history items with title, artist, type badge, codec badge, and date
  - Integrated fire-and-forget Firestore writes in `prepareSaveLink()` after `triggerSave()` and `api.cleanupJob()` — records download metadata and increments global counter
  - Added real-time `onSnapshot` subscriptions in `init()` for both history (last 5 items) and counter
- **Build (`wrangler.jsonc`):** Added `FIREBASE_API_KEY`, `FIREBASE_PROJECT_ID`, `FIREBASE_APP_ID` to `vars` for Cloudflare Pages deployment
- **Build (`build.sh`):** Added Firebase config env var injection via `sed` (same pattern as existing `API_URL` injection)
- **Files modified:** `web/js/firebase-config.js` [NEW], `web/js/download-history.js` [NEW], `web/index.html`, `web/css/style.css`, `web/js/app.js`, `web/build.sh`, `wrangler.jsonc`

### 2. Bugfix: Firestore API Not Enabled
- The Cloud Firestore API was never enabled on the `amdlxd-history-9553f` project, causing all browser reads/writes to silently fail
- Also discovered the Firestore security rules were still set to the default `allow read, write: if false` (deny all), blocking all operations
- **Fix:** Enabled the API via Google Cloud Console, created the Firestore database in `asia-southeast1`, and published open security rules (`allow read, write: if true`) for `download_history/{doc}` and `stats/{doc}`

### 3. Bugfix: Missing Helper Functions in app.js
- `getCodecLabel()` and `renderHistoryList()` were not present in `app.js` despite the Firestore write code and subscription setup existing
- This caused silent failures: `typeof addDownloadHistory === 'function'` passed but `getCodecLabel()` was undefined, and `subscribeToDownloadHistory()` called `renderHistoryList()` which didn't exist
- **Fix:** Added both functions to `app.js` inside the IIFE, before `triggerSave()`
- **File modified:** `web/js/app.js`

### 4. Fix: History Item Title Overflow
- Long titles (e.g. "The Fate of Ophelia (Alone In My Tower Acoustic Version) - Single (Deluxe Edition/Live/Explicit)") overflowed the `.history-item` container and overlapped `.history-item-meta`
- Root cause: `.history-item-title` and `.history-item-artist` are `<span>` elements (inline by default) — `text-overflow: ellipsis` only works on block-level elements
- **Fix:** Added `display: block` to `.history-item-title` and `.history-item-artist`, and `overflow: hidden` to `.history-item-info`
- **File modified:** `web/css/style.css`

### 5. UI: Badges Moved Below Artist Name
- Moved `.history-badge.type-badge` and `.history-badge.codec-badge` from the `.history-item-meta` div (right side) into `.history-item-info` (below artist)
- New layout: Title → Artist → [Type] [Codec] on left, Date on right
- **File modified:** `web/js/app.js` (`renderHistoryList` template)

### 6. UI: Detailed Codec Labels
- Updated `getCodecLabel()` to show full codec detail matching the Settings dropdown labels:
  - `aac` → "AAC 256kbps 48kHz", `aac-he` → "AAC-HE 64kbps 48kHz"
  - `aac-legacy` → "AAC 256kbps", `aac-he-legacy` → "AAC-HE 64kbps"
  - `ac3` → "AC3 640kbps", `alac` → "ALAC Lossless", `atmos` → "Dolby Atmos"
- **File modified:** `web/js/app.js`

## Changes Made (March 19, 2026)

### 1. Fix: Authentication Failed, Token Not Found in index.js
- Apple restructured the Apple Music website, moving the Developer Token out of the legacy JavaScript bundle (`index-legacy~*.js`) and into the modern ES module bundle (`index~*.js`). They also changed the JWT header structure from `{"alg":...}` (Base64: `eyJh`) to `{"typ":"JWT","alg":...}` (Base64: `eyJ0eXAi`).
- **Fix (`apple_music_api.py`):** Updated the `_get_token()` method regex logic.
  - Now tries to find the modern bundle first (`assets/index~[^/"]+\.js`), falling back to the legacy bundle.
  - Updated the token regex prefix to match the new JWT header format (`(?=eyJ)(.*?)(?=")` instead of `eyJh`).
- **File modified:** `gamdl/api/apple_music_api.py`

## Changes Made (July 26, 2026)

### 1. Feature: Track Selection in Preview Phase
Users can now selectively choose which tracks from an album or playlist they want to download during the preview phase, rather than being forced to download everything.
- **Backend (`models.py`, `api_routes.py`):** Added `selected_tracks: list[int] | None` to the `DownloadRequest` model.
- **Backend (`download_manager.py`):** Added filtering logic in `submit_download()` to filter the API's track list based on the provided `selected_tracks` indices before processing.
- **Frontend (`app.js`, `style.css`):**
  - Replaced the default native browser checkboxes with custom SVG icon buttons.
  - Added a stateful toolbar above the tracklist:
    - **Default state**: "Select Tracks" SVG icon button.
    - **Edit state**: Select All, Deselect All, Cancel, and Confirm buttons (all SVG icon-only). Tracks that are unselected become visually dimmed.
    - **Confirmed state**: Shows the selected count (e.g. "3 / 5 tracks selected"), an Edit (pencil) icon button, and a Clear (X) icon button to revert to selecting all tracks.
- **Files modified:** `server/models.py`, `server/api_routes.py`, `server/download_manager.py`, `web/index.html`, `web/css/style.css`, `web/js/app.js`, `web/js/api.js`

### 2. Infrastructure: UI EC2 Deployment
- Successfully deployed backend server code and frontend UI updates (SVG UI elements) to the EC2 server (`16.176.205.50`) via SSH/SCP and rebuilt the Docker container.

## Changes Made (August 1, 2026)

### 1. Fix: Downloads Permanently Stuck in "Queued..." (Semaphore Deadlock)
All downloads were permanently stuck at "Queued..." status, never progressing to parsing or downloading.
- **Root cause:** The `asyncio.Semaphore(2)` concurrent download limit had both slots permanently held by zombie jobs. These jobs acquired the semaphore and then hung indefinitely inside `_process_job_inner()` — most likely at `get_download_queue()` which makes async API calls through the WARP proxy. With no timeout on the API calls, the hung `await` never completed, the semaphore was never released, and all subsequent downloads were queued forever.
- **Evidence from logs:** Multiple `POST /api/download` requests returned 200 but produced zero PARSING/DOWNLOADING/track-done log entries. Only cancellation logs appeared. The last successful track download was July 27; all Aug 1 downloads were zombie jobs.
- **Fix 1: 10-minute timeout on `_process_job_inner`** — Wrapped the inner download logic in `asyncio.wait_for(..., timeout=600)`. If the API hangs for 10 minutes, the job times out with a user-facing error message and the semaphore slot is released.
- **Fix 2: CancelledError handling during semaphore acquire** — Added explicit `try/except asyncio.CancelledError` around `_download_semaphore.acquire()`. If a job is cancelled while waiting for a slot (before acquiring the semaphore), it now cleans up properly instead of potentially leaking state.
- **Fix 3: Diagnostic logging** — Added `logger.info` at semaphore acquire/release transitions and at each stage of `_process_job_inner` (PARSING, URL parsed, PREPARING, download queue returned) to pinpoint where future hangs occur.
- **Immediate fix:** Restarted the Docker container to clear the stuck semaphore state.
- **File modified:** `server/download_manager.py`

## Changes Made (August 31, 2026)

### 1. Fix: AAC 256kbps 48kHz Stalling at "Downloading 50%" & Unreliable Wrapper Restart
Experimental FairPlay codecs (AAC 48kHz, ALAC) were freezing at 50% download progress indefinitely.
- **Root cause 1:** An interrupted download left a socket stuck in `CLOSE_WAIT` on decryption port `10020` in the Wrapper daemon.
- **Root cause 2:** The `/api/wrapper/restart` endpoint called `pkill -f wrapper`, but `pkill` was not installed in the slim container image, causing restart attempts to fail silently and spawn orphan processes while port 10020 remained blocked.
- **Root cause 3:** In `amdecrypt.py`, reading decrypted samples from the socket had no timeout, causing downloads to hang indefinitely rather than failing or triggering codec fallback.
- **Root cause 4:** `/api/wrapper/status` only checked HTTP port `30020`, showing a false green dot when port `10020` was frozen.
- **Fix 1 (`server/api_routes.py`):** Replaced `pkill` with Python `psutil` process termination to reliably kill all wrapper/main processes regardless of installed system packages. Reduced cooldown from 300s to 60s.
- **Fix 2 (`server/api_routes.py`):** Updated `wrapper_status()` to test both HTTP port `30020` and TCP socket connectivity to decrypt port `10020`.
- **Fix 3 (`gamdl/downloader/amdecrypt.py`):** Wrapped socket sample reads in `asyncio.wait_for(..., timeout=20.0)`. If the wrapper hangs, it fails fast and triggers codec fallback instead of deadlocking.
- **Files modified:** `server/api_routes.py`, `gamdl/downloader/amdecrypt.py`, `latest_changes_reference.md`

### 2. Feature: Self-Healing Wrapper Watchdog Background Loop
Implemented an autonomous health monitor in the server lifecycle to ensure zero-touch reliability for the Wrapper daemon.
- **Implementation (`server/main.py`):** Added `_wrapper_watchdog_loop()` running every 60 seconds. Tests both HTTP port 30020 and TCP decrypt port 10020 via `api_routes.check_wrapper_healthy()`.
- **Auto-Recovery (`server/api_routes.py`):** If 2 consecutive health checks fail, the watchdog triggers `api_routes.do_wrapper_restart()`, terminating zombie/deadlock processes with `psutil.send_signal(SIGKILL)`, reaping PID 1 child zombies, and spawning a fresh daemon without requiring user intervention.
- **Files modified:** `server/main.py`, `server/api_routes.py`, `latest_changes_reference.md`

### 3. Feature: Emergency 1GB Disk-Space Check & Proactive Cleanup
Prevents disk full crashes on the EC2 instance by verifying available storage before starting downloads.
- **Threshold (`server/download_manager.py`):** Updated `_MIN_FREE_DISK_BYTES` from 200MB to 1GB (`1024 * 1024 * 1024`).
- **Emergency Sweep (`server/download_manager.py`):** If free space in `/tmp` drops below 1GB, `_check_disk_space()` automatically invokes `_emergency_cleanup_tmp()`, pruning temp directories and orphan artwork files older than 2 minutes before re-checking. If space remains below 1GB, the job is cleanly rejected with a detailed message instead of causing an unhandled server crash.
- **File modified:** `server/download_manager.py`

### 4. Architecture: Container Init System with tini
Integrated `tini` into the Docker build to ensure proper process lifecycle management.
- **Zombie Process Reaping (`Dockerfile`):** Added `tini` to `apt-get install` and set `ENTRYPOINT ["/usr/bin/tini", "--"]`.
- **Signal Forwarding:** As PID 1 inside the container, `tini` reaps all child zombie processes (`<defunct>`) generated by wrapper restarts or child subprocesses, and handles OS termination signals (`SIGTERM`, `SIGINT`) cleanly.
- **File modified:** `Dockerfile`

### 5. Fix: Socket Connection & Teardown Timeouts in amdecrypt.py
Hardens the socket lifecycle when communicating with the Wrapper daemon.
- **Connection Timeout (`gamdl/downloader/amdecrypt.py`):** Added a 5.0s timeout to `asyncio.open_connection(host, port)`. Fails fast if the port is non-responsive.
- **Graceful Teardown Timeout (`gamdl/downloader/amdecrypt.py`):** In `finally:`, wrapped `writer.wait_closed()` in a 3.0s timeout to prevent lingering sockets from sticking in `CLOSE_WAIT` on the server.
- **File modified:** `gamdl/downloader/amdecrypt.py`

## Changes Made (September 1, 2026)

### 1. Codebase Bug Resolution Sweep (All 68 Findings from BUGS.md)
Systematically resolved, tested, and verified all 68 documented findings across security, functional breakage, medium stability, and code quality.
- **Critical Security (C1–C7):**
  - Authenticated and sanitized `GET /api/config` and `PUT /api/config` with sensitive key redaction (`r2_*`, `cookies_path`).
  - Anchored CORS regex in `server/main.py` strictly to `^https://([a-zA-Z0-9-]+\.)*gamdl\.pages\.dev$|^https://([a-zA-Z0-9-]+\.)*stormygenesis\.workers\.dev$`.
  - Added token protection and targeted process isolation to `/api/wrapper/restart`.
  - Guarded `/api/convert-m3u8` against SSRF with an Apple CDN host allowlist, concurrency semaphore (max 3), and 45s subprocess timeout.
  - Locked Firestore security rules to authenticated UIDs (`request.auth.uid == user_id`) and made `stats` collection read-only for clients.
  - Resolved Cloudflare Pages middleware password bypass and CSS interpolation injection in `functions/_middleware.js`.
- **High Severity Functional Breakage (H1–H19):**
  - Resolved `StreamInfoAv` media type mismatches in music video Widevine decryption.
  - Fixed unhandled stream formatting and populated `adamId`/`media_id` in DRM license requests across song and music video interfaces.
  - Fixed retry task queue miss references, concurrency slot corruption on watchdog semaphore release, and stale job TTL expansion (1800s).
  - Protected active user managers from eviction in multi-user mode.
  - Resolved TTML timestamp wrapping with `datetime.timedelta` parsing and preserved nested word-level lyric spans.
  - Corrected ISO-BMFF `tenc` offset calculation and enforced big-endian KID byte order in `downloader_song.py`.
- **Medium Severity & amdecrypt Box Parser (M1–M26):**
  - Rewrote ISO-BMFF box parser in `gamdl/downloader/amdecrypt.py` with hierarchical box-tree traversal scoped strictly to container bounds (`moov/trak/mdia/minf/stbl/stsd`), dynamic child header offsets (36 audio / 78 video), 64-bit `co64` chunk offset boxes (supporting files > 4 GiB), and explicit `ValueError` on truncated sample sizes.
  - Standardized configuration properties between CLI and server, enforced path containment before existence checks, and fixed OPTIONS preflight routing in `worker.js`.
  - Fixed preview checkbox event bubbling and eliminated duplicate event handlers in `web/js/app.js`.
- **Low Severity & UX Polish (L1–L16):**
  - Updated progress label from "Compressing" to "Packaging ${pct}%", aligned fraction calculation, and sequenced fallback downloads with delays.
  - Deduplicated cover image fetches per job and fixed `escapeHtml` to preserve `0`.
  - Enabled `.icon-pause` toggling in audio preview manager.
  - Enforced 450-document chunking for Firestore batch deletions.
  - Passed `silent=self.silent` to music video remux subprocesses and added warning logs for missing URL text files in CLI.
- **Files modified:** `server/api_routes.py`, `server/main.py`, `server/download_manager.py`, `gamdl/interface/interface.py`, `gamdl/interface/interface_song.py`, `gamdl/interface/interface_music_video.py`, `gamdl/interface/interface_uploaded_video.py`, `gamdl/downloader/downloader.py`, `gamdl/downloader/downloader_song.py`, `gamdl/downloader/downloader_music_video.py`, `gamdl/downloader/downloader_uploaded_video.py`, `gamdl/downloader/amdecrypt.py`, `gamdl/api/apple_music_api.py`, `gamdl/api/itunes_api.py`, `gamdl/api/exceptions.py`, `gamdl/cli/cli.py`, `gamdl/cli/cli_config.py`, `gamdl/cli/config_file.py`, `gamdl/cli/utils.py`, `web/js/app.js`, `web/js/download-history.js`, `web/js/events.js`, `firestore.rules`

### 2. Fix: Cloudflare Pages Proxy HTTP 502 (Bad Gateway)
- **Root cause:** `functions/api/[[path]].js` was forwarding `body: request.body` on all incoming requests including `GET` and `HEAD` methods (such as `GET /api/system/stats`), which violates the Fetch API specification and threw a runtime `TypeError` inside the Cloudflare runtime.
- **Fix:** Guarded request initialization so `body` is only attached when the HTTP method is not `GET`/`HEAD`. Also removed overriding the `Host` header to allow Cloudflare's edge runtime to resolve destination hostnames cleanly.
- **Files modified:** `functions/api/[[path]].js`, `src/worker.js`

### 3. Fix: Content Security Policy (CSP) Violations
- **Root cause:** `web/_headers` blocked required CDN scripts (`cdn.jsdelivr.net` for `hls.js` and `disable-devtool`, `storage.ko-fi.com` for Ko-Fi widget).
- **Fix:** Added `https://cdn.jsdelivr.net` and `https://storage.ko-fi.com` to `script-src`, enabled `frame-src 'self' https://ko-fi.com`, and configured caching headers.
- **File modified:** `web/_headers`

### 4. Database: Firestore Anonymous Auth & Composite Indexing
- **Rules:** Enforced strict per-user ownership on `/download_history/{doc}` matching `request.auth.uid == resource.data.user_id`.
- **Auth:** Initialized anonymous authentication in `firebase-config.js` with fallback error handling and timeout guards.
- **Indexing:** Created composite index in Firestore for collection `download_history` on fields `user_id` (Ascending) and `timestamp` (Descending) to support sorted real-time history streaming.
- **Files modified:** `firestore.rules`, `firestore.indexes.json`, `web/js/firebase-config.js`, `web/js/download-history.js`

### 5. Infrastructure: Git LFS Sync & Wrapper Process Architecture
- **Root cause:** Git cloned on EC2 without `git-lfs` installed, pulling text pointer files for `rootfs/system/bin/main` and `linker64` instead of actual binaries, which caused Linux to return `execve: Exec format error`.
- **Fix:** Installed `git-lfs` on the EC2 host and ran `git lfs pull`, syncing the complete 253MB binary rootfs into the container with recursive `chmod +x` permissions.
- **Healthcheck:** Updated `check_wrapper_healthy` in `server/api_routes.py` to recognize HTTP responses on port 30020 as active/healthy (preventing false offline statuses on non-200 responses) and verified ports 10020 and 30020 are live.
- **Files modified:** `server/api_routes.py`, `gamdl/api/apple_music_api.py`, `latest_changes_reference.md`

### 6. Feature: Direct Re-Download for Latest History Item (Single-File Server Retention)
- **Single-File Retention (`server/download_manager.py`):** When a download completes (single track or album/playlist ZIP), the finished bundle is retained in a dedicated per-user directory `/tmp/gamdl_latest_<token>/`. Any previously retained file is automatically purged so only 1 file is kept on the server.
- **Resumption Safety:** Does not alter `gamdl_cache_*` deterministic collection directories, preserving resumed track recovery for cancelled/retried downloads.
- **REST Endpoints (`server/api_routes.py`):** Added `GET /api/download/latest` for metadata check and `GET /api/download/latest/file` for direct file delivery.
- **Frontend Integration (`web/js/api.js`, `web/js/app.js`, `web/css/style.css`):** Attaches a direct Download button (`.btn-history-download`) strictly to the topmost (very first) item in **Recent Downloads**. When a new download starts, the direct download button is automatically detached from the previous item and attached to the new download once complete.
- **Files modified:** `server/download_manager.py`, `server/api_routes.py`, `web/js/api.js`, `web/js/app.js`, `web/css/style.css`, `latest_changes_reference.md`
