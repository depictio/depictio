import React, { createContext, useContext } from 'react';

import type { InteractiveFilter } from '../../api';

/**
 * Lets the app hang an "Export / embed" action off every component's chrome
 * without this package learning about the export API, its dialog, or the
 * server flag that turns it on.
 *
 * Same contract as `CommentsContext`: the viewer provides, the chrome
 * consumes, and a null context (the default) is the feature flag. The viewer
 * mounts a value only when the server's export API answers
 * (`DEPICTIO_FASTAPI_EMBED_ENABLED`), so on every other deployment, and in
 * every other host (catalog preview, builder, the embed bundle itself), no
 * export action is rendered.
 */
export interface ComponentExportTarget {
  /** The dashboard the component is *defined* on: a cross-tab section's owner
   *  tab, a highlight's source tab — not necessarily the page's. */
  dashboardId: string;
  /** The component's `index` on that dashboard. */
  componentId: string;
  componentType: string;
  vizKind?: string | null;
  title?: string;
  /** The filters the tile is drawn with right now, so the export can match. */
  filters: InteractiveFilter[];
}

export interface ComponentExportControl {
  open: (target: ComponentExportTarget) => void;
}

export const ComponentExportContext = createContext<ComponentExportControl | null>(null);

export const ComponentExportControlProvider: React.FC<{
  value: ComponentExportControl | null;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <ComponentExportContext.Provider value={value}>{children}</ComponentExportContext.Provider>
);

export function useComponentExportControl(): ComponentExportControl | null {
  return useContext(ComponentExportContext);
}

/**
 * Where a tile's chrome says its component comes from.
 *
 * The chrome receives only `metadata`, and `metadata.index` alone does not
 * name a component: a cross-tab section renders under its owner tab's id, and
 * a highlight's metadata keeps the *highlight's* index while drawing another
 * tab's figure. `ComponentRenderer` provides its own `dashboardId` and
 * `filters` here once, `HighlightBlock` overrides it with the source it
 * resolved, and the chrome reads whichever is nearest. Ten `wrapWithChrome`
 * call sites need no new argument.
 */
export interface ChromeSource {
  dashboardId?: string;
  /** Set when the component drawn is not `metadata.index` (a highlight). */
  componentId?: string;
  filters: InteractiveFilter[];
}

const ChromeSourceContext = createContext<ChromeSource | null>(null);

export const ChromeSourceProvider: React.FC<{
  value: ChromeSource;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <ChromeSourceContext.Provider value={value}>{children}</ChromeSourceContext.Provider>
);

export function useChromeSource(): ChromeSource | null {
  return useContext(ChromeSourceContext);
}
