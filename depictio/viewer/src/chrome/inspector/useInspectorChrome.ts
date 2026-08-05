import { useEffect, useMemo, useRef } from 'react';
import { INSPECTOR_TOGGLE_EVENT, dispatchPanelToggle } from 'depictio-react-core';
import type { InspectorControl } from 'depictio-react-core';
import type { AppShellAsideConfiguration as AppShellAside } from '@mantine/core';
import { useUiStore } from '../../store/useUiStore';
import { INSPECTOR_WIDTH } from './Inspector';

/** Matches `AppShell transitionDuration={300}` in App.tsx / EditorApp.tsx. */
const TRANSITION_MS = 300;

export interface InspectorChrome {
  open: boolean;
  /** Passed to `InspectorProviders`; null when the feature is disabled, which
   *  is what keeps the inspect action out of every component's chrome. */
  control: InspectorControl | null;
  /** `AppShell`'s `aside` prop, or undefined when the feature is disabled so
   *  the shell lays out exactly as it did before. */
  aside: AppShellAside | undefined;
}

/**
 * Bridges the UI store to the panel-toggle contract.
 *
 * `AppShell.Aside` animates its width over 300ms, and the dashboard grid needs
 * to hear about it for the same reason the sidebar and the filter panel do:
 * Plotly and AG Grid only reflow on a window resize. Emitting the shared event
 * reuses `DashboardGrid`'s existing machinery rather than adding a third copy.
 *
 * @param enabled - the `inspector_enabled` server flag.
 */
export function useInspectorChrome(enabled: boolean): InspectorChrome {
  const inspectorOpen = useUiStore((s) => s.inspectorOpen);
  const selectedComponentId = useUiStore((s) => s.selectedComponentId);
  const inspectComponent = useUiStore((s) => s.inspectComponent);

  const open = enabled && inspectorOpen;

  // Announce transitions rather than toggles: the store is the source of truth
  // and can change from several places (chrome button, close button), so
  // watching the resulting value is the only way to catch all of them.
  const prevOpenRef = useRef(open);
  useEffect(() => {
    if (prevOpenRef.current === open) return;
    prevOpenRef.current = open;
    document.body.classList.add('panel-transitioning');
    const timer = setTimeout(
      () => document.body.classList.remove('panel-transitioning'),
      TRANSITION_MS + 20,
    );
    dispatchPanelToggle(INSPECTOR_TOGGLE_EVENT, {
      willBeOpen: open,
      swingPx: INSPECTOR_WIDTH,
      durationMs: TRANSITION_MS,
    });
    return () => clearTimeout(timer);
  }, [open]);

  // Memoised: this becomes a context value read by every component's chrome,
  // so a fresh object per render would re-render the whole grid's toolbars on
  // every App render.
  const control = useMemo<InspectorControl | null>(
    () => (enabled ? { selectedId: selectedComponentId, select: inspectComponent } : null),
    [enabled, selectedComponentId, inspectComponent],
  );

  const aside = useMemo<AppShellAside | undefined>(
    () =>
      enabled
        ? {
            width: INSPECTOR_WIDTH,
            breakpoint: 'md',
            collapsed: { desktop: !open, mobile: true },
          }
        : undefined,
    [enabled, open],
  );

  return { open, control, aside };
}

export default useInspectorChrome;
