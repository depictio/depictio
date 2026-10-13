/**
 * Cloudflare Worker: GitHub OAuth code→token exchange for Depictio Tool Studio.
 *
 * The Studio is a static GitHub-Pages SPA, so it cannot hold the OAuth client
 * secret. This tiny stateless worker performs the one step that requires the
 * secret — exchanging the `code` from GitHub's authorize redirect for a user
 * access token — and returns it to the app. Everything else (fork, commit, PR)
 * runs in the browser with that token via the CORS-enabled GitHub REST API.
 *
 * Config (set with `wrangler secret put` / vars in wrangler.toml):
 *   GH_CLIENT_ID      — the OAuth App client id (public)
 *   GH_CLIENT_SECRET  — the OAuth App client secret (SECRET)
 *   ALLOWED_ORIGIN    — the exact Studio origin, e.g. https://depictio.github.io
 *
 * Endpoint: POST /exchange  { code: string }  ->  { access_token: string }
 */
export interface Env {
  GH_CLIENT_ID: string;
  GH_CLIENT_SECRET: string;
  ALLOWED_ORIGIN: string;
}

function corsHeaders(env: Env): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function json(body: unknown, status: number, env: Env): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(env) },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    // Only accept the Studio origin (defence-in-depth on top of CORS, which the
    // browser enforces but non-browser callers ignore).
    const origin = request.headers.get('Origin');
    if (origin && origin !== env.ALLOWED_ORIGIN) {
      return json({ error: 'forbidden origin' }, 403, env);
    }
    const url = new URL(request.url);
    if (request.method !== 'POST' || url.pathname !== '/exchange') {
      return json({ error: 'not found' }, 404, env);
    }

    let code: unknown;
    try {
      ({ code } = (await request.json()) as { code?: unknown });
    } catch {
      return json({ error: 'invalid JSON body' }, 400, env);
    }
    if (typeof code !== 'string' || !code) {
      return json({ error: 'missing code' }, 400, env);
    }

    const ghRes = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        client_id: env.GH_CLIENT_ID,
        client_secret: env.GH_CLIENT_SECRET,
        code,
      }),
    });
    const data = (await ghRes.json()) as { access_token?: string; error?: string };
    if (!data.access_token) {
      return json({ error: data.error || 'token exchange failed' }, 502, env);
    }
    // Return ONLY the token — never echo the secret.
    return json({ access_token: data.access_token }, 200, env);
  },
};
