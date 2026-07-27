/**
 * Anonymous browser telemetry.
 *
 * Shared deliberately rather than living in one app: the Tools Studio
 * (`packages/catalog-studio`) aliases `depictio-react-core` in its Vite config,
 * so a client here is reachable from both the dashboard viewer and the Studio
 * without duplicating the consent logic — and consent logic duplicated is consent
 * logic that eventually disagrees with itself.
 *
 * No SDK. A PostHog capture is one JSON POST, and `posthog-js` would add ~50 KB
 * to the bundle plus a script origin to justify under the Studio's GitHub Pages
 * hosting. `fetch` with `keepalive` survives page unload, which is the only thing
 * an SDK would really have bought us.
 *
 * Consent rules, in order:
 *  1. An explicit opt-out stored in `localStorage` always wins.
 *  2. `navigator.doNotTrack === '1'` is honoured.
 *  3. Without a configured project token, nothing is sent at all.
 *
 * Nothing identifying is collected. No cookies are set, no fingerprinting is
 * done, and the anonymous ID is a random UUID in `localStorage` that the user can
 * clear at any time along with the rest of their site data.
 */

/** PostHog Cloud EU ingestion endpoint — keeps event data inside the EEA. */
const DEFAULT_ENDPOINT = 'https://eu.i.posthog.com/i/v0/e/';

const ANON_ID_KEY = 'depictio.telemetry.anonymous_id';
const OPT_OUT_KEY = 'depictio.telemetry.opt_out';

export interface TelemetryConfig {
  /** PostHog project token. Public and write-only; empty disables telemetry. */
  apiKey: string;
  /** Ingestion endpoint. Defaults to PostHog Cloud EU. */
  endpoint?: string;
  /** Included on every event, so viewer and Studio events stay distinguishable. */
  source: string;
  /** App version, when the host knows it. */
  version?: string;
}

let config: TelemetryConfig | null = null;

/**
 * localStorage access that tolerates it being unavailable.
 *
 * Private browsing, embedded webviews and strict cookie policies can all make
 * `localStorage` throw on access rather than merely return null. Telemetry must
 * never be the reason a page fails to load.
 */
function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** True when the user has opted out, by our own toggle or by Do Not Track. */
export function isOptedOut(): boolean {
  const storage = safeStorage();
  if (storage?.getItem(OPT_OUT_KEY) === 'true') return true;

  try {
    if (navigator.doNotTrack === '1') return true;
  } catch {
    // Non-browser or locked-down environment; fall through to allowed.
  }
  return false;
}

/** Record the user's choice. `true` stops all further sends immediately. */
export function setOptOut(optOut: boolean): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    if (optOut) {
      storage.setItem(OPT_OUT_KEY, 'true');
    } else {
      storage.removeItem(OPT_OUT_KEY);
    }
  } catch {
    // Nothing to do — a browser that refuses the write also refuses the ID,
    // so telemetry simply stays off.
  }
}

/**
 * Stable-per-browser anonymous ID, or null if it cannot be stored.
 *
 * Returning null rather than a fresh per-call UUID is deliberate: an ID that
 * changes every event would make each page load look like a new user and quietly
 * inflate every count.
 */
function anonymousId(): string | null {
  const storage = safeStorage();
  if (!storage) return null;

  try {
    const existing = storage.getItem(ANON_ID_KEY);
    if (existing) return existing;

    const generated =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    storage.setItem(ANON_ID_KEY, generated);
    return generated;
  } catch {
    return null;
  }
}

/** Configure telemetry. Until this is called with a token, `capture` is a no-op. */
export function initTelemetry(next: TelemetryConfig): void {
  config = next;
}

/**
 * Send one anonymous event. Never throws, never awaited by callers.
 *
 * `keepalive` lets the request outlive the page, so an event fired as the user
 * navigates away still arrives — without it, exit events (the interesting half of
 * any funnel) would be lost.
 *
 * @param event Event name, e.g. `studio_export`.
 * @param properties Bounded, non-identifying values only. Never pass user input,
 *   file names, URLs or free text.
 */
export function capture(event: string, properties: Record<string, unknown> = {}): void {
  if (!config?.apiKey) return;
  if (isOptedOut()) return;

  const distinctId = anonymousId();
  if (!distinctId) return;

  try {
    void fetch(config.endpoint ?? DEFAULT_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
      body: JSON.stringify({
        api_key: config.apiKey,
        event,
        distinct_id: distinctId,
        properties: {
          ...properties,
          source: config.source,
          ...(config.version ? { version: config.version } : {}),
        },
        timestamp: new Date().toISOString(),
      }),
      // A failed telemetry POST is a non-event. Swallow rather than surface an
      // unhandled rejection in the host app's console.
    }).catch(() => undefined);
  } catch {
    // Ignore: no telemetry failure is worth affecting the page.
  }
}
