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
    const btnUploadCookie = $('#btn-upload-cookie');
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
    let _activeJobId = null;    // Job ID linked to current preview
    const _trackBlobs = {};     // jobId → { trackIndex: { blob, filename } }
    const _blobPromises = {};   // jobId → { trackIndex: Promise }
    const _lyricsBlobs = {};    // jobId → { trackIndex: { blob, filename } }
    const _lyricsBlobPromises = {};  // jobId → { trackIndex: Promise }
    const _coverBlobs = {};     // jobId → { filename: { blob, filename } }
    const _coverBlobPromises = {};   // jobId → { filename: Promise }
    const _savedJobs = new Set(); // Jobs that already triggered auto-save
    const _activeJobs = new Set(); // Jobs started in THIS browser session (not replayed)


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
            if (status.account_restrictions) {
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
        } else {
            cookieStatus.textContent = 'No token — upload cookies.txt';
            cookieStatus.classList.remove('success');
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
        try {
            const cfg = await api.getConfig();
            setConfigFields(cfg);
        } catch (e) {
            console.error('Failed to load config:', e);
        }
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
                toast('Wrapper restarted successfully', 'success');
            } else {
                toast(result.message || 'Failed to restart wrapper', 'error');
            }
        } catch (e) {
            toast('Failed to restart wrapper: ' + e.message, 'error');
        }

        // Re-check status
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
            'cfg-output-path': 'output_path',
            'cfg-cover-format': 'cover_format',
            'cfg-cover-size': 'cover_size',
            'cfg-save-cover': 'save_cover',
            'cfg-overwrite': 'overwrite',
            'cfg-download-mode': 'download_mode',
            'cfg-remux-mode': 'remux_mode',
            'cfg-language': 'language',
            'cfg-use-wrapper': 'use_wrapper',
            'cfg-rate-limit-delay': 'rate_limit_delay',
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
            cover_format: $('#cfg-cover-format').value,
            cover_size: parseInt($('#cfg-cover-size').value) || 1200,
            save_cover: $('#cfg-save-cover').checked,
            overwrite: $('#cfg-overwrite').checked,
            download_mode: $('#cfg-download-mode').value,
            remux_mode: $('#cfg-remux-mode').value,
            language: $('#cfg-language').value || undefined,
            use_wrapper: $('#cfg-use-wrapper').checked,
            rate_limit_delay: parseFloat($('#cfg-rate-limit-delay').value) || 2.0,
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
            updateFetchStatus(`Fetching ${fetchedCount}/${totalTracks} tracks\u2026`, 0);

            const trackedPromises = allPromises.map(p =>
                p.then(() => {
                    fetchedCount++;
                    const pct = Math.round((fetchedCount / totalFetches) * 100);
                    // Show track count for audio, but total items count for the pct
                    const tracksFetched = Math.min(fetchedCount, totalTracks);
                    updateFetchStatus(`Fetching ${tracksFetched}/${totalTracks} tracks\u2026`, pct);
                })
            );
            await Promise.all(trackedPromises);
        } else {
            // Single file or no files — just wait without granular progress
            if (totalFetches === 1) updateFetchStatus('Fetching track\u2026', 50);
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
        const allEntries = [...entries, ...lyricsEntries, ...coverEntries];

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
            for (const { blob, filename } of allEntries) {
                zip.file(filename, blob);
            }

            finalBlob = await zip.generateAsync(
                { type: 'blob', compression: 'STORE' },
                (meta) => {
                    const pct = Math.round(meta.percent);
                    updateFetchStatus(`Compressing ${pct}%`, pct);
                }
            );

            // Build ZIP filename from first track metadata
            const first = job.tracks[0];
            let zipName = job.job_id;
            if (first?.album && first?.artist) zipName = `${first.album} - ${first.artist}`;
            else if (first?.album) zipName = first.album;
            else if (first?.artist) zipName = first.artist;
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
            canvas.width = 50;
            canvas.height = 50;
            ctx.drawImage(img, 0, 0, 50, 50);
            const data = ctx.getImageData(10, 10, 30, 30).data;
            let r = 0, g = 0, b = 0, count = 0;
            for (let i = 0; i < data.length; i += 4) {
                r += data[i];
                g += data[i + 1];
                b += data[i + 2];
                count++;
            }
            r = Math.round(r / count);
            g = Math.round(g / count);
            b = Math.round(b / count);
            return { r, g, b };
        } catch (e) {
            console.warn('[Preview] Color extraction failed:', e);
            return { r: 100, g: 100, b: 100 };
        }
    }

    function showPreview(data) {
        _previewUrl = data.url;

        // Populate header
        previewTitle.textContent = data.title;
        previewArtist.textContent = data.artist;

        const genreParts = [];
        if (data.genre) genreParts.push(data.genre);
        if (data.year) genreParts.push(data.year);
        previewGenre.textContent = genreParts.join(' · ');
        previewExplicit.style.display = data.is_explicit ? '' : 'none';

        // Set artwork and extract dominant color on load
        previewArtwork.src = data.artwork_url;
        previewArtwork.onload = () => {
            const color = extractDominantColor(previewArtwork);
            previewCard.style.setProperty('--preview-bg', `rgba(${color.r},${color.g},${color.b},0.4)`);
        };

        // Build track list
        const tracksHtml = data.tracks.map(t => `
            <div class="preview-track-item">
                <span class="preview-track-num">${t.track_number}</span>
                <div class="preview-track-info">
                    <div class="preview-track-name">
                        <span class="preview-track-title-text">${escapeHtml(t.title)}</span>
                        ${t.is_explicit ? '<span class="explicit-badge inline-badge">E</span>' : ''}
                    </div>
                    ${data.media_type !== 'song' && t.artist !== data.artist
                ? `<div class="preview-track-artist">${escapeHtml(t.artist)}</div>`
                : ''}
                </div>
                <span class="preview-track-duration">${formatDuration(t.duration_ms)}</span>
            </div>
        `).join('');
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
    }

    function hidePreview() {
        previewSection.classList.remove('visible');
        _previewUrl = null;
        _activeJobId = null;
        previewCard.style.removeProperty('--preview-bg');
        clearStatus();

        // Re-enable input bar
        urlInput.disabled = false;
        btnSubmit.disabled = false;
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

        const html = `<span class="status-text">${escapeHtml(headerText)}</span>`
            + progressBar
            + (trackLines ? `<div class="status-track-list">${trackLines}</div>` : '');
        setStatus(html);

        // Re-enable button on terminal states
        if (stage === 'done' || stage === 'error' || stage === 'cancelled') {
            previewDownloadBtn.disabled = false;
            _activeJobId = null;

            // Re-enable input bar
            urlInput.disabled = false;
            btnSubmit.disabled = false;
        }
    }


    // ── Event handlers ────────────────────────────────────────────────────

    // URL input change — clear preview when user types a new URL
    urlInput.addEventListener('input', () => {
        if (_previewUrl && urlInput.value.trim() !== _previewUrl) {
            hidePreview();
        }
    });

    urlForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = urlInput.value.trim();
        if (!url || isSubmitting) return;

        isSubmitting = true;
        btnSubmit.disabled = true;
        btnSubmit.textContent = 'Loading…';
        setStatusText('Loading...');

        try {
            const data = await api.previewUrl(url);
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
            }
            btnSubmit.textContent = 'Download';
        }
    });

    // Preview download button — triggers actual download
    previewDownloadBtn.addEventListener('click', async () => {
        if (!_previewUrl) return;

        previewDownloadBtn.disabled = true;
        setStatusText('Starting download...');

        try {
            const job = await api.startDownload(_previewUrl);
            _activeJobs.add(job.job_id);
            _activeJobId = job.job_id;
            jobs[job.job_id] = job;
            renderJob(job);
            // Preview stays visible — status container shows progress
        } catch (e) {
            toast(e.message || 'Download failed', 'error');
            previewDownloadBtn.disabled = false;
            clearStatus();
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
            await api.updateConfig(cfg);
            toast('Settings saved', 'success');
            closeModal('modal-settings');
        } catch (e) {
            toast(e.message || 'Failed to save settings', 'error');
        }
    });

    // Cookie file upload — parse client-side, extract token, store in browser
    btnUploadCookie.addEventListener('click', () => {
        cookieFile.click();
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

            // Validate token against the server
            const result = await api.connectAuth();
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

        try {
            btnConnect.textContent = 'Connecting…';
            btnConnect.disabled = true;
            const result = await api.connectAuth();
            updateAuthBadge(result);
            toast('Connected successfully', 'success');
            // Start/restart SSE now that we have a valid token
            eventStream.connect();
        } catch (e) {
            toast(e.message || 'Connection failed', 'error');
        } finally {
            btnConnect.textContent = 'Connect';
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


    // ── Init ──────────────────────────────────────────────────────────────

    async function init() {
        // Check auth status
        await checkAuth();

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
