/**
 * Cloudflare Pages Function — proxies all /api/* requests to the backend.
 *
 * This catch-all function handles any path under /api/ and forwards it
 * to the EC2 backend specified by the API_URL environment variable.
 *
 * Environment variables (set in Pages dashboard):
 *   API_URL — The backend URL (e.g. https://amdlxd.duckdns.org)
 */

export async function onRequest(context) {
    const { request, env } = context;
    const url = new URL(request.url);

    // ── Handle CORS preflight ────────────────────────────────────────
    if (request.method === 'OPTIONS') {
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

    // ── Proxy to backend ─────────────────────────────────────────────
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
    headers.set('Host', new URL(backendUrl).host);
    headers.delete('cf-connecting-ip');

    const proxyRequest = new Request(target.toString(), {
        method: request.method,
        headers,
        body: request.body,
        redirect: 'follow',
    });

    try {
        const response = await fetch(proxyRequest);

        // Clone response and add CORS headers for the frontend
        const proxyResponse = new Response(response.body, response);
        proxyResponse.headers.set('Access-Control-Allow-Origin', url.origin);
        proxyResponse.headers.set('Access-Control-Allow-Credentials', 'true');
        return proxyResponse;
    } catch (err) {
        return new Response(
            JSON.stringify({ detail: `Backend unreachable: ${err.message}` }),
            { status: 502, headers: { 'content-type': 'application/json' } }
        );
    }
}
