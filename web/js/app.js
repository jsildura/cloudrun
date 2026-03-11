/**
 * Main application logic for Gamdl Web.
 * Handles UI interactions, download orchestration, and real-time updates.
 */

(function () {
    'use strict';

    // ── DOM references ────────────────────────────────────────────────────

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const urlForm = $('#url-form');
    const urlInput = $('#url-input');
    const btnSubmit = $('#btn-submit');
    const btnSettings = $('#btn-settings');
    const btnInfo = $('#btn-info');
    const authBadge = $('#auth-badge');

    const queueSection = $('#queue-section');
    const queueList = $('#queue-list');

    // Status container
    const statusContainer = $('#status-container');

    // Preview section
    const previewSection = $('#preview-section');
    const previewCard = $('#preview-card');
    const previewArtwork = $('#preview-artwork');
    const previewTitle = $('#preview-title');
    const previewArtist = $('#preview-artist');
    const previewGenre = $('#preview-genre');
    const previewExplicit = $('#preview-explicit');
    const previewTracks = $('#preview-tracks');
    const previewFooter = $('#preview-footer');
    const previewDownloadBtn = $('#preview-download-btn');

    // Settings modal
    const modalSettings = $('#modal-settings');
    const btnSaveSettings = $('#btn-save-settings');
    const btnUploadCookie = $('#cookie-upload'); // dropzone is the clickable area
    const authStatusCard = $('#auth-status-card');
    const authStatusLabel = $('#auth-status-label');
    const authStatusDetail = $('#auth-status-detail');
    const cookieFile = $('#cookie-file');
    const cookieStatus = $('#cookie-status');
    const btnConnect = $('#btn-connect');
    const btnSignOut = $('#btn-sign-out');
    const wrapperCheckbox = $('#cfg-use-wrapper');
    const wrapperStatusDot = $('#wrapper-status');

    // Info modal
    const modalInfo = $('#modal-info');

    // State
    const jobs = {};
    let isSubmitting = false;
    let _previewUrl = null;     // URL currently shown in preview
    let _previewMediaType = null; // 'song', 'album', or 'playlist'
    let _activeJobId = null;    // Job ID linked to current preview
    const _trackBlobs = {};     // jobId → { trackIndex: { blob, filename } }
    const _blobPromises = {};   // jobId → { trackIndex: Promise }
    const _lyricsBlobs = {};    // jobId → { trackIndex: { blob, filename } }
    const _lyricsBlobPromises = {};  // jobId → { trackIndex: Promise }
    const _coverBlobs = {};     // jobId → { filename: { blob, filename } }
    const _coverBlobPromises = {};   // jobId → { filename: Promise }
    const _savedJobs = new Set(); // Jobs that already triggered auto-save
    const _activeJobs = new Set(); // Jobs started in THIS browser session (not replayed)

    // ── Audio Preview Manager ────────────────────────────────────────────
    let _previewAudio = null;       // Current HTMLAudioElement
    let _previewActiveBtn = null;   // Currently active play button element

    function stopPreviewAudio() {
        if (_previewAudio) {
            _previewAudio.pause();
            _previewAudio.src = '';
            _previewAudio = null;
        }
        if (_previewActiveBtn) {
            _previewActiveBtn.querySelector('.icon-play').style.display = '';
            _previewActiveBtn.querySelector('.icon-eq').style.display = 'none';
            _previewActiveBtn.closest('.preview-track-item')?.classList.remove('playing');
            _previewActiveBtn = null;
        }
    }

    function togglePreviewAudio(btn) {
        const url = btn.dataset.previewUrl;
        if (!url) return;

        // If same button is already playing, pause it
        if (_previewActiveBtn === btn && _previewAudio && !_previewAudio.paused) {
            stopPreviewAudio();
            return;
        }

        // Stop any currently playing preview
        stopPreviewAudio();

        // Start new preview
        _previewAudio = new Audio(url);
        _previewActiveBtn = btn;
        btn.querySelector('.icon-play').style.display = 'none';
        btn.querySelector('.icon-eq').style.display = '';
        btn.closest('.preview-track-item')?.classList.add('playing');

        _previewAudio.play().catch(() => stopPreviewAudio());
        _previewAudio.addEventListener('ended', () => stopPreviewAudio());
    }

    // Delegate click on preview track items (entire row is clickable)
    document.addEventListener('click', (e) => {
        const trackItem = e.target.closest('.preview-track-item.has-preview');
        if (!trackItem) return;
        const btn = trackItem.querySelector('.preview-play-btn');
        if (btn) {
            e.stopPropagation();
            togglePreviewAudio(btn);
        }
    });

    // ── LocalStorage settings ────────────────────────────────────────────
    const SETTINGS_KEY = 'gamdl_user_settings';

    // Default user preferences (matches the user's requested defaults)
    const DEFAULT_SETTINGS = {
        song_codec: 'aac-legacy',
        synced_lyrics_format: 'lrc',
        no_synced_lyrics: false,
        synced_lyrics_only: false,
        save_synced_lyrics: true,
        music_video_resolution: '720p',
        exclude_videos: false,
        cover_format: 'png',
        cover_size: 1200,
        save_cover: true,
        save_animated_artwork: false,
        overwrite: false,
        download_mode: 'ytdlp',
        remux_mode: 'ffmpeg',
        language: 'en-US',
        use_wrapper: false,
        rate_limit_delay: 7,
        disc_folder_enabled: true,
        disc_folder_label: 'Disc',
        codec_fallback: '',
        compressed_album_template: '{album} - {album_artist}',
        compressed_single_template: '{title} - {album_artist}',
        compressed_playlist_template: '{playlist} - {album_artist}',
        single_disc_file_template: '{track:02d} {title}',
        multi_disc_file_template: '{disc}-{track:02d} {title}',
        playlist_file_template: 'Playlists/{playlist_artist}/{playlist_title}',
    };

    /**
     * Load settings from localStorage, falling back to defaults.
     * Returns a plain object with all user preference keys.
     */
    function loadLocalSettings() {
        // Force folder templates to empty — ZIP naming is frontend-only now
        const FOLDER_OVERRIDES = {
            album_folder_template: '',
            compilation_folder_template: '',
            no_album_folder_template: '',
        };
        try {
            const raw = localStorage.getItem(SETTINGS_KEY);
            if (raw) {
                const saved = JSON.parse(raw);
                // Remove deprecated folder template keys (replaced by compressed file templates)
                delete saved.album_folder_template;
                delete saved.compilation_folder_template;
                delete saved.no_album_folder_template;
                // Merge saved on top of defaults so new keys get defaults
                return { ...DEFAULT_SETTINGS, ...saved, ...FOLDER_OVERRIDES };
            }
        } catch (e) {
            console.warn('[Settings] Failed to load from localStorage:', e);
        }
        return { ...DEFAULT_SETTINGS, ...FOLDER_OVERRIDES };
    }

    /**
     * Save settings to localStorage.
     */
    function saveLocalSettings(cfg) {
        try {
            localStorage.setItem(SETTINGS_KEY, JSON.stringify(cfg));
        } catch (e) {
            console.warn('[Settings] Failed to save to localStorage:', e);
        }
    }


    // ── Toast ─────────────────────────────────────────────────────────────

    function toast(message, type = 'info') {
        const container = $('#toast-container');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.textContent = message;
        container.appendChild(el);

        setTimeout(() => {
            el.classList.add('out');
            setTimeout(() => el.remove(), 300);
        }, 4000);
    }


    // ── Auth ──────────────────────────────────────────────────────────────

    function updateAuthBadge(status) {
        const badge = authBadge;
        const dot = badge.querySelector('.auth-dot');
        const text = badge.querySelector('.auth-text');

        badge.classList.remove('connected', 'restricted');

        if (status.authenticated && status.active_subscription) {
            badge.classList.add('connected');
            text.textContent = `Connected · ${status.storefront || 'Unknown'}`;
            // Only flag as restricted if explicit content is actually blocked
            const r = status.account_restrictions;
            const explicitBlocked = r && r.explicit && r.explicit.allowed === false;
            if (explicitBlocked) {
                badge.classList.add('restricted');
                text.textContent += ' (restricted)';
            }
        } else if (status.authenticated) {
            text.textContent = 'No active subscription';
        } else {
            text.textContent = 'Not connected';
        }

        // Show/hide sign out button based on token presence
        if (btnSignOut) {
            btnSignOut.style.display = AuthStorage.hasToken() ? '' : 'none';
        }
    }

    function updateCookieStatus() {
        if (!cookieStatus) return;
        if (AuthStorage.hasToken()) {
            const info = AuthStorage.getAuthInfo();
            const savedAt = info?.savedAt
                ? new Date(info.savedAt).toLocaleString()
                : 'unknown';
            cookieStatus.textContent = `Token saved (${savedAt})`;
            cookieStatus.classList.add('success');
            // Update status card
            if (authStatusCard) authStatusCard.classList.add('connected');
            if (authStatusLabel) authStatusLabel.textContent = 'Connected';
            if (authStatusDetail) authStatusDetail.textContent = `Token saved ${savedAt}`;
        } else {
            cookieStatus.textContent = '';
            cookieStatus.classList.remove('success');
            // Update status card
            if (authStatusCard) authStatusCard.classList.remove('connected');
            if (authStatusLabel) authStatusLabel.textContent = 'Not Connected';
            if (authStatusDetail) authStatusDetail.textContent = 'Upload cookies.txt to connect';
        }
    }

    async function checkAuth() {
        // Client-side token is the source of truth. If no token exists
        // in localStorage (e.g. after sign out), show "Not connected"
        // without querying the server — the server singleton may still
        // be authenticated from a previous session, but the client
        // has no credentials to send.
        if (!AuthStorage.hasToken()) {
            updateAuthBadge({ authenticated: false });
            updateCookieStatus();
            return;
        }

        try {
            const status = await api.getAuthStatus();
            updateAuthBadge(status);
        } catch (e) {
            updateAuthBadge({ authenticated: false });
        }
        updateCookieStatus();
    }


    // ── Modal management ──────────────────────────────────────────────────

    function openModal(id) {
        const modal = $(`#${id}`);
        if (modal) {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    }

    function closeModal(id) {
        const modal = $(`#${id}`);
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    }

    // Close modal on overlay click
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-overlay')) {
            e.target.classList.remove('active');
            document.body.style.overflow = '';
        }
        if (e.target.dataset.close) {
            closeModal(e.target.dataset.close);
        }
    });

    // Close modals with Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            $$('.modal-overlay.active').forEach((m) => {
                m.classList.remove('active');
            });
            document.body.style.overflow = '';
        }
    });


    // ── Settings ──────────────────────────────────────────────────────────

    async function loadSettings() {
        // Load from localStorage (no server call needed for user preferences)
        const cfg = loadLocalSettings();
        setConfigFields(cfg);
        // Check wrapper availability (non-blocking)
        checkWrapperStatus();
    }

    async function checkWrapperStatus() {
        const restartBtn = $('#btn-restart-wrapper');
        // Default to disabled while checking
        wrapperCheckbox.disabled = true;
        wrapperStatusDot.className = 'wrapper-status-dot';
        wrapperStatusDot.title = 'Checking...';
        if (restartBtn) restartBtn.style.display = 'none';

        try {
            const { available } = await api.getWrapperStatus();
            if (available) {
                wrapperCheckbox.disabled = false;
                wrapperStatusDot.className = 'wrapper-status-dot online';
                wrapperStatusDot.title = 'Wrapper is running';
                if (restartBtn) restartBtn.style.display = 'none';
            } else {
                wrapperCheckbox.disabled = true;
                wrapperStatusDot.className = 'wrapper-status-dot offline';
                wrapperStatusDot.title = 'Wrapper is not reachable';
                if (restartBtn) restartBtn.style.display = '';
            }
        } catch (e) {
            wrapperCheckbox.disabled = true;
            wrapperStatusDot.className = 'wrapper-status-dot offline';
            wrapperStatusDot.title = 'Wrapper is not reachable';
            if (restartBtn) restartBtn.style.display = '';
        }
    }

    async function restartWrapper() {
        const restartBtn = $('#btn-restart-wrapper');
        if (!restartBtn) return;

        // Show loading state
        restartBtn.disabled = true;
        restartBtn.classList.add('restarting');
        const originalHTML = restartBtn.innerHTML;
        restartBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="spin-icon">
                <polyline points="23 4 23 10 17 10"></polyline>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
            </svg>
            <span>Restarting...</span>
        `;

        try {
            const result = await api.restartWrapper();
            if (result.success) {
                toast('Wrapper successfully started, please refresh the page', 'success');
                // Hide button immediately to prevent repeated restarts
                restartBtn.style.display = 'none';
                restartBtn.disabled = false;
                restartBtn.classList.remove('restarting');
                restartBtn.innerHTML = originalHTML;
                return;
            } else if (result.message && result.message.includes('successfully started')) {
                // Wrapper process started but not yet responding — still hide button
                toast(result.message, 'success');
                restartBtn.style.display = 'none';
                restartBtn.disabled = false;
                restartBtn.classList.remove('restarting');
                restartBtn.innerHTML = originalHTML;
                return;
            } else {
                toast(result.message || 'Failed to restart wrapper', 'error');
            }
        } catch (e) {
            toast('Failed to restart wrapper: ' + e.message, 'error');
        }

        // Only re-check on failure
        restartBtn.disabled = false;
        restartBtn.classList.remove('restarting');
        restartBtn.innerHTML = originalHTML;
        await checkWrapperStatus();
    }

    function setConfigFields(cfg) {
        const map = {
            // Note: cookies_path removed — auth is now client-side via AuthStorage
            'cfg-song-codec': 'song_codec',
            'cfg-lyrics-format': 'synced_lyrics_format',
            'cfg-no-synced-lyrics': 'no_synced_lyrics',
            'cfg-synced-lyrics-only': 'synced_lyrics_only',
            'cfg-save-synced-lyrics': 'save_synced_lyrics',
            'cfg-mv-resolution': 'music_video_resolution',
            'cfg-exclude-videos': 'exclude_videos',
            'cfg-output-path': 'output_path',
            'cfg-cover-format': 'cover_format',
            'cfg-cover-size': 'cover_size',
            'cfg-save-cover': 'save_cover',
            'cfg-save-animated-artwork': 'save_animated_artwork',
            'cfg-overwrite': 'overwrite',
            'cfg-download-mode': 'download_mode',
            'cfg-remux-mode': 'remux_mode',
            'cfg-language': 'language',
            'cfg-use-wrapper': 'use_wrapper',
            'cfg-rate-limit-delay': 'rate_limit_delay',
            'cfg-disc-folder-enabled': 'disc_folder_enabled',
            'cfg-disc-folder-label': 'disc_folder_label',
            'cfg-codec-fallback': 'codec_fallback',
            'cfg-compressed-album-template': 'compressed_album_template',
            'cfg-compressed-single-template': 'compressed_single_template',
            'cfg-compressed-playlist-template': 'compressed_playlist_template',
            'cfg-single-disc-file-template': 'single_disc_file_template',
            'cfg-multi-disc-file-template': 'multi_disc_file_template',
            'cfg-playlist-file-template': 'playlist_file_template',
        };

        for (const [elId, key] of Object.entries(map)) {
            const el = $(`#${elId}`);
            if (!el || cfg[key] === undefined) continue;

            if (el.type === 'checkbox') {
                el.checked = cfg[key];
            } else {
                el.value = cfg[key];
            }
        }
    }

    function getConfigFields() {
        return {
            // Note: cookies_path removed — auth is now client-side via AuthStorage
            song_codec: $('#cfg-song-codec').value,
            synced_lyrics_format: $('#cfg-lyrics-format').value,
            no_synced_lyrics: $('#cfg-no-synced-lyrics').checked,
            synced_lyrics_only: $('#cfg-synced-lyrics-only').checked,
            save_synced_lyrics: $('#cfg-save-synced-lyrics').checked,
            music_video_resolution: $('#cfg-mv-resolution').value,
            exclude_videos: $('#cfg-exclude-videos').checked,
            cover_format: $('#cfg-cover-format').value,
            cover_size: parseInt($('#cfg-cover-size').value) || 1200,
            save_cover: $('#cfg-save-cover').checked,
            save_animated_artwork: $('#cfg-save-animated-artwork').checked,
            overwrite: $('#cfg-overwrite').checked,
            download_mode: $('#cfg-download-mode').value,
            remux_mode: $('#cfg-remux-mode').value,
            language: $('#cfg-language').value || undefined,
            use_wrapper: $('#cfg-use-wrapper').checked,
            rate_limit_delay: parseFloat($('#cfg-rate-limit-delay').value) || 2.0,
            disc_folder_enabled: $('#cfg-disc-folder-enabled')?.checked ?? true,
            disc_folder_label: $('#cfg-disc-folder-label')?.value || 'Disc',
            codec_fallback: $('#cfg-codec-fallback')?.value || '',
            compressed_album_template: $('#cfg-compressed-album-template')?.value || undefined,
            compressed_single_template: $('#cfg-compressed-single-template')?.value || undefined,
            compressed_playlist_template: $('#cfg-compressed-playlist-template')?.value || undefined,
            single_disc_file_template: $('#cfg-single-disc-file-template')?.value || undefined,
            multi_disc_file_template: $('#cfg-multi-disc-file-template')?.value || undefined,
            playlist_file_template: $('#cfg-playlist-file-template')?.value || undefined,
            // Force folder templates to empty — ZIP naming is now frontend-only
            album_folder_template: '',
            compilation_folder_template: '',
            no_album_folder_template: '',
        };
    }


    // ── Download queue rendering ──────────────────────────────────────────

    function getStageIcon(stage) {
        switch (stage) {
            case 'done': return '✓';
            case 'error': return '✗';
            case 'cancelled': return '—';
            case 'queued': return '·';
            default: return '↻';
        }
    }

    function getStageClass(stage) {
        switch (stage) {
            case 'done': return 'done';
            case 'error': return 'error';
            case 'downloading':
            case 'decrypting':
            case 'tagging':
            case 'preparing':
            case 'parsing':
                return 'downloading';
            default: return 'queued';
        }
    }

    function renderTrack(track, jobId, trackIndex) {
        const stageClass = getStageClass(track.stage);
        const stageIcon = getStageIcon(track.stage);
        const isActive = ['downloading', 'decrypting', 'tagging', 'preparing'].includes(track.stage);
        const progressWidth = track.stage === 'done' ? 100
            : isActive ? 50
                : 0;



        const retryBtn = (track.stage === 'error')
            ? `<button class="track-retry-btn" data-job-id="${jobId}" data-track-index="${trackIndex}" title="Retry">↻</button>`
            : '';

        return `
            <div class="track-item">
                <div class="track-cover">
                    ${track.cover_url ? `<img src="${track.cover_url}" alt="" loading="lazy">` : ''}
                </div>
                <div class="track-info">
                    <div class="track-title">${escapeHtml(track.title)}</div>
                    <div class="track-artist">${escapeHtml(track.artist)}${track.album ? ` — ${escapeHtml(track.album)}` : ''}</div>
                    ${isActive ? `
                        <div class="track-progress">
                            <div class="track-progress-bar" style="width: ${progressWidth}%"></div>
                        </div>
                    ` : ''}
                    ${track.error_message ? `<div class="track-artist" style="color: var(--error)">${escapeHtml(track.error_message)}</div>` : ''}
                </div>
                ${retryBtn}
                <div class="track-status-icon ${stageClass}" title="${track.stage}">
                    ${stageIcon}
                </div>
            </div>
        `;
    }

    function renderJob(job) {
        const existing = $(`[data-job-id="${job.job_id}"]`);

        if (existing) {
            // ── In-place update: avoid full DOM rebuild to prevent flicker ──
            const statusEl = existing.querySelector('.job-status');
            const statusLabel = job.stage === 'downloading'
                ? `${job.current_track}/${job.total_tracks}`
                : job.stage;
            if (statusEl) {
                statusEl.textContent = statusLabel;
                statusEl.className = `job-status ${job.stage}`;
            }

            // Update tracks in-place
            const tracksContainer = existing.querySelector('.job-tracks');
            if (tracksContainer && job.tracks.length) {
                // Get existing track items
                const existingTracks = tracksContainer.querySelectorAll('.track-item');

                job.tracks.forEach((track, i) => {
                    const newHtml = renderTrack(track, job.job_id, i);
                    if (existingTracks[i]) {
                        // Compare and only replace if changed
                        const temp = document.createElement('div');
                        temp.innerHTML = newHtml.trim();
                        const newEl = temp.firstElementChild;
                        if (existingTracks[i].innerHTML !== newEl.innerHTML) {
                            existingTracks[i].replaceWith(newEl);
                        }
                    } else {
                        // New track — append to tracks container
                        const temp = document.createElement('div');
                        temp.innerHTML = newHtml.trim();
                        tracksContainer.appendChild(temp.firstElementChild);
                    }
                });



                // Add/remove Retry All button
                const hasErrors = job.tracks.some(t => t.stage === 'error');
                const jobDoneOrError = ['done', 'error'].includes(job.stage);
                let retryAllDiv = tracksContainer.querySelector('.job-retry-all');
                if (hasErrors && jobDoneOrError && !retryAllDiv) {
                    tracksContainer.insertAdjacentHTML('beforeend',
                        `<div class="job-retry-all"><button class="btn-retry-all" data-job-id="${job.job_id}">↻ Retry All Failed</button></div>`
                    );
                    attachRetryAllHandler(existing, job.job_id);
                } else if ((!hasErrors || !jobDoneOrError) && retryAllDiv) {
                    retryAllDiv.remove();
                }
            }
            return;
        }

        // ── First render: create the card ──
        const tracksHtml = job.tracks.map((t, i) => renderTrack(t, job.job_id, i)).join('');
        const statusLabel = job.stage === 'downloading'
            ? `${job.current_track}/${job.total_tracks}`
            : job.stage;



        const hasErrors = job.tracks.some(t => t.stage === 'error');
        const retryAllBtn = hasErrors
            ? `<div class="job-retry-all"><button class="btn-retry-all" data-job-id="${job.job_id}">↻ Retry All Failed</button></div>`
            : '';

        const html = `
            <div class="job-card expanded" data-job-id="${job.job_id}">
                <div class="job-header">
                    <span class="job-url" title="${escapeHtml(job.url)}">${escapeHtml(job.url)}</span>
                    <span class="job-status ${job.stage}">${statusLabel}</span>
                </div>
                <div class="job-tracks">
                    ${tracksHtml || '<div class="track-item"><div class="track-info"><div class="track-title">Loading tracks…</div></div></div>'}
                    ${retryAllBtn}
                </div>
            </div>
        `;

        queueList.insertAdjacentHTML('afterbegin', html);

        // Attach listeners
        const card = $(`[data-job-id="${job.job_id}"]`);
        if (card) {
            card.querySelector('.job-header').addEventListener('click', () => {
                card.classList.toggle('expanded');
            });
            attachRetryAllHandler(card, job.job_id);
        }

    }



    function attachRetryAllHandler(card, jobId) {
        const retryAllBtn = card.querySelector('.btn-retry-all');
        if (retryAllBtn) {
            retryAllBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                retryAllBtn.disabled = true;
                retryAllBtn.textContent = 'Retrying…';
                try {
                    await api.retryAllFailed(jobId);
                    toast('Retrying all failed tracks…', 'info');
                } catch (err) {
                    toast('Retry failed: ' + err.message, 'error');
                    retryAllBtn.disabled = false;
                    retryAllBtn.textContent = '↻ Retry All Failed';
                }
            });
        }
    }

    // ── Blob storage & save helpers ─────────────────────────────────────

    /**
     * Fetch a single track's file as a Blob and store it in _trackBlobs.
     * Called as soon as SSE reports the track is done.
     * Returns a Promise that resolves when the blob is stored.
     */
    function fetchTrackBlob(jobId, trackIndex) {
        // Guard against duplicate fetches — return existing promise
        if (!_blobPromises[jobId]) _blobPromises[jobId] = {};
        if (_blobPromises[jobId][trackIndex]) return _blobPromises[jobId][trackIndex];

        const promise = (async () => {
            const maxRetries = 2;
            for (let attempt = 1; attempt <= maxRetries; attempt++) {
                try {
                    const token = AuthStorage.getToken();
                    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
                    const resp = await fetch(`/api/save/${jobId}/${trackIndex}`, { headers });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

                    const filename = resp.headers.get('X-Filename') || `track_${trackIndex}`;
                    const blob = await resp.blob();

                    if (!blob || blob.size === 0) {
                        throw new Error('Empty blob received');
                    }

                    if (!_trackBlobs[jobId]) _trackBlobs[jobId] = {};
                    _trackBlobs[jobId][trackIndex] = { blob, filename };
                    return; // Success — exit retry loop
                } catch (err) {
                    console.error(
                        `[App] Blob fetch failed for job=${jobId} track=${trackIndex} (attempt ${attempt}/${maxRetries}):`,
                        err
                    );
                    if (attempt < maxRetries) {
                        await new Promise(r => setTimeout(r, 2000));
                    } else {
                        toast(`Failed to fetch track ${trackIndex + 1} for saving: ${err.message}`, 'error');
                    }
                }
            }
        })();

        _blobPromises[jobId][trackIndex] = promise;
        return promise;
    }

    /**
     * Fetch a single track's synced lyrics file as a Blob.
     * Called when SSE reports the track is done and has a lyrics file.
     */
    function fetchLyricsBlob(jobId, trackIndex) {
        if (!_lyricsBlobPromises[jobId]) _lyricsBlobPromises[jobId] = {};
        if (_lyricsBlobPromises[jobId][trackIndex]) return _lyricsBlobPromises[jobId][trackIndex];

        const promise = (async () => {
            try {
                const token = AuthStorage.getToken();
                const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
                const resp = await fetch(`/api/save/${jobId}/${trackIndex}/lyrics`, { headers });
                if (!resp.ok) return; // No lyrics file — silently skip

                const filename = resp.headers.get('X-Filename') || `lyrics_${trackIndex}`;
                const blob = await resp.blob();

                if (!blob || blob.size === 0) return;

                if (!_lyricsBlobs[jobId]) _lyricsBlobs[jobId] = {};
                _lyricsBlobs[jobId][trackIndex] = { blob, filename };
            } catch (err) {
                console.warn(`[App] Lyrics blob fetch failed for job=${jobId} track=${trackIndex}:`, err);
            }
        })();

        _lyricsBlobPromises[jobId][trackIndex] = promise;
        return promise;
    }

    /**
     * Fetch a track's cover image file as a Blob.
     * Deduplicated by filename — all tracks in an album share the same cover.
     */
    function fetchCoverBlob(jobId, trackIndex) {
        if (!_coverBlobPromises[jobId]) _coverBlobPromises[jobId] = {};
        // Use trackIndex as key but deduplicate by filename later in prepareSaveLink
        if (_coverBlobPromises[jobId][trackIndex]) return _coverBlobPromises[jobId][trackIndex];

        const promise = (async () => {
            try {
                const token = AuthStorage.getToken();
                const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
                const resp = await fetch(`/api/save/${jobId}/${trackIndex}/cover`, { headers });
                if (!resp.ok) return; // No cover file — silently skip

                const filename = resp.headers.get('X-Filename') || `Cover`;
                const blob = await resp.blob();

                if (!blob || blob.size === 0) return;

                // Deduplicate: only store one blob per unique filename
                if (!_coverBlobs[jobId]) _coverBlobs[jobId] = {};
                if (!_coverBlobs[jobId][filename]) {
                    _coverBlobs[jobId][filename] = { blob, filename };
                }
            } catch (err) {
                console.warn(`[App] Cover blob fetch failed for job=${jobId} track=${trackIndex}:`, err);
            }
        })();

        _coverBlobPromises[jobId][trackIndex] = promise;
        return promise;
    }

    /**
     * Trigger native browser save dialog from an in-memory Blob.
     */
    function triggerSave(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

    /**
     * Auto-save completed job files.
     * Blobs are pre-fetched in background; once the job is done this function
     * waits for all blobs, optionally ZIP-compresses them, then triggers the
     * browser's native save dialog automatically — no extra click needed.
     */
    async function prepareSaveLink(job) {
        const isPreviewJob = previewSection.classList.contains('visible');
        const totalTracks = job.tracks ? job.tracks.length : 0;

        // Helper to update both card status and preview status together
        const card = $(`[data-job-id="${job.job_id}"]`);
        const statusEl = card?.querySelector('.job-status');

        function updateFetchStatus(text, pct) {
            if (statusEl) statusEl.textContent = text;
            if (isPreviewJob) {
                const progressBar = pct >= 0
                    ? `<div class="status-progress-bar processing"><div class="status-progress-fill" style="width:${pct}%"></div></div>`
                    : '';
                setStatus(`<span class="status-text">${escapeHtml(text)}</span>${progressBar}`);
            }
        }

        // Wait for all pending blob fetches with progress tracking
        const pending = _blobPromises[job.job_id];
        const pendingLyrics = _lyricsBlobPromises[job.job_id];
        const pendingCovers = _coverBlobPromises[job.job_id];
        const allPromises = [
            ...(pending ? Object.values(pending) : []),
            ...(pendingLyrics ? Object.values(pendingLyrics) : []),
            ...(pendingCovers ? Object.values(pendingCovers) : []),
        ];
        const totalFetches = allPromises.length;

        if (totalFetches > 1) {
            // Track progress as each blob resolves
            let fetchedCount = 0;
            updateFetchStatus(`Processing ${fetchedCount}/${totalTracks} tracks\u2026`, 0);

            const trackedPromises = allPromises.map(p =>
                p.then(() => {
                    fetchedCount++;
                    const pct = Math.round((fetchedCount / totalFetches) * 100);
                    // Show track count for audio, but total items count for the pct
                    const tracksFetched = Math.min(fetchedCount, totalTracks);
                    updateFetchStatus(`Processing ${tracksFetched}/${totalTracks} tracks\u2026`, pct);
                })
            );
            await Promise.all(trackedPromises);
        } else {
            // Single file or no files — just wait without granular progress
            if (totalFetches === 1) updateFetchStatus('Processing track\u2026', 50);
            await Promise.all(allPromises);
        }

        const jobBlobs = _trackBlobs[job.job_id];
        const blobCount = jobBlobs ? Object.keys(jobBlobs).length : 0;

        if (blobCount === 0) return; // Nothing to save

        // Collect all files (audio + lyrics + covers) into a single entries array
        const entries = Object.values(jobBlobs);
        const lyricsEntries = _lyricsBlobs[job.job_id]
            ? Object.values(_lyricsBlobs[job.job_id])
            : [];
        const coverEntries = _coverBlobs[job.job_id]
            ? Object.values(_coverBlobs[job.job_id])
            : [];

        // Fetch animated artwork MP4s if available
        const animatedArtworkEntries = [];
        const artPaths = job.animated_artwork_paths || [];
        const artUrls = job.animated_artwork_urls || [];
        for (let i = 0; i < Math.max(artPaths.length, artUrls.length); i++) {
            try {
                let resp;
                if (artUrls[i]) {
                    // Cloud mode: fetch from signed R2 URL
                    resp = await fetch(artUrls[i]);
                } else {
                    // Local mode: fetch from API
                    const token = AuthStorage.getToken();
                    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
                    resp = await fetch(`/api/save/${job.job_id}/animated-artwork/${i}`, { headers });
                }
                if (resp.ok) {
                    const filename = resp.headers.get('X-Filename') || `animated_cover_${i}.mp4`;
                    const blob = await resp.blob();
                    if (blob && blob.size > 0) {
                        animatedArtworkEntries.push({ blob, filename });
                    }
                }
            } catch (err) {
                console.warn(`[App] Animated artwork fetch failed for index ${i}:`, err);
            }
        }

        const allEntries = [...entries, ...lyricsEntries, ...coverEntries, ...animatedArtworkEntries];

        let finalBlob, finalFilename;

        if (allEntries.length === 1) {
            // ── Single file — save directly ──
            finalBlob = allEntries[0].blob;
            finalFilename = allEntries[0].filename;
        } else {
            // ── Multi-file — compress to ZIP in background ──
            if (typeof JSZip === 'undefined') {
                // Fallback: trigger individual save dialogs for each file
                for (const { blob, filename } of allEntries) {
                    triggerSave(blob, filename);
                }
                updateFetchStatus('Saved', -1);
                if (statusEl) statusEl.className = 'job-status done';
                // Clean up blobs from memory
                delete _trackBlobs[job.job_id];
                delete _blobPromises[job.job_id];
                delete _lyricsBlobs[job.job_id];
                delete _lyricsBlobPromises[job.job_id];
                delete _coverBlobs[job.job_id];
                delete _coverBlobPromises[job.job_id];
                return;
            }

            updateFetchStatus('Compressing 0%', 0);

            const zip = new JSZip();

            // Check if this is a multi-disc album by looking at track disc numbers
            const discNumbers = (job.tracks || []).map(t => t.disc_number || 1);
            const maxDiscNumber = Math.max(1, ...discNumbers);
            const userSettings = loadLocalSettings();
            const useDiscFolders = maxDiscNumber > 1 && userSettings.disc_folder_enabled;

            // Build a trackIndex → disc_number lookup
            const discMap = {};
            if (useDiscFolders) {
                for (const t of (job.tracks || [])) {
                    discMap[t.track_index] = t.disc_number || 1;
                }
            }

            const discLabel = userSettings.disc_folder_label || 'Disc';

            // Helper: get folder prefix from a track's relative path
            function _folderOf(relPath) {
                if (!relPath) return '';
                const lastSlash = relPath.replace(/\\/g, '/').lastIndexOf('/');
                return lastSlash >= 0 ? relPath.replace(/\\/g, '/').substring(0, lastSlash + 1) : '';
            }
            // Helper: get just the filename from a path
            function _filenameOf(relPath) {
                if (!relPath) return relPath;
                const lastSlash = relPath.replace(/\\/g, '/').lastIndexOf('/');
                return lastSlash >= 0 ? relPath.substring(lastSlash + 1) : relPath;
            }

            // Add audio entries with relative path from backend templates
            for (const [trackIdx, entry] of Object.entries(jobBlobs)) {
                const track = job.tracks?.[parseInt(trackIdx)];
                let zipPath = track?.relative_path || entry.filename;
                // Insert disc subfolder if enabled (e.g., "Artist/Album/CD 1/01 Track.m4a")
                if (useDiscFolders && track) {
                    const discNum = track.disc_number || 1;
                    const folder = _folderOf(zipPath);
                    const fname = _filenameOf(zipPath);
                    zipPath = `${folder}${discLabel} ${discNum}/${fname}`;
                }
                zip.file(zipPath, entry.blob);
            }

            // Add lyrics in the same folder as their corresponding track
            if (_lyricsBlobs[job.job_id]) {
                for (const [trackIdx, entry] of Object.entries(_lyricsBlobs[job.job_id])) {
                    const track = job.tracks?.[parseInt(trackIdx)];
                    const relPath = track?.relative_path;
                    let folder = relPath ? _folderOf(relPath) : '';
                    if (useDiscFolders && track) {
                        const discNum = track.disc_number || 1;
                        folder = `${folder}${discLabel} ${discNum}/`;
                    }
                    zip.file(folder + entry.filename, entry.blob);
                }
            }

            // Add covers — one copy per disc subfolder if enabled, otherwise in album folder
            const firstTrack = job.tracks?.[0];
            const coverFolder = firstTrack?.relative_path ? _folderOf(firstTrack.relative_path) : '';
            for (const entry of coverEntries) {
                if (useDiscFolders) {
                    const discs = new Set(discNumbers);
                    for (const d of discs) {
                        zip.file(`${coverFolder}${discLabel} ${d}/${entry.filename}`, entry.blob);
                    }
                } else {
                    zip.file(coverFolder + entry.filename, entry.blob);
                }
            }

            // Add animated artwork at root level
            for (const entry of animatedArtworkEntries) {
                zip.file(entry.filename, entry.blob);
            }

            finalBlob = await zip.generateAsync(
                { type: 'blob', compression: 'STORE' },
                (meta) => {
                    const pct = Math.round(meta.percent);
                    updateFetchStatus(`Compressing ${pct}%`, pct);
                }
            );

            // Build ZIP filename from user template based on media type
            const previewName = previewTitle?.textContent?.trim();
            const previewArtistName = previewArtist?.textContent?.trim();
            const first = job.tracks[0];
            const mediaType = _previewMediaType || (job.tracks.length === 1 ? 'song' : 'album');

            // Pick the right template
            let tpl;
            if (mediaType === 'song') {
                tpl = userSettings.compressed_single_template || DEFAULT_SETTINGS.compressed_single_template;
            } else if (mediaType === 'playlist') {
                tpl = userSettings.compressed_playlist_template || DEFAULT_SETTINGS.compressed_playlist_template;
            } else {
                tpl = userSettings.compressed_album_template || DEFAULT_SETTINGS.compressed_album_template;
            }

            // Build replacement map
            const albumArtist = previewArtistName && previewArtistName.toLowerCase() !== 'unknown' ? previewArtistName : '';
            const replacements = {
                '{title}': first?.title || previewName || '',
                '{artist}': first?.artist || albumArtist || '',
                '{album}': first?.album || previewName || '',
                '{album_artist}': albumArtist,
                '{playlist}': previewName || '',
                '{playlist_artist}': albumArtist,
            };

            let zipName = tpl;
            for (const [token, val] of Object.entries(replacements)) {
                zipName = zipName.split(token).join(val);
            }
            // Clean up dangling separators when artist is empty (e.g. " - ")
            zipName = zipName.replace(/\s*-\s*$/g, '').replace(/^\s*-\s*/g, '').trim();
            // Fallback if template produced empty string
            if (!zipName) zipName = previewName || first?.album || job.job_id;
            zipName = zipName.replace(/[<>:"/\\|?*]/g, '_').trim();
            finalFilename = `${zipName}.zip`;
        }

        // Auto-trigger browser save dialog
        triggerSave(finalBlob, finalFilename);

        // Update status to reflect saved state (no more processing animation)
        if (statusEl) {
            statusEl.textContent = 'Saved';
            statusEl.className = 'job-status done';
        }
        if (isPreviewJob) {
            setStatus(`<span class="status-text">${escapeHtml('Saved ' + finalFilename)}</span>`);
        }

        // Clean up blobs from memory
        delete _trackBlobs[job.job_id];
        delete _blobPromises[job.job_id];
        delete _lyricsBlobs[job.job_id];
        delete _lyricsBlobPromises[job.job_id];
        delete _coverBlobs[job.job_id];
        delete _coverBlobPromises[job.job_id];
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }


    // ── Preview helpers ───────────────────────────────────────────────────

    function formatDuration(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }

    function formatTotalDuration(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (hours > 0) return `${hours} hr ${minutes} min`;
        return `${minutes} min ${seconds} sec`;
    }

    function extractDominantColor(img) {
        try {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            const size = 64;
            canvas.width = size;
            canvas.height = size;
            ctx.drawImage(img, 0, 0, size, size);
            const data = ctx.getImageData(0, 0, size, size).data;

            // Collect pixel samples, skipping near-black and near-white
            const pixels = [];
            for (let i = 0; i < data.length; i += 16) { // sample every 4th pixel
                const r = data[i], g = data[i + 1], b = data[i + 2];
                const max = Math.max(r, g, b), min = Math.min(r, g, b);
                const lum = (max + min) / 2;
                if (lum > 20 && lum < 240) {
                    pixels.push([r, g, b]);
                }
            }

            if (pixels.length === 0) return { r: 100, g: 100, b: 100 };

            // Median-cut quantization into 8 buckets
            const buckets = medianCut(pixels, 3); // 2^3 = 8 buckets

            // Score each bucket: prefer saturated, mid-luminance colors
            let bestColor = buckets[0];
            let bestScore = -1;
            for (const bucket of buckets) {
                const [r, g, b] = bucket.color;
                const max = Math.max(r, g, b), min = Math.min(r, g, b);
                const lum = (max + min) / 2 / 255;
                const range = max - min;
                const sat = max === 0 ? 0 : range / max;
                // Prefer vivid, mid-brightness colors; weight by population
                const score = sat * (1 - Math.abs(lum - 0.45) * 1.5) * Math.sqrt(bucket.count);
                if (score > bestScore) {
                    bestScore = score;
                    bestColor = bucket;
                }
            }

            const [r, g, b] = bestColor.color;
            return { r, g, b };
        } catch (e) {
            console.warn('[Preview] Color extraction failed:', e);
            return { r: 100, g: 100, b: 100 };
        }
    }

    function medianCut(pixels, depth) {
        if (depth === 0 || pixels.length <= 1) {
            // Average the bucket
            let rSum = 0, gSum = 0, bSum = 0;
            for (const p of pixels) { rSum += p[0]; gSum += p[1]; bSum += p[2]; }
            const n = pixels.length || 1;
            return [{
                color: [Math.round(rSum / n), Math.round(gSum / n), Math.round(bSum / n)],
                count: n,
            }];
        }

        // Find the channel with the widest range
        let rMin = 255, rMax = 0, gMin = 255, gMax = 0, bMin = 255, bMax = 0;
        for (const [r, g, b] of pixels) {
            if (r < rMin) rMin = r; if (r > rMax) rMax = r;
            if (g < gMin) gMin = g; if (g > gMax) gMax = g;
            if (b < bMin) bMin = b; if (b > bMax) bMax = b;
        }
        const ranges = [rMax - rMin, gMax - gMin, bMax - bMin];
        const channel = ranges.indexOf(Math.max(...ranges));

        // Sort by widest channel and split at median
        pixels.sort((a, b) => a[channel] - b[channel]);
        const mid = Math.floor(pixels.length / 2);
        return [
            ...medianCut(pixels.slice(0, mid), depth - 1),
            ...medianCut(pixels.slice(mid), depth - 1),
        ];
    }

    function showPreview(data) {
        _previewUrl = data.url;
        _previewMediaType = data.media_type || null;

        // Populate header
        previewTitle.textContent = data.title;
        previewArtist.textContent = data.artist;

        const genreParts = [];
        if (data.genre) genreParts.push(escapeHtml(data.genre));
        if (data.year) genreParts.push(escapeHtml(data.year));

        const dolbySvg = '<svg class="format-badge-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1546 1070"><path fill="currentColor" d="m1546 1069.8h-155.9c-298.1 0-535.3-243.7-535.3-534.9 0-291.1 243.9-534.9 535.3-534.9h155.9zm-1546-1069.8h155.9c298.1 0 535.3 243.7 535.3 534.9 0 291.1-244 534.9-535.3 534.9h-155.9z"/></svg>';
        const losslessSvg = '<svg class="format-badge-icon lossless-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 9"><path fill="currentColor" d="M8.184,0.35C9.944,0.35 10.703,3.296 11.338,5.238C11.673,3.842 11.497,3.542 11.857,3.542C11.99,3.542 12.126,3.633 12.126,3.798C12.126,3.809 12.123,3.839 12.117,3.883L12.091,4.058C12.02,4.522 11.845,5.494 11.654,6.144C13.198,10.191 14.345,4.861 14.474,3.772C14.493,3.615 14.612,3.542 14.731,3.542C14.891,3.542 15.022,3.662 14.997,3.843C14.72,5.605 14.295,8.35 12.547,8.35C11.582,8.35 11.04,7.595 10.611,6.73C9.54,4.626 9.047,1.093 7.997,1.093C7.66,1.093 7.411,1.444 7.394,1.444C7.362,1.444 7.337,1.301 7.023,0.909C7.322,0.567 7.734,0.35 8.184,0.35ZM2.458,0.354C5.211,0.354 5.456,7.618 7.014,7.618C7.197,7.618 7.394,7.507 7.61,7.256C7.729,7.458 7.851,7.638 7.978,7.796C7.667,8.151 7.28,8.35 6.795,8.35C5.054,8.349 4.306,5.434 3.663,3.466C3.511,4.097 3.432,4.669 3.402,4.925C3.382,5.088 3.263,5.163 3.143,5.163C3.009,5.163 2.874,5.071 2.874,4.908L2.874,4.908L2.877,4.87C2.966,4.223 3.146,3.243 3.347,2.56C3.079,1.858 2.745,1.091 2.252,1.091C1.257,1.091 0.687,3.591 0.527,4.925C0.508,5.088 0.388,5.163 0.268,5.163C0.135,5.163 0,5.071 0,4.908C0,4.896 0.001,4.883 0.002,4.87C0.283,2.836 0.808,0.354 2.458,0.354ZM5.315,0.35C5.809,0.35 6.339,0.608 6.797,1.211C6.822,1.241 7.078,1.639 7.159,1.777C8.277,3.802 8.818,7.627 9.881,7.627C10.065,7.627 10.264,7.513 10.484,7.256C10.604,7.458 10.726,7.638 10.852,7.796C10.542,8.15 10.155,8.35 9.67,8.35C6.933,8.349 6.636,1.09 5.128,1.09C4.788,1.09 4.536,1.444 4.519,1.444C4.487,1.444 4.462,1.301 4.148,0.909C4.455,0.558 4.87,0.35 5.315,0.35Z"/></svg>';

        if (data.has_dolby_atmos) {
            genreParts.push(`<span class="format-badge">${dolbySvg} Dolby Atmos</span>`);
        }
        genreParts.push(`<span class="format-badge">${losslessSvg} Lossless</span>`);

        previewGenre.innerHTML = genreParts.join(' · ');
        previewExplicit.style.display = data.is_explicit ? '' : 'none';

        // Set artwork: prefer animated (video) over static (image)
        if (data.animated_artwork_url && typeof Hls !== 'undefined') {
            // Animated artwork — show looping silent video
            previewArtwork.style.display = 'none';

            // Remove any existing video
            const existingVideo = previewArtwork.parentElement.querySelector('.preview-artwork-video');
            if (existingVideo) existingVideo.remove();

            const video = document.createElement('video');
            video.className = 'preview-artwork preview-artwork-video';
            video.autoplay = true;
            video.loop = true;
            video.muted = true;
            video.playsInline = true;
            video.poster = data.artwork_url;
            video.setAttribute('crossorigin', 'anonymous');
            video.addEventListener('loadeddata', () => {
                const wrapper = previewArtwork.parentElement;
                wrapper.insertBefore(video, previewArtwork);
            });

            if (Hls.isSupported()) {
                const hls = new Hls({ enableWorker: false });
                hls.loadSource(data.animated_artwork_url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
                // Store for cleanup
                previewCard._hlsInstance = hls;
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                // Safari native HLS
                video.src = data.animated_artwork_url;
                video.addEventListener('loadedmetadata', () => video.play());
            }

            // Extract color from the static poster image
            const posterImg = new Image();
            posterImg.crossOrigin = 'anonymous';
            posterImg.onload = () => {
                const color = extractDominantColor(posterImg);
                previewCard.style.setProperty('--preview-bg', `rgba(${color.r},${color.g},${color.b},0.4)`);
            };
            posterImg.src = data.artwork_url;
        } else {
            // Static artwork — standard image
            // Remove any existing video
            const existingVideo = previewArtwork.parentElement.querySelector('.preview-artwork-video');
            if (existingVideo) existingVideo.remove();
            previewArtwork.style.display = '';

            previewArtwork.src = data.artwork_url;
            previewArtwork.onload = () => {
                const color = extractDominantColor(previewArtwork);
                previewCard.style.setProperty('--preview-bg', `rgba(${color.r},${color.g},${color.b},0.4)`);
            };
        }

        // Build track list
        const tracksHtml = data.tracks.map(t => {
            const hasPreview = !!t.preview_url;
            const playBtnHtml = hasPreview
                ? `<button class="preview-play-btn" data-preview-url="${escapeHtml(t.preview_url)}" title="Play 30s preview" aria-label="Play preview">
                       <svg class="icon-play" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,3 20,12 6,21"/></svg>
                       <svg class="icon-eq" viewBox="0 0 16 16" fill="currentColor" style="display:none"><rect class="eq-bar" x="1" y="6" width="3" rx="1" height="10"/><rect class="eq-bar" x="6.5" y="2" width="3" rx="1" height="14"/><rect class="eq-bar" x="12" y="4" width="3" rx="1" height="12"/></svg>
                       <svg class="icon-pause" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="3" width="4" height="18"/><rect x="15" y="3" width="4" height="18"/></svg>
                   </button>`
                : '';
            return `
            <div class="preview-track-item${hasPreview ? ' has-preview' : ''}">
                <div class="preview-track-num-wrap">
                    <span class="preview-track-num">${t.track_number}</span>
                    ${playBtnHtml}
                </div>
                <div class="preview-track-info">
                    <div class="preview-track-name">
                        ${t.is_video ? '<span class="video-badge" title="Music Video"><svg xmlns="http://www.w3.org/2000/svg" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" clip-rule="evenodd" viewBox="0 0 19 16" xml:space="preserve"><path fill-rule="nonzero" d="M16.747 12.437c1.166 0 1.753-.565 1.753-1.771V2.771C18.5 1.565 17.913 1 16.747 1H2.253C1.087 1 .5 1.565.5 2.771v7.895c0 1.206.587 1.771 1.753 1.771h14.494Zm-.02-1.109H2.273c-.47 0-.675-.193-.675-.675V2.791c0-.489.205-.682.675-.682h14.454c.47 0 .675.193.675.682v7.862c0 .482-.205.675-.675.675Zm-8.738-1.296c.976 0 1.637-.709 1.637-1.708V5.961c0-.255.055-.324.205-.359l1.603-.385c.327-.09.429-.159.429-.559v-1.35c0-.262-.095-.379-.457-.289l-1.991.503c-.341.082-.41.151-.41.558v3.107c0 .303-.027.358-.375.455l-.627.165c-.621.165-1.139.537-1.139 1.213 0 .585.436 1.012 1.125 1.012ZM13.828 15a.636.636 0 0 0 .627-.648.636.636 0 0 0-.627-.647H5.159a.642.642 0 0 0-.635.647c0 .359.287.648.635.648h8.669Z"></path></svg></span>' : ''}
                        <span class="preview-track-title-text">${escapeHtml(t.title)}</span>
                        ${t.is_explicit ? '<span class="explicit-badge inline-badge">E</span>' : ''}
                    </div>
                    ${data.media_type !== 'song' && t.artist !== data.artist
                    ? `<div class="preview-track-artist">${escapeHtml(t.artist)}</div>`
                    : ''}
                </div>
                <span class="preview-track-duration">${formatDuration(t.duration_ms)}</span>
            </div>
        `}).join('');
        previewTracks.innerHTML = tracksHtml;

        // Build footer
        const footerParts = [];
        if (data.release_date) footerParts.push(data.release_date);
        const songLabel = data.track_count === 1 ? '1 Song' : `${data.track_count} Songs`;
        footerParts.push(`${songLabel}, ${formatTotalDuration(data.total_duration_ms)}`);
        if (data.copyright) footerParts.push(data.copyright);
        previewFooter.innerHTML = footerParts.map(p => `<div>${escapeHtml(p)}</div>`).join('');

        // Show section
        previewSection.classList.add('visible');
        previewDownloadBtn.disabled = false;

        // Gray out input bar while preview is active
        urlInput.disabled = true;
        btnSubmit.disabled = true;
        if (btnPaste) btnPaste.disabled = true;
    }

    function hidePreview() {
        stopPreviewAudio();
        previewSection.classList.remove('visible');
        _previewUrl = null;
        _previewMediaType = null;
        _activeJobId = null;
        previewCard.style.removeProperty('--preview-bg');
        clearStatus();

        // Clean up animated artwork HLS player
        if (previewCard._hlsInstance) {
            previewCard._hlsInstance.destroy();
            previewCard._hlsInstance = null;
        }
        const existingVideo = previewCard.querySelector('.preview-artwork-video');
        if (existingVideo) existingVideo.remove();
        previewArtwork.style.display = '';

        // Re-enable input bar
        urlInput.disabled = false;
        btnSubmit.disabled = false;
        if (btnPaste) btnPaste.disabled = false;
    }

    function setStatus(html) {
        statusContainer.innerHTML = html;
    }

    function setStatusText(text) {
        statusContainer.innerHTML = `<span class="status-text">${escapeHtml(text)}</span>`;
    }

    function clearStatus() {
        statusContainer.innerHTML = '';
    }

    function updateStatusFromJob(job) {
        const stage = job.stage;
        const tracks = job.tracks || [];
        const total = tracks.length;


        if (stage === 'queued') {
            setStatusText('Queued...');
            return;
        }
        if (stage === 'parsing') {
            setStatusText('Parsing URL...');
            return;
        }
        if (stage === 'preparing' && total === 0) {
            setStatusText('Preparing...');
            return;
        }

        // Build per-track text list for preparing / downloading / done
        let headerText = '';
        let progressPct = -1; // -1 = no bar
        if (stage === 'preparing') {
            headerText = `Preparing tracks 1\u2013${total}...`;
        } else if (stage === 'downloading') {
            let doneCount = 0;
            let activeCount = 0;
            for (const t of tracks) {
                if (t.stage === 'done') doneCount++;
                else if (t.stage === 'downloading' || t.stage === 'decrypting' || t.stage === 'tagging') activeCount++;
            }
            // Each done track = 1 unit, each in-progress track = ~0.5 unit
            progressPct = total > 0 ? Math.round(((doneCount + activeCount * 0.5) / total) * 100) : 0;
            if (progressPct > 99 && doneCount < total) progressPct = 99;
            headerText = `Downloading ${progressPct}%`;
        } else if (stage === 'done') {
            headerText = 'Ready.';
            progressPct = 100;
        } else if (stage === 'error') {
            headerText = job.error_message || 'An error occurred.';
        } else if (stage === 'cancelled') {
            headerText = 'Cancelled.';
        }

        // Build track lines
        let trackLines = '';
        for (const t of tracks) {
            let icon = '';
            let cls = 'status-track';

            if (t.stage === 'done') {
                icon = '<span class="status-track-icon done">\u2713</span>';
                cls += ' done';
            } else if (t.stage === 'downloading' || t.stage === 'decrypting' || t.stage === 'tagging') {
                icon = '<span class="status-track-icon active">\u25CF</span>';
                cls += ' active';
            } else if (t.stage === 'error') {
                icon = '<span class="status-track-icon error">\u2717</span>';
                cls += ' error';
            } else {
                icon = '<span class="status-track-icon"></span>';
            }

            trackLines += `<div class="${cls}">${icon}<span class="status-track-name">${escapeHtml(t.title || `Track ${t.track_index + 1}`)}</span></div>`;
        }

        // Build progress bar HTML
        let progressBar = '';
        const isProcessing = (stage === 'downloading') || (stage === 'done');
        if (progressPct >= 0) {
            const processingClass = isProcessing ? ' processing' : '';
            progressBar = `<div class="status-progress-bar${processingClass}"><div class="status-progress-fill" style="width:${progressPct}%"></div></div>`;
        }

        // Build cancel link for active stages
        const isCancellable = ['queued', 'parsing', 'preparing', 'downloading'].includes(stage);
        const cancelHtml = isCancellable
            ? '<span class="status-cancel-text" id="status-cancel-text">Cancel</span>'
            : '';

        const html = `<span class="status-text">${escapeHtml(headerText)}</span>`
            + progressBar
            + cancelHtml
            + (trackLines ? `<div class="status-track-list">${trackLines}</div>` : '');
        setStatus(html);

        // Re-enable button on terminal states
        if (stage === 'done' || stage === 'error' || stage === 'cancelled') {
            previewDownloadBtn.disabled = false;
            _activeJobId = null;

            // Re-enable input bar
            urlInput.disabled = false;
            btnSubmit.disabled = false;
            if (btnPaste) btnPaste.disabled = false;
        }
    }


    // ── Event handlers ────────────────────────────────────────────────────

    // URL input change — clear preview when user types a new URL
    urlInput.addEventListener('input', () => {
        if (_previewUrl && urlInput.value.trim() !== _previewUrl) {
            hidePreview();
        }
    });

    // Paste button — read clipboard and validate Apple Music URL
    const btnPaste = $('#btn-paste');
    if (btnPaste) {
        btnPaste.addEventListener('click', async () => {
            try {
                const text = (await navigator.clipboard.readText()).trim();
                const appleMusicPattern = /^https?:\/\/music\.apple\.com\/.+\/(album|song|playlist|music-video|post)\//i;
                if (appleMusicPattern.test(text)) {
                    urlInput.value = text;
                    urlInput.dispatchEvent(new Event('input'));
                    urlInput.focus();
                } else {
                    toast('Clipboard does not contain an Apple Music URL', 'error');
                }
            } catch (err) {
                toast('Unable to read clipboard', 'error');
            }
        });
    }

    urlForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = urlInput.value.trim();
        if (!url || isSubmitting) return;

        isSubmitting = true;
        btnSubmit.disabled = true;
        if (btnPaste) btnPaste.disabled = true;
        btnSubmit.textContent = 'Loading…';
        setStatusText('Loading...');

        try {
            const userCfg = loadLocalSettings();
            const data = await api.previewUrl(url, userCfg);
            clearStatus();
            showPreview(data);
        } catch (e) {
            clearStatus();
            toast(e.message || 'Failed to load preview', 'error');
        } finally {
            isSubmitting = false;
            // Only re-enable if preview isn't active (e.g. on error)
            if (!previewSection.classList.contains('visible')) {
                btnSubmit.disabled = false;
                urlInput.disabled = false;
                if (btnPaste) btnPaste.disabled = false;
            }
            btnSubmit.textContent = 'Preview';
        }
    });

    // Preview download button — triggers actual download
    previewDownloadBtn.addEventListener('click', async () => {
        if (!_previewUrl) return;

        previewDownloadBtn.disabled = true;
        urlInput.disabled = true;
        btnSubmit.disabled = true;
        if (btnPaste) btnPaste.disabled = true;
        setStatusText('Starting download...');

        try {
            const userCfg = loadLocalSettings();
            const job = await api.startDownload(_previewUrl, userCfg);
            _activeJobs.add(job.job_id);
            _activeJobId = job.job_id;
            jobs[job.job_id] = job;
            renderJob(job);
            // Preview stays visible — status container shows progress
        } catch (e) {
            toast(e.message || 'Download failed', 'error');
            previewDownloadBtn.disabled = false;
            urlInput.disabled = false;
            btnSubmit.disabled = false;
            clearStatus();
        }
    });

    // Cancel text — delegated click handler on status container
    statusContainer.addEventListener('click', async (e) => {
        const cancelEl = e.target.closest('.status-cancel-text');
        if (!cancelEl || !_activeJobId) return;

        cancelEl.style.pointerEvents = 'none';
        cancelEl.style.opacity = '0.4';
        try {
            await api.cancelDownload(_activeJobId);
            toast('Download cancelled', 'info');
        } catch (err) {
            toast(err.message || 'Cancel failed', 'error');
        }
    });

    // Individual track retry buttons (delegated)
    queueList.addEventListener('click', async (e) => {
        // Individual track retry buttons
        const retryBtn = e.target.closest('.track-retry-btn');
        if (retryBtn) {
            e.preventDefault();
            e.stopPropagation();
            const jobId = retryBtn.dataset.jobId;
            const trackIndex = parseInt(retryBtn.dataset.trackIndex, 10);
            retryBtn.disabled = true;
            retryBtn.textContent = '...';
            try {
                await api.retryTrack(jobId, trackIndex);
                toast('Retrying track…', 'info');
            } catch (err) {
                toast('Retry failed: ' + err.message, 'error');
                retryBtn.disabled = false;
                retryBtn.textContent = '↻';
            }
            return;
        }
    });

    // Settings button
    btnSettings.addEventListener('click', () => {
        loadSettings();
        openModal('modal-settings');
    });

    // Info button
    btnInfo.addEventListener('click', () => {
        openModal('modal-info');
    });

    // Save settings
    btnSaveSettings.addEventListener('click', async () => {
        try {
            const cfg = getConfigFields();
            saveLocalSettings(cfg);
            toast('Settings saved', 'success');
            closeModal('modal-settings');
        } catch (e) {
            toast(e.message || 'Failed to save settings', 'error');
        }
    });

    // Restore defaults
    const btnRestoreDefaults = $('#btn-restore-defaults');
    if (btnRestoreDefaults) {
        btnRestoreDefaults.addEventListener('click', () => {
            // Reset form fields to defaults
            setConfigFields(DEFAULT_SETTINGS);
            // Save defaults to localStorage immediately
            saveLocalSettings(DEFAULT_SETTINGS);
            toast('Settings restored to defaults', 'info');
        });
    }

    // Cookie file upload — click dropzone to browse
    btnUploadCookie.addEventListener('click', (e) => {
        // Don't re-trigger if clicking the file input itself
        if (e.target === cookieFile) return;
        cookieFile.click();
    });

    // Drag-and-drop support on the dropzone
    const dropzone = btnUploadCookie;
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) {
            // Simulate file input change
            const dt = new DataTransfer();
            dt.items.add(file);
            cookieFile.files = dt.files;
            cookieFile.dispatchEvent(new Event('change'));
        }
    });

    cookieFile.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        cookieStatus.textContent = 'Parsing cookies…';
        cookieStatus.classList.remove('success');

        try {
            // Parse the cookies.txt file entirely in the browser
            const token = await AuthStorage.parseCookiesFromFile(file);

            if (!token) {
                throw new Error(
                    'media-user-token not found. Make sure the cookies.txt is '
                    + 'from music.apple.com and you are logged in.'
                );
            }

            // Save token to localStorage
            AuthStorage.save(token);

            // Validate token against the server (retry once on failure)
            let result;
            try {
                result = await api.connectAuth();
            } catch {
                // Server may need a moment to register — retry after a short delay
                await new Promise(r => setTimeout(r, 1500));
                result = await api.connectAuth();
            }
            updateAuthBadge(result);
            updateCookieStatus();
            toast('Authenticated successfully', 'success');
            // Start/restart SSE now that we have a valid token
            eventStream.connect();
        } catch (err) {
            cookieStatus.textContent = `Failed: ${err.message}`;
            cookieStatus.classList.remove('success');
            toast(err.message || 'Cookie parsing failed', 'error');
        }

        // Reset file input so the same file can be re-selected
        cookieFile.value = '';
    });

    // Connect button — validate stored token against Apple Music API
    btnConnect.addEventListener('click', async () => {
        if (!AuthStorage.hasToken()) {
            toast('No token found, add cookies.txt first', 'error');
            return;
        }

        const originalHTML = btnConnect.innerHTML;
        try {
            btnConnect.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg> Connecting…`;
            btnConnect.disabled = true;
            const result = await api.connectAuth();
            updateAuthBadge(result);
            updateCookieStatus();
            toast('Connected successfully', 'success');
            // Start/restart SSE now that we have a valid token
            eventStream.connect();
        } catch (e) {
            toast(e.message || 'Connection failed', 'error');
        } finally {
            btnConnect.innerHTML = originalHTML;
            btnConnect.disabled = false;
        }
    });

    // Sign out — clear stored token
    if (btnSignOut) {
        btnSignOut.addEventListener('click', () => {
            AuthStorage.clear();
            updateAuthBadge({ authenticated: false });
            updateCookieStatus();
            toast('Signed out', 'info');
        });
    }

    // Restart Wrapper
    const btnRestartWrapper = $('#btn-restart-wrapper');
    if (btnRestartWrapper) {
        btnRestartWrapper.addEventListener('click', () => {
            restartWrapper();
        });
    }


    // ── SSE Event Stream ───────────────────────────────────────────────────

    eventStream.on('job_created', (data) => {
        _activeJobs.add(data.job_id);  // Mark new jobs as active
        jobs[data.job_id] = data;
        renderJob(data);
    });

    eventStream.on('job_update', (data) => {
        const prevJob = jobs[data.job_id];
        jobs[data.job_id] = data;
        renderJob(data);

        // Update status container for the job linked to the current preview
        if (data.job_id === _activeJobId) {
            updateStatusFromJob(data);
        }

        // Only process blob fetching and auto-save for jobs started in this session
        if (!_activeJobs.has(data.job_id)) return;

        // Fetch blob for each track that just completed
        if (data.tracks) {
            data.tracks.forEach((track, i) => {
                const prevTrack = prevJob?.tracks?.[i];
                if (track.stage === 'done' && track.file_path && prevTrack?.stage !== 'done') {
                    fetchTrackBlob(data.job_id, i);
                    // Also fetch lyrics file if available
                    if (track.synced_lyrics_file_path) {
                        fetchLyricsBlob(data.job_id, i);
                    }
                    // Also fetch cover file if available
                    if (track.cover_file_path) {
                        fetchCoverBlob(data.job_id, i);
                    }
                }
            });
        }

        // Prepare native download link when entire job is done
        if (data.stage === 'done' && !_savedJobs.has(data.job_id)) {
            _savedJobs.add(data.job_id);
            prepareSaveLink(data);
        } else if (data.stage === 'error') {
            toast(`Error: ${data.error_message || 'Unknown error'}`, 'error');
        }
    });

    eventStream.on('connected', () => {
        console.log('[App] SSE connected');
    });

    eventStream.on('disconnected', () => {
        console.log('[App] SSE disconnected');
    });

    eventStream.on('connection_lost', () => {
        toast('Connection lost. Please refresh.', 'error');
    });


    // ── System Stats ─────────────────────────────────────────────────────

    const statCpu = $('#stat-cpu');
    const statRam = $('#stat-ram');
    const statSwap = $('#stat-swap');

    function applyStatClass(el, percent) {
        el.classList.remove('stat-warning', 'stat-danger');
        if (percent >= 95) el.classList.add('stat-danger');
        else if (percent >= 80) el.classList.add('stat-warning');
    }

    async function fetchSystemStats() {
        const s = await api.getSystemStats();
        if (!s) return;

        statCpu.textContent = `CPU: ${Math.round(s.cpu_percent)}%`;
        statRam.textContent = `RAM: ${s.ram_used_mb}/${s.ram_total_mb} MB`;
        statSwap.textContent = `SWAP: ${s.swap_used_mb}/${s.swap_total_mb} MB`;

        applyStatClass(statCpu, s.cpu_percent);
        applyStatClass(statRam, s.ram_percent);
        applyStatClass(statSwap, s.swap_percent);
    }

    // Poll every 3 seconds
    setInterval(fetchSystemStats, 3000);


    // ── Init ──────────────────────────────────────────────────────────────

    async function init() {
        // Check auth status
        await checkAuth();

        // Only load downloads & connect SSE if authenticated
        if (AuthStorage.hasToken()) {
            // Load existing downloads
            try {
                const existingJobs = await api.getDownloads();
                for (const job of existingJobs) {
                    jobs[job.job_id] = job;
                    renderJob(job);
                    // Mark completed jobs so they don't trigger auto-download on SSE reconnect
                    if (job.stage === 'done') {
                        _savedJobs.add(job.job_id);
                    }
                }
            } catch (e) {
                console.error('Failed to load downloads:', e);
            }

            // Connect SSE event stream
            eventStream.connect();
        }

        // Fetch system stats immediately
        fetchSystemStats();

        // Focus input
        urlInput.focus();
    }

    // Start when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
