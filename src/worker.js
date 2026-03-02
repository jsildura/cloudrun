/**
 * Cloudflare Worker — injects environment variables into index.html at runtime.
 *
 * This allows sensitive config (like the backend API URL) to be stored as
 * Cloudflare Variables & Secrets instead of being hardcoded in the source code.
 *
 * Environment variables used:
 *   API_URL — The backend Cloud Run URL (e.g. https://gamdl-api-xyz.a.run.app)
 */

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        // Only intercept the root HTML page to inject variables
        if (url.pathname === '/' || url.pathname === '/index.html') {
            // Fetch the static index.html from assets
            const response = await env.ASSETS.fetch(request);
            let html = await response.text();

            // Inject API_URL from Cloudflare variable (if set)
            const apiUrl = env.API_URL || '';
            html = html.replace(
                '<meta name="api-url" content="">',
                `<meta name="api-url" content="${apiUrl}">`
            );

            return new Response(html, {
                headers: {
                    'content-type': 'text/html;charset=UTF-8',
                    // Preserve security headers
                    'X-Frame-Options': 'DENY',
                    'X-Content-Type-Options': 'nosniff',
                    'Referrer-Policy': 'strict-origin-when-cross-origin',
                },
            });
        }

        // All other requests (JS, CSS, images) — serve static assets directly
        return env.ASSETS.fetch(request);
    },
};
