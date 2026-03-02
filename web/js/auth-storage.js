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

            // Match exactly how the Python gamdl library does it:
            //   cookie.name == "media-user-token"
            //   cookie.domain == ".music.apple.com"
            if (name === this.TOKEN_NAME && domain === this.COOKIE_DOMAIN) {
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
     * Save the media-user-token to localStorage.
     *
     * @param {string} mediaUserToken - The extracted media-user-token value.
     */
    static save(mediaUserToken) {
        if (!mediaUserToken) {
            console.warn('AuthStorage: Attempted to save empty token');
            return;
        }

        const data = {
            token: mediaUserToken,
            savedAt: new Date().toISOString(),
        };

        localStorage.setItem(this.KEY, JSON.stringify(data));
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
