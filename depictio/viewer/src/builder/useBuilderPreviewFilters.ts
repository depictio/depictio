/**
 * The filters a builder preview should apply: the dashboard's active filters
 * carried into the builder (see editorFilters.ts), minus any emitted by the
 * component being edited itself, gated by the "Apply to preview" toggle.
 *
 * Excluding ALL own-index filters (not just selection sources) is the safe
 * superset of the runtime rule: at runtime a figure drops only its own
 * `scatter_selection` (FigureRenderer), but here the edited component may
 * also be the interactive control that emitted the filter — and no control
 * filters itself. In create mode the componentId is a fresh UUID, so nothing
 * matches and this is a no-op.
 */
import { useMemo } from 'react';
import type { InteractiveFilter } from 'depictio-react-core';
import { useBuilderStore } from './store/useBuilderStore';

export function useBuilderPreviewFilters(): InteractiveFilter[] {
  const dashboardFilters = useBuilderStore((s) => s.dashboardFilters);
  const apply = useBuilderStore((s) => s.applyDashboardFilters);
  const componentId = useBuilderStore((s) => s.componentId);
  return useMemo(
    () =>
      apply
        ? dashboardFilters.filter((f) => String(f.index) !== String(componentId))
        : [],
    [apply, dashboardFilters, componentId],
  );
}
