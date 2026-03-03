export async function onRequest(context) {
    const { request, env, next } = context;
    const url = new URL(request.url);

    // 1. If no password is configured, allow all traffic
    if (!env.SITE_PASSWORD) {
        return next();
    }

    // 2. Check for authentication cookie
    const cookies = request.headers.get('Cookie') || '';
    const isAuthenticated = cookies.includes(`gamdl_auth=${env.SITE_PASSWORD}`);

    if (isAuthenticated) {
        return next();
    }

    // 3. Handle Login POST request
    if (request.method === 'POST' && url.pathname === '/login') {
        const formData = await request.formData();
        const password = formData.get('password');

        if (password === env.SITE_PASSWORD) {
            // Success: Set cookie and redirect to root
            return new Response(null, {
                status: 302,
                headers: {
                    'Location': '/',
                    'Set-Cookie': `gamdl_auth=${password}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=2592000` // 30 days
                }
            });
        } else {
            // Fail: Redirect back with error
            return new Response(null, {
                status: 302,
                headers: {
                    'Location': '/?error=1'
                }
            });
        }
    }

    // 4. Deny API requests with 401 JSON immediately
    if (url.pathname.startsWith('/api/')) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), {
            status: 401,
            headers: {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
        });
    }

    // 5. Serve the Custom Login Page
    const isError = url.searchParams.has('error');

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Amdlxd - Authenticate</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --surface-color: rgba(30, 41, 59, 0.7);
            --border-color: rgba(255, 255, 255, 0.1);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --error: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        html {
            height: 100%;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100%;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
            overflow: hidden;
            position: relative;
        }

        /* Moving Gradient Background */
        .ambient-bg {
            position: fixed;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle at 50% 50%, rgba(59, 130, 246, 0.15), transparent 60%),
                        radial-gradient(circle at 80% 20%, rgba(139, 92, 246, 0.15), transparent 50%);
            animation: rotateBg 20s linear infinite;
            z-index: 0;
            pointer-events: none;
        }

        @keyframes rotateBg {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .login-container {
            background: var(--surface-color);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 48px 40px;
            width: 100%;
            max-width: 400px;
            z-index: 1;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            text-align: center;
        }

        .icon-container {
            margin-bottom: 24px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 64px;
            height: 64px;
            border-radius: 16px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--primary);
        }

        h1 {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }

        p.subtitle {
            color: var(--text-muted);
            font-size: 15px;
            margin-bottom: 32px;
        }

        form {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .input-group {
            position: relative;
        }

        .input-icon {
            position: absolute;
            left: 16px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            width: 20px;
            height: 20px;
        }

        input[type="password"] {
            width: 100%;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 14px 16px 14px 48px;
            border-radius: 12px;
            font-size: 16px;
            outline: none;
            transition: all 0.2s;
            -webkit-appearance: none;
        }

        input[type="password"]:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
        }
        
        input[type="password"]::placeholder {
            color: var(--text-muted);
        }

        button {
            background: var(--primary);
            color: white;
            border: none;
            padding: 14px;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
            -webkit-appearance: none;
        }

        button:hover {
            background: var(--primary-hover);
        }

        .error-message {
            color: var(--error);
            font-size: 14px;
            margin-top: 16px;
            display: ${isError ? 'block' : 'none'};
        }

        /* Mobile responsiveness */
        @media (max-width: 480px) {
            body {
                padding: 16px;
            }
            .login-container {
                padding: 36px 24px;
                border-radius: 20px;
            }
            .icon-container {
                width: 56px;
                height: 56px;
            }
            h1 {
                font-size: 22px;
            }
            p.subtitle {
                font-size: 14px;
                margin-bottom: 24px;
            }
        }
    </style>
</head>
<body>
    <div class="ambient-bg"></div>
    <div class="login-container">
        <div class="icon-container">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
        </div>
        <h1>Protected Access</h1>
        <p class="subtitle">Please enter the password to access Amdlxd</p>
        
        <form action="/login" method="POST">
            <div class="input-group">
                <svg class="input-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path>
                </svg>
                <input type="password" name="password" placeholder="Password" required autofocus>
            </div>
            <button type="submit">Login</button>
        </form>
        
        <div class="error-message">Incorrect password. Please try again.</div>
    </div>
</body>
</html>`;

    return new Response(html, {
        headers: {
            'Content-Type': 'text/html;charset=UTF-8'
        }
    });
}
