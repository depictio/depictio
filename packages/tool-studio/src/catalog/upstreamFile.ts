/**
 * Read a file from the catalog as it stands on the target branch RIGHT NOW.
 *
 * `public/catalog.json` is a build-time snapshot: it is what the Studio knows
 * about the existing catalog, and it can be weeks behind whatever is on `main`.
 * That is fine for recognition and duplicate detection, but not for the
 * "add a visualization to an existing output" flow, which rewrites a whole file
 * — appending to a stale copy silently drops every render merged since the
 * snapshot. So the preview (and the plain download) rebase on the live file too,
 * not just the PR path (which re-reads at its exact base commit).
 *
 * raw.githubusercontent.com is CORS-enabled and unauthenticated, so this works
 * from the static app with no token.
 */
import { useEffect, useState } from 'react';
import { resolveTarget, type PrTarget } from './github';

export function rawUrlFor(path: string, target: PrTarget): string {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return `https://raw.githubusercontent.com/${target.owner}/${target.repo}/${target.base}/${encoded}`;
}

export async function fetchUpstreamFile(
  path: string,
  target: PrTarget = resolveTarget(),
): Promise<string> {
  const res = await fetch(rawUrlFor(path, target), { cache: 'no-store' });
  if (!res.ok) throw new Error(`${res.status} for ${path}`);
  return res.text();
}

export type UpstreamState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; text: string; drifted: boolean }
  /** Offline / rate-limited / private: fall back to the snapshot and say so. */
  | { status: 'error'; message: string };

/**
 * Live content of `path`, compared against the snapshot the Studio was built
 * with. `drifted` is what the UI warns on.
 */
export function useUpstreamFile(path: string | null, snapshot: string | null): UpstreamState {
  const [state, setState] = useState<UpstreamState>({ status: 'idle' });
  useEffect(() => {
    if (!path) {
      setState({ status: 'idle' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    fetchUpstreamFile(path)
      .then((text) => {
        if (cancelled) return;
        setState({
          status: 'ok',
          text,
          drifted: snapshot != null && snapshot.trim() !== text.trim(),
        });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: 'error', message: (e as Error).message });
      });
    return () => {
      cancelled = true;
    };
  }, [path, snapshot]);
  return state;
}
