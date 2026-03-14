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

    // ── Downloads ─────────────────────────────────────────────────────────

    async startDownload(url, config = null) {
        const body = { url };
        if (config) body.config = config;
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
