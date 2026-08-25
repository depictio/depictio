import { useCallback, useRef, useState } from 'react';

import { useAdvancedVizConfigDraft, type VizConfigDraftSink } from './AdvancedVizConfigDraft';

/**
 * Write a config patch for this component, for controls the hook below cannot
 * own: a value that is auto-detected from the data and only sometimes chosen by
 * the author, like coverage_track's view mode.
 *
 * Use it in the control's own `onChange`, alongside the local setState. Keeping
 * the two calls separate is the point: the auto-detected default stays local,
 * and only the author's pick is persisted.
 */
export function useVizConfigWriter(metadata: {
  index?: string | number;
}): (patch: Record<string, unknown>) => void {
  const latest = useRef<{ sink: VizConfigDraftSink | null; index: string }>({
    sink: null,
    index: '',
  });
  latest.current = {
    sink: useAdvancedVizConfigDraft(),
    index: String(metadata.index ?? ''),
  };
  return useCallback((patch: Record<string, unknown>) => {
    latest.current.sink?.(latest.current.index, patch);
  }, []);
}

/**
 * One Tier-2 control: seeded from the component's persisted config, held in
 * local state, and mirrored back to whoever owns that config when it changes.
 *
 * A drop-in for `useState(config.x ?? DEFAULT)`, which is the shape every
 * renderer used before and which read identically but forgot everything.
 *
 * The mirror fires from the setter, never from an effect and never during
 * render. That is what keeps a control change to exactly one store write and
 * makes a feedback loop structurally impossible rather than a thing to be
 * careful about. The corollary is a rule worth enforcing in review: never call
 * this setter from inside an effect. A value that has to be corrected once the
 * data arrives is data-derived, not authored, and belongs in `useState` plus an
 * explicit `useVizConfigWriter` call on the control itself.
 *
 * With no sink in context (every dashboard surface today) the setter is a plain
 * setState and the control behaves exactly as it did before.
 */
export function usePersistedVizControl<T>(
  // `config` is deliberately `unknown`: every renderer narrows it to its own
  // per-kind interface, and those have no index signature, so anything tighter
  // would reject the exact callers this hook exists for.
  metadata: { index?: string | number; config?: unknown },
  configKey: string,
  fallback: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(
    () =>
      ((metadata.config as Record<string, unknown> | undefined)?.[configKey] as T | undefined) ??
      fallback,
  );

  // A ref rather than deps: the setter keeps one identity for the life of the
  // renderer, so the `controls` useMemo that closes over it is not invalidated
  // whenever the sink or the metadata identity changes.
  const latest = useRef<{ sink: VizConfigDraftSink | null; configKey: string; index: string }>({
    sink: null,
    configKey,
    index: '',
  });
  latest.current = {
    sink: useAdvancedVizConfigDraft(),
    configKey,
    index: String(metadata.index ?? ''),
  };

  const set = useCallback((next: T) => {
    setValue(next);
    const { sink, configKey: key, index } = latest.current;
    sink?.(index, { [key]: next });
  }, []);

  return [value, set];
}
