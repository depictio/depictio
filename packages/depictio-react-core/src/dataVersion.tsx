/**
 * Which data every render call on this page should read.
 *
 * When the viewer is showing a past dashboard version, the user can choose
 * whether the *data* under it is the data that version was authored against
 * ("as authored") or today's ("current"). That choice is a property of the
 * page, not of any one component, but it has to reach the body of every
 * `render_*` request — figures, tables, maps, images, MultiQC and the bulk
 * card compute.
 *
 * A context rather than a prop threaded through `DashboardGrid` →
 * `ComponentRenderer` → each renderer: that route is eight files deep and every
 * intermediate component would carry a prop it does not use. `availableValues`
 * already establishes the context pattern in this package.
 *
 * `null` means "read live", which is what every consumer outside a preview
 * gets, so no existing caller changes behaviour.
 */

import React, { createContext, useContext, useMemo } from 'react';

const DataVersionContext = createContext<string | null>(null);

interface DataVersionProviderProps {
  /** The dashboard version whose data should be read, or `null` for live. */
  versionId: string | null;
  children: React.ReactNode;
}

export const DataVersionProvider: React.FC<DataVersionProviderProps> = ({
  versionId,
  children,
}) => {
  const value = useMemo(() => versionId ?? null, [versionId]);
  return <DataVersionContext.Provider value={value}>{children}</DataVersionContext.Provider>;
};

/**
 * The version id to send with a render request, or `null` to read live.
 *
 * Safe outside a provider — the default is `null`, so the editor, the catalog
 * preview and every other host keep making live requests without wrapping
 * anything.
 */
export function useDataVersion(): string | null {
  return useContext(DataVersionContext);
}
