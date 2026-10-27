/**
 * A trace of what the genome tiles do, for working out a confusing sequence
 * (a brush, then Escape, then the browser moving): every brush, filter emitted
 * or cleared, zoom from code, Escape and browser navigation, in order.
 *
 * Off unless asked for: `?debug=genome` in the URL, or
 * `localStorage['depictio:debug'] = 'genome'` (kept across reloads). When on,
 * each event goes to the console (`[genome]`), to a ring buffer the panel
 * (`GenomeDebugPanel`) shows, and to `window.__depictioGenomeTrace` for a
 * session driven from devtools. When off, `traceGenome` returns at once.
 */

export interface GenomeTraceEvent {
  /** Milliseconds since the page loaded. */
  t: number;
  /** Which tile: its title, else its index. */
  tile: string;
  event: string;
  detail?: unknown;
}

const LIMIT = 200;
const STORAGE_KEY = 'depictio:debug';

let enabledCache: boolean | null = null;
let events: GenomeTraceEvent[] = [];
const listeners = new Set<() => void>();

export function genomeDebugEnabled(): boolean {
  if (enabledCache !== null) return enabledCache;
  let on = false;
  try {
    const params = new URLSearchParams(window.location.search);
    const flag = params.get('debug');
    if (flag !== null) {
      on = flag === 'genome' || flag === '1';
      // The URL flag sticks for the session's reloads, and `?debug=0` drops it.
      if (on) window.localStorage.setItem(STORAGE_KEY, 'genome');
      else window.localStorage.removeItem(STORAGE_KEY);
    } else {
      on = window.localStorage.getItem(STORAGE_KEY) === 'genome';
    }
  } catch {
    on = false;
  }
  enabledCache = on;
  return on;
}

function tileLabel(index: string): string {
  try {
    const el = document.querySelector(`[data-component-index="${CSS.escape(index)}"]`);
    return el?.getAttribute('data-component-title')?.trim() || index;
  } catch {
    return index;
  }
}

/** Record one event of tile `index`. A no-op while the trace is off. */
export function traceGenome(index: string, event: string, detail?: unknown): void {
  if (!genomeDebugEnabled()) return;
  const entry: GenomeTraceEvent = {
    t: Math.round(performance.now()),
    tile: tileLabel(index),
    event,
    ...(detail === undefined ? {} : { detail }),
  };
  events = [...events.slice(-(LIMIT - 1)), entry];
  (window as unknown as { __depictioGenomeTrace?: GenomeTraceEvent[] }).__depictioGenomeTrace = events;
  // eslint-disable-next-line no-console
  console.debug(`[genome] ${entry.t}ms ${entry.tile} · ${event}`, detail ?? '');
  for (const l of listeners) l();
}

export function genomeTrace(): GenomeTraceEvent[] {
  return events;
}

export function clearGenomeTrace(): void {
  events = [];
  for (const l of listeners) l();
}

export function subscribeGenomeTrace(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** A region-filter pair as one short string, for the trace. */
export function describeFilters(
  filters: readonly { index: unknown; value: unknown }[],
): string {
  return filters
    .map((f) => `${String(f.index)}=${JSON.stringify(f.value)}`)
    .join(' ');
}
