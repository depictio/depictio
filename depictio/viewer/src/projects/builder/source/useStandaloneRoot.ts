/**
 * The data root of a standalone builder: the folder `depictio project-builder
 * <dir>` was launched on, read once from `GET /projects/builder/context`. It
 * cannot be changed from the page.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { builderContext } from 'depictio-react-core';
import type { BuilderContext, BuilderRootSpec } from 'depictio-react-core';

export type StandaloneRoot =
  | { status: 'loading'; rootSpec: null; retry: () => void }
  | { status: 'error'; error: string; rootSpec: null; retry: () => void }
  | { status: 'ready'; context: BuilderContext; rootSpec: BuilderRootSpec; retry: () => void };

export function useStandaloneRoot(enabled: boolean): StandaloneRoot {
  const [attempt, setAttempt] = useState(0);
  const [context, setContext] = useState<BuilderContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setError(null);
    builderContext({ signal: controller.signal })
      .then((ctx) => {
        if (!controller.signal.aborted) setContext(ctx);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err.message || 'The builder server did not answer.');
      });
    return () => controller.abort();
  }, [enabled, attempt]);

  const rootSpec = useMemo<BuilderRootSpec | null>(
    () => (context ? { data_root: context.data_root } : null),
    [context],
  );

  if (context && rootSpec) return { status: 'ready', context, rootSpec, retry };
  if (error) return { status: 'error', error, rootSpec: null, retry };
  return { status: 'loading', rootSpec: null, retry };
}
