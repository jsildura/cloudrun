/**
 * API Client — typed wrappers for all backend REST endpoints.
 * Base URL read from <meta name="api-url"> tag, with fallback to same-origin.
 *
 * Requires: auth-storage.js (AuthStorage) to be loaded first.
 * Every request includes an Authorization header when a token is available.
 */

class GamdlApi {
    constructor() {
        // Read API URL from meta tag (set at deploy time for Cloudflare Pages)
        // Falls back to same-origin for local development
        const meta = document.querySelector('meta[name="api-url"]');
        this.baseUrl = meta?.content || window.location.origin;
    }

    /**
     * Generic fetch wrapper with error handling.
     * Automatically includes Authorization header when a token is available.
     */
    async _fetch(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const token = AuthStorage.getToken();
        const res = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                ...options.headers,
            },
        });

        if (!res.ok) {
            let detail = res.statusText || `Request failed (HTTP ${res.status})`;
            try {
                const body = await res.json();
                detail = body.detail || detail;
            } catch (_) { }
            throw new Error(detail);
        }

        return res.json();
    }

    // ── Auth ──────────────────────────────────────────────────────────────

    async getAuthStatus() {
        return this._fetch('/api/auth/status');
    }

    async connectAuth() {
        return this._fetch('/api/auth/connect', { method: 'POST' });
    }

    // ── Reserve Cookies Pool ──────────────────────────────────────────────

    async contributeReserveCookie({ storefront, has_subscription }) {
        return this._fetch('/api/reserve-cookies/contribute', {
            method: 'POST',
            body: JSON.stringify({ storefront, has_subscription }),
        });
    }

    async unlockReserveCookies(passcode) {
        return this._fetch('/api/reserve-cookies/unlock', {
            method: 'POST',
            body: JSON.stringify({ passcode }),
        });
    }

    async getReserveCookies(passcode) {
        return this._fetch('/api/reserve-cookies', {
            headers: { 'X-Reserve-Passcode': passcode },
        });
    }

    async connectReserveCookie(accountId, passcode) {
        return this._fetch(`/api/reserve-cookies/connect/${accountId}`, {
            method: 'POST',
            headers: { 'X-Reserve-Passcode': passcode },
        });
    }

    async deleteReserveCookie(accountId, passcode) {
        return this._fetch(`/api/reserve-cookies/${accountId}`, {
            method: 'DELETE',
            headers: { 'X-Reserve-Passcode': passcode },
        });
    }


    // ── Downloads ─────────────────────────────────────────────────────────

    async startDownload(url, config = null, selectedTracks = null) {
        const body = { url };
        if (config) body.config = config;
        if (selectedTracks) body.selected_tracks = selectedTracks;
        return this._fetch('/api/download', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    async previewUrl(url, config = null) {
        const body = { url };
        if (config) body.config = config;
        return this._fetch('/api/preview', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    async getDownloads() {
        return this._fetch('/api/downloads');
    }

    async getDownload(jobId) {
        return this._fetch(`/api/downloads/${jobId}`);
    }

    async cancelDownload(jobId) {
        return this._fetch(`/api/downloads/${jobId}/cancel`, {
            method: 'POST',
        });
    }

    async retryTrack(jobId, trackIndex) {
        return this._fetch(`/api/downloads/${jobId}/retry/${trackIndex}`, {
            method: 'POST',
        });
    }

    async retryAllFailed(jobId) {
        return this._fetch(`/api/downloads/${jobId}/retry-all`, {
            method: 'POST',
        });
    }

    async cleanupJob(jobId) {
        return this._fetch(`/api/downloads/${jobId}/cleanup`, {
            method: 'POST',
        });
    }

    // ── Config ────────────────────────────────────────────────────────────

    async getConfig() {
        return this._fetch('/api/config');
    }

    async updateConfig(updates) {
        return this._fetch('/api/config', {
            method: 'PUT',
            body: JSON.stringify(updates),
        });
    }

    async getWrapperStatus() {
        return this._fetch('/api/wrapper/status');
    }

    async restartWrapper() {
        return this._fetch('/api/wrapper/restart', { method: 'POST' });
    }

    // ── Files ─────────────────────────────────────────────────────────────

    async getFiles() {
        return this._fetch('/api/files');
    }

    getFileUrl(filePath) {
        return `${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`;
    }

    // ── Latest Download ───────────────────────────────────────────────────

    async getLatestDownload() {
        try {
            return await this._fetch('/api/download/latest');
        } catch {
            return { available: false };
        }
    }

    async downloadLatestFile(fallbackFilename) {
        const headers = {};
        const token = (typeof AuthStorage !== 'undefined' && typeof AuthStorage.getToken === 'function')
            ? AuthStorage.getToken()
            : null;
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const url = token
            ? `${this.baseUrl}/api/download/latest/file?token=${encodeURIComponent(token)}`
            : `${this.baseUrl}/api/download/latest/file`;
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error('File no longer available on server');

        let filename = fallbackFilename || 'download.zip';
        const disposition = res.headers.get('content-disposition');
        if (disposition && disposition.includes('filename')) {
            const matchUtf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            const matchStandard = disposition.match(/filename="?([^";]+)"?/i);
            if (matchUtf8 && matchUtf8[1]) {
                filename = decodeURIComponent(matchUtf8[1].trim());
            } else if (matchStandard && matchStandard[1]) {
                filename = matchStandard[1].trim();
            }
        }
        const blob = await res.blob();
        return { blob, filename };
    }

    // ── System Stats ──────────────────────────────────────────────────────

    async getSystemStats() {
        try {
            const res = await fetch(`${this.baseUrl}/api/system/stats`);
            if (!res.ok) return null;
            return res.json();
        } catch {
            return null;
        }
    }
}

// Global singleton
const api = new GamdlApi();
