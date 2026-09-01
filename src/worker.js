/**
 * Cloudflare Worker — serves frontend assets and proxies /api/* to the backend.
 *
 * Architecture:
 *   - Static assets (JS, CSS, images) are served from Cloudflare's edge.
 *   - All /api/* requests are proxied to the backend (Koyeb, Cloud Run, etc.)
 *     so the frontend can use same-origin relative URLs with zero CORS issues.
 *
 * Environment variables:
 *   API_URL — The backend URL (e.g. https://scared-feliza-amdlxd-91dad0b5.koyeb.app)
 */

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        // ── Handle CORS preflight for /api/* ────────────────────────────
        if (request.method === 'OPTIONS' && url.pathname.startsWith('/api/')) {
            return new Response(null, {
                status: 204,
                headers: {
                    'Access-Control-Allow-Origin': url.origin,
                    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept',
                    'Access-Control-Max-Age': '86400',
                },
            });
        }

        // ── Proxy /api/* requests to the backend ────────────────────────
        if (url.pathname.startsWith('/api/')) {
            const backendUrl = env.API_URL;
            if (!backendUrl) {
                return new Response(
                    JSON.stringify({ detail: 'API_URL not configured' }),
                    { status: 502, headers: { 'content-type': 'application/json' } }
                );
            }

            // Build the target URL: backend + original path + query string
            const target = new URL(url.pathname + url.search, backendUrl);

            // Clone the incoming request, forwarding method, headers, and body
            const headers = new Headers(request.headers);
            headers.delete('host');
            headers.delete('cf-connecting-ip');

            const hasBody = !['GET', 'HEAD'].includes(request.method.toUpperCase());
            const proxyRequest = new Request(target.toString(), {
                method: request.method,
                headers,
                body: hasBody ? request.body : undefined,
                redirect: 'follow',
            });

            try {
                const response = await fetch(proxyRequest);

                // Clone response and add CORS headers for the frontend
                const proxyResponse = new Response(response.body, response);
                proxyResponse.headers.set('Access-Control-Allow-Origin', url.origin);
                proxyResponse.headers.set('Access-Control-Allow-Credentials', 'true');
                proxyResponse.headers.set('Access-Control-Expose-Headers', 'Content-Disposition, Content-Length, Content-Type');
                return proxyResponse;
            } catch (err) {
                return new Response(
                    JSON.stringify({ detail: `Backend unreachable: ${err.message}` }),
                    { status: 502, headers: { 'content-type': 'application/json' } }
                );
            }
        }

        // ── Serve static assets ─────────────────────────────────────────
        return env.ASSETS.fetch(request);
    },
};
