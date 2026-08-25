/**
 * "Sign in with GitHub" for the static Catalog Studio — a popup OAuth flow that
 * never navigates the main window, so the authored entry (tool/fixture/renders)
 * survives. The popup returns to `public/oauth-callback.html`, which postMessages
 * the `code` back here; we validate `state`, then exchange the code for a user
 * token via the deploy-time worker (which holds the client secret). The token is
 * used in the browser to fork + commit + open a PR (see `github.ts`).
 *
 * Configured via Vite env (see oauth-worker/README.md):
 *   VITE_GH_CLIENT_ID         — OAuth App client id (public)
 *   VITE_GH_OAUTH_WORKER_URL  — worker /exchange endpoint
 * When unset, `oauthConfigured()` is false and the UI falls back to web-upload.
 */
const CLIENT_ID = import.meta.env.VITE_GH_CLIENT_ID as string | undefined;
const WORKER_URL = import.meta.env.VITE_GH_OAUTH_WORKER_URL as string | undefined;
const SCOPE = 'public_repo';

export function oauthConfigured(): boolean {
  return Boolean(CLIENT_ID && WORKER_URL);
}

/** Local-testing escape hatch: in `pnpm dev`, a token in `.env.local`
 *  (`VITE_GH_TOKEN`, e.g. `$(gh auth token)`) lets you exercise the real
 *  fork/commit/PR flow without deploying the worker or registering an OAuth
 *  App. DEV-only and gitignored — never used in a production build. */
export function devToken(): string | null {
  if (!import.meta.env.DEV) return null;
  const raw = (import.meta.env.VITE_GH_TOKEN as string | undefined)?.trim();
  if (!raw) return null;
  // Guard the common mistake of pasting a literal shell command into .env.local
  // (env files don't run shell) — that would 401 with a confusing "Bad credentials".
  if (raw.startsWith('$(') || raw.includes('gh auth token')) {
    // eslint-disable-next-line no-console
    console.warn('[catalog-studio] VITE_GH_TOKEN looks like a literal shell command — put the actual token value.');
    return null;
  }
  return raw;
}

const TOKEN_KEY = 'depictio-gh-token';

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}
export function clearStoredToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

function randomState(): string {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Run the popup OAuth flow and return a user access token. Must be called from
 *  a user gesture (button click) so the popup isn't blocked. */
export async function signIn(): Promise<string> {
  if (!oauthConfigured()) throw new Error('GitHub OAuth is not configured for this deployment.');
  const existing = getStoredToken();
  if (existing) return existing;

  const state = randomState();
  const redirectUri = `${window.location.origin}${import.meta.env.BASE_URL}oauth-callback.html`;
  const authUrl =
    `https://github.com/login/oauth/authorize?client_id=${encodeURIComponent(CLIENT_ID!)}` +
    `&scope=${encodeURIComponent(SCOPE)}` +
    `&redirect_uri=${encodeURIComponent(redirectUri)}` +
    `&state=${state}`;

  const popup = window.open(authUrl, 'depictio-github-oauth', 'width=720,height=760');
  if (!popup) throw new Error('Popup blocked — allow popups for this site and try again.');

  const code = await new Promise<string>((resolve, reject) => {
    const timer = window.setInterval(() => {
      if (popup.closed) {
        cleanup();
        reject(new Error('Sign-in cancelled.'));
      }
    }, 500);
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      const d = e.data as { source?: string; code?: string; state?: string; error?: string };
      if (!d || d.source !== 'depictio-oauth') return;
      cleanup();
      if (d.error) return reject(new Error(`GitHub sign-in failed: ${d.error}`));
      if (d.state !== state) return reject(new Error('OAuth state mismatch — aborting.'));
      if (!d.code) return reject(new Error('No authorization code returned.'));
      resolve(d.code);
    };
    function cleanup() {
      window.clearInterval(timer);
      window.removeEventListener('message', onMessage);
    }
    window.addEventListener('message', onMessage);
  });

  const res = await fetch(WORKER_URL!, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error(`Token exchange failed (HTTP ${res.status}).`);
  const { access_token } = (await res.json()) as { access_token?: string };
  if (!access_token) throw new Error('Token exchange returned no token.');

  sessionStorage.setItem(TOKEN_KEY, access_token);
  return access_token;
}
