/**
 * auth-storage.js — Client-side Apple Music authentication storage.
 *
 * Parses Netscape cookies.txt files entirely in the browser, extracts the
 * `media-user-token` from the `.music.apple.com` domain, and persists it
 * in localStorage. The token is sent with every API request via the
 * Authorization header.
 *
 * Cookie format (tab-separated Netscape HTTP Cookie File):
 *   domain \t flag \t path \t secure \t expiry \t name \t value
 *
 * Example:
 *   .music.apple.com  TRUE  /  TRUE  1787563513  media-user-token  Aobj4O...
 */

class AuthStorage {
    /** localStorage key for persisted auth data. */
    static KEY = 'gamdl_auth';

    /**
     * The exact cookie domain that the Python library (gamdl) uses
     * when looking for the media-user-token. This must match
     * `APPLE_MUSIC_COOKIE_DOMAIN` in gamdl/api/constants.py.
     */
    static COOKIE_DOMAIN = '.music.apple.com';

    /**
     * The cookie name we need to extract.
     */
    static TOKEN_NAME = 'media-user-token';

    /**
     * Parse a Netscape cookies.txt string and extract the media-user-token.
     *
     * Follows the same matching logic as Python's MozillaCookieJar:
     *   - Lines starting with '#' are comments (skipped)
     *   - Empty/whitespace-only lines are skipped
     *   - Fields are tab-separated: domain, flag, path, secure, expiry, name, value
     *   - We match: name === "media-user-token" AND domain === ".music.apple.com"
     *
     * @param {string} text - Raw contents of a cookies.txt file.
     * @returns {string|null} The media-user-token value, or null if not found.
     */
    static parseCookiesFile(text) {
        if (!text || typeof text !== 'string') {
            return null;
        }

        const lines = text.split(/\r?\n/);

        for (const line of lines) {
            const trimmed = line.trim();

            // Skip empty lines and comments
            if (!trimmed || trimmed.startsWith('#')) {
                continue;
            }

            // Netscape cookie format is tab-separated with exactly 7 fields:
            // domain \t httponly_flag \t path \t secure \t expiry \t name \t value
            const fields = trimmed.split('\t');

            if (fields.length < 7) {
                continue;
            }

            const domain = fields[0].trim();
            const name = fields[5].trim();
            const value = fields[6].trim();

            // Many extensions prefix HTTP-only cookies with #HttpOnly_
            const cleanDomain = domain.startsWith('#HttpOnly_') ? domain.substring(10) : domain;

            // Match exactly how the Python gamdl library does it:
            //   cookie.name == "media-user-token"
            //   cookie.domain == ".music.apple.com"
            if (name === this.TOKEN_NAME && cleanDomain === this.COOKIE_DOMAIN) {
                if (value) {
                    return value;
                }
            }
        }

        return null;
    }

    /**
     * Parse a cookies.txt File object and extract the token.
     * Convenience wrapper around parseCookiesFile() for use with <input type="file">.
     *
     * @param {File} file - A File object from an <input type="file"> element.
     * @returns {Promise<string|null>} The media-user-token, or null if not found.
     */
    static async parseCookiesFromFile(file) {
        if (!file) {
            return null;
        }

        try {
            const text = await file.text();
            return this.parseCookiesFile(text);
        } catch (err) {
            console.error('AuthStorage: Failed to read cookies file:', err);
            return null;
        }
    }

    /**
     * Synchronous SHA-256 hex digest (UTF-8 input) to match Python's
     * `hashlib.sha256(token.strip().encode()).hexdigest()`.
     *
     * @param {string} asciiOrUtf8 - Input string.
     * @returns {string} 64-character lowercase hex SHA-256 digest.
     */
    static _sha256Hex(asciiOrUtf8) {
        const bytes = new TextEncoder().encode(asciiOrUtf8);
        const K = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
        ];
        const H = [
            0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
            0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
        ];
        const bitLen = bytes.length * 8;
        const padLen = ((bytes.length + 9 + 63) & ~63);
        const padded = new Uint8Array(padLen);
        padded.set(bytes);
        padded[bytes.length] = 0x80;
        const view = new DataView(padded.buffer);
        view.setUint32(padLen - 8, Math.floor(bitLen / 0x100000000), false);
        view.setUint32(padLen - 4, bitLen >>> 0, false);

        const W = new Uint32Array(64);
        const rotr = (n, x) => (x >>> n) | (x << (32 - n));

        for (let offset = 0; offset < padLen; offset += 64) {
            for (let i = 0; i < 16; i++) {
                W[i] = view.getUint32(offset + i * 4, false);
            }
            for (let i = 16; i < 64; i++) {
                const s0 = rotr(7, W[i - 15]) ^ rotr(18, W[i - 15]) ^ (W[i - 15] >>> 3);
                const s1 = rotr(17, W[i - 2]) ^ rotr(19, W[i - 2]) ^ (W[i - 2] >>> 10);
                W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
            }
            let [a, b, c, d, e, f, g, h] = H;
            for (let i = 0; i < 64; i++) {
                const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
                const ch = (e & f) ^ (~e & g);
                const temp1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
                const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
                const maj = (a & b) ^ (a & c) ^ (b & c);
                const temp2 = (S0 + maj) >>> 0;
                h = g;
                g = f;
                f = e;
                e = (d + temp1) >>> 0;
                d = c;
                c = b;
                b = a;
                a = (temp1 + temp2) >>> 0;
            }
            H[0] = (H[0] + a) >>> 0;
            H[1] = (H[1] + b) >>> 0;
            H[2] = (H[2] + c) >>> 0;
            H[3] = (H[3] + d) >>> 0;
            H[4] = (H[4] + e) >>> 0;
            H[5] = (H[5] + f) >>> 0;
            H[6] = (H[6] + g) >>> 0;
            H[7] = (H[7] + h) >>> 0;
        }
        return H.map((v) => v.toString(16).padStart(8, '0')).join('');
    }

    /**
     * Compute the 8-character account ID for a media-user-token.
     * Matches `hashlib.sha256(token.strip().encode()).hexdigest()[:8]` on the server.
     *
     * @param {string} token - Raw media-user-token.
     * @returns {string|null} 8-char hex ID (e.g. "e56b880b") or null.
     */
    static computeAccountId(token) {
        if (!token || typeof token !== 'string') return null;
        const clean = token.trim();
        if (!clean) return null;
        return this._sha256Hex(clean).slice(0, 8);
    }

    /**
     * Save the media-user-token to localStorage.
     *
     * @param {string} mediaUserToken - The extracted media-user-token value.
     * @param {Object} [meta] - Optional metadata ({ accountId, storefront, source }).
     */
    static save(mediaUserToken, meta = {}) {
        if (!mediaUserToken) {
            console.warn('AuthStorage: Attempted to save empty token');
            return;
        }

        const cleanToken = mediaUserToken.trim();
        const accountId = meta.accountId || this.computeAccountId(cleanToken);

        const data = {
            token: cleanToken,
            accountId,
            storefront: meta.storefront || null,
            source: meta.source || 'file',
            savedAt: new Date().toISOString(),
        };

        localStorage.setItem(this.KEY, JSON.stringify(data));
    }

    /**
     * Update metadata fields (e.g. storefront, source, accountId) on the stored auth entry.
     *
     * @param {Object} meta - Metadata fields to merge.
     */
    static updateMeta(meta = {}) {
        try {
            const info = this.getAuthInfo();
            if (!info || !info.token) return;
            const updated = {
                ...info,
                ...meta,
                accountId: meta.accountId || info.accountId || this.computeAccountId(info.token),
            };
            localStorage.setItem(this.KEY, JSON.stringify(updated));
        } catch (err) {
            console.warn('AuthStorage: Failed to update metadata:', err);
        }
    }

    /**
     * Retrieve the 8-character account ID of the currently stored token.
     *
     * @returns {string|null} 8-char account ID (e.g. "e56b880b") or null.
     */
    static getAccountId() {
        const info = this.getAuthInfo();
        if (!info || !info.token) return null;
        return info.accountId || this.computeAccountId(info.token);
    }

    /**
     * Retrieve the currently saved token.
     *
     * @returns {string|null} The token, or null if not saved.
     */
    static getToken() {
        try {
            const raw = localStorage.getItem(this.KEY);
            if (!raw) {
                return null;
            }

            const data = JSON.parse(raw);
            return data?.token || null;
        } catch (err) {
            // Corrupted data — clear it
            console.warn('AuthStorage: Corrupted stored data, clearing:', err);
            this.clear();
            return null;
        }
    }

    /**
     * Returns true if a token is currently stored.
     *
     * @returns {boolean}
     */
    static hasToken() {
        return !!this.getToken();
    }

    /**
     * Clear stored authentication data (sign out).
     */
    static clear() {
        localStorage.removeItem(this.KEY);
    }

    /**
     * Get metadata about the stored auth (e.g. when it was saved).
     *
     * @returns {{ token: string, savedAt: string } | null}
     */
    static getAuthInfo() {
        try {
            const raw = localStorage.getItem(this.KEY);
            if (!raw) {
                return null;
            }

            return JSON.parse(raw);
        } catch {
            return null;
        }
    }
}
