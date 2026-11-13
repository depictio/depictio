/**
 * The before/after of one component against the reader's baseline (#1397).
 *
 * Inert unless `comparing` is true: no request, no state, so a host with no
 * change marks (the editor, every other page) is unchanged. The query comes
 * from the change-marks context: the reader's stored baseline when anonymous,
 * nothing when signed in (the server holds the mark), `since` / `before_run`
 * in a read-only view.
 */
import { useContext, useEffect, useMemo, useState, type RefObject } from 'react';

import { fetchComponentDiff } from '../api';
import type { ComponentDiff, ReaderBaseline } from '../api';
import { ChangeMarksContext } from '../changeMarks';
import {
  applyFigureDiffOverlay,
  buildFigureDiffOverlay,
  resolveDiffColors,
  type FigureDiffOverlay,
  type PlotlyFigureLike,
} from '../figureDiffOverlay';

export interface ComponentDiffState {
  diff: ComponentDiff | null;
  loading: boolean;
  error: string | null;
}

const IDLE: ComponentDiffState = { diff: null, loading: false, error: null };

export function useComponentDiff(args: {
  dashboardId: string | undefined;
  componentId: string;
  comparing: boolean;
  filters: unknown[];
}): ComponentDiffState {
  const { dashboardId, componentId, comparing, filters } = args;
  const { diffQuery } = useContext(ChangeMarksContext);
  const [state, setState] = useState<ComponentDiffState>(IDLE);
  const filtersKey = JSON.stringify(filters);
  const queryKey = JSON.stringify(diffQuery);
  const active = comparing && Boolean(dashboardId) && Boolean(componentId);

  useEffect(() => {
    if (!active || !dashboardId) {
      setState(IDLE);
      return;
    }
    const ctrl = new AbortController();
    setState((prev) => ({ diff: prev.diff, loading: true, error: null }));
    fetchComponentDiff(
      dashboardId,
      componentId,
      {
        baseline: (diffQuery.baseline as ReaderBaseline | null | undefined) ?? null,
        since: diffQuery.since ?? null,
        beforeRun: diffQuery.beforeRun ?? null,
        filters: JSON.parse(filtersKey) as Array<Record<string, unknown>>,
      },
      ctrl.signal,
    )
      .then((diff) => {
        if (!ctrl.signal.aborted) setState({ diff, loading: false, error: null });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setState({
          diff: null,
          loading: false,
          error: err instanceof Error ? err.message : 'Could not compare with your last visit.',
        });
      });
    return () => ctrl.abort();
    // diffQuery is keyed by content: the provider rebuilds the object on every dismissal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, dashboardId, componentId, filtersKey, queryKey]);

  return active ? state : IDLE;
}

const NO_OVERLAY: FigureDiffOverlay = { traces: [], patches: [], matched: 0 };

/**
 * `useComponentDiff` plus the overlay it draws over a figure. `rootRef` names
 * the element the theme colours are read from (a brand-scoped dashboard
 * retints its own subtree, not the document).
 */
export function useFigureDiffOverlay(args: {
  dashboardId: string | undefined;
  componentId: string;
  comparing: boolean;
  filters: unknown[];
  figure: PlotlyFigureLike | null;
  rootRef?: RefObject<Element | null>;
  /** Re-resolve the colours when the colour scheme flips. */
  theme?: string;
}): ComponentDiffState & { overlay: FigureDiffOverlay; apply: (data: unknown[]) => unknown[] } {
  const { figure, rootRef, theme, comparing } = args;
  const state = useComponentDiff(args);
  const overlay = useMemo(
    () =>
      comparing && state.diff && figure
        ? buildFigureDiffOverlay(figure, state.diff, resolveDiffColors(rootRef?.current ?? undefined))
        : NO_OVERLAY,
    // rootRef is a ref: reading it at build time is the point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [comparing, state.diff, figure, theme],
  );
  const apply = useMemo(() => (data: unknown[]) => applyFigureDiffOverlay(data, overlay), [overlay]);
  return { ...state, overlay, apply };
}
