import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * `githubOAuth` reads `import.meta.env` into module-level constants, so each
 * case re-imports it after stubbing the env. The popup flow is exercised for
 * real in jsdom: the module listens for a postMessage from the callback page,
 * and the `state` comparison there is the only CSRF defence in the whole flow.
 */
async function loadModule(env: Record<string, string> = {}) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  return import('../catalog/githubOAuth');
}

/** A stand-in for the OAuth popup: never "closed", so only postMessage drives it. */
function stubPopup() {
  const popup = { closed: false } as Window;
  vi.stubGlobal('open', vi.fn(() => popup));
  return popup;
}

/** Emit what `public/oauth-callback.html` posts back to the opener. */
function postFromCallback(payload: Record<string, unknown>) {
  window.dispatchEvent(
    new MessageEvent('message', { data: { source: 'depictio-oauth', ...payload }, origin: window.location.origin }),
  );
}

/** The `state` the module put in the authorize URL it just opened. */
function stateFromAuthorizeUrl(): string {
  const call = (window.open as unknown as { mock: { calls: unknown[][] } }).mock.calls[0];
  return new URL(String(call[0])).searchParams.get('state')!;
}

beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('oauthConfigured', () => {
  it('is false unless BOTH the client id and the worker URL are set', async () => {
    expect((await loadModule()).oauthConfigured()).toBe(false);
    expect((await loadModule({ VITE_GH_CLIENT_ID: 'abc' })).oauthConfigured()).toBe(false);
    expect(
      (await loadModule({ VITE_GH_CLIENT_ID: 'abc', VITE_GH_OAUTH_WORKER_URL: 'https://w/exchange' }))
        .oauthConfigured(),
    ).toBe(true);
  });
});

describe('devToken', () => {
  it('rejects a pasted shell command, which env files do not run', async () => {
    const m = await loadModule({ VITE_GH_TOKEN: '$(gh auth token)' });
    expect(m.devToken()).toBeNull();
    const m2 = await loadModule({ VITE_GH_TOKEN: 'ghp_real' });
    expect(m2.devToken()).toBe('ghp_real');
  });
});

describe('signIn', () => {
  const env = { VITE_GH_CLIENT_ID: 'abc', VITE_GH_OAUTH_WORKER_URL: 'https://w/exchange' };

  it('refuses when the deployment has no OAuth config', async () => {
    const m = await loadModule();
    await expect(m.signIn()).rejects.toThrow(/not configured/i);
  });

  it('exchanges the code and caches the token in sessionStorage', async () => {
    const m = await loadModule(env);
    stubPopup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ access_token: 'tok' }), { status: 200 })),
    );
    const pending = m.signIn();
    await vi.advanceTimersByTimeAsync(0);
    postFromCallback({ code: 'the-code', state: stateFromAuthorizeUrl() });
    await expect(pending).resolves.toBe('tok');
    expect(m.getStoredToken()).toBe('tok');
    m.clearStoredToken();
    expect(m.getStoredToken()).toBeNull();
  });

  it('aborts on a state mismatch — the only CSRF check in the flow', async () => {
    const m = await loadModule(env);
    stubPopup();
    const pending = m.signIn();
    await vi.advanceTimersByTimeAsync(0);
    postFromCallback({ code: 'the-code', state: 'attacker-supplied' });
    await expect(pending).rejects.toThrow(/state mismatch/i);
  });

  it('ignores a message from another origin', async () => {
    const m = await loadModule(env);
    const popup = stubPopup();
    // Attach the handler up front: the rejection fires while the fake timers
    // are being advanced, which would otherwise surface as an unhandled one.
    const settled = m.signIn().then(
      () => null,
      (e: Error) => e,
    );
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { source: 'depictio-oauth', code: 'x', state: stateFromAuthorizeUrl() },
        origin: 'https://evil.example',
      }),
    );
    // Nothing resolved it, so closing the popup is still what ends the wait.
    (popup as { closed: boolean }).closed = true;
    await vi.advanceTimersByTimeAsync(600);
    expect((await settled)?.message).toMatch(/cancelled/i);
  });

  it('reports a blocked popup instead of hanging', async () => {
    const m = await loadModule(env);
    vi.stubGlobal('open', vi.fn(() => null));
    await expect(m.signIn()).rejects.toThrow(/popup blocked/i);
  });

  it('surfaces an error the callback page reports', async () => {
    const m = await loadModule(env);
    stubPopup();
    const pending = m.signIn();
    await vi.advanceTimersByTimeAsync(0);
    postFromCallback({ error: 'access_denied' });
    await expect(pending).rejects.toThrow(/access_denied/);
  });

  it('surfaces a failing token exchange', async () => {
    const m = await loadModule(env);
    stubPopup();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 502 })));
    const pending = m.signIn();
    await vi.advanceTimersByTimeAsync(0);
    postFromCallback({ code: 'c', state: stateFromAuthorizeUrl() });
    await expect(pending).rejects.toThrow(/502/);
  });

  it('requests only the public_repo scope', async () => {
    const m = await loadModule(env);
    stubPopup();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ access_token: 't' }))));
    const pending = m.signIn();
    await vi.advanceTimersByTimeAsync(0);
    const url = new URL(
      String((window.open as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]),
    );
    expect(url.searchParams.get('scope')).toBe('public_repo');
    postFromCallback({ code: 'c', state: url.searchParams.get('state')! });
    await pending;
  });
});
