/**
 * Where the Guide draws the dashboard's own components.
 *
 * The demos are the real thing: `ComponentRenderer`, `DashboardGrid`, the
 * real chrome, fetching from the same endpoints as the canvas. They are also
 * second copies of tiles the canvas holds, under the same component ids, and
 * a renderer reports about itself to the app through contexts keyed by that
 * id. Each of those reports would reach the dashboard and act on the original:
 *
 * - load status: a copy unmounting would unregister the tile's own status,
 *   and the dashboard's progress bar would count it as never loaded;
 * - autofit: a copy measured at the Guide's width would resize the tile on
 *   the canvas;
 * - the inspector: an advanced view publishes its controls to the panel, and
 *   the copy's would replace the tile's;
 * - groups: "save as group" would add to the reader's real groups;
 * - filter values: a control would list what the dashboard's filters leave.
 *
 * So each gets a provider of its own here, holding nothing of the dashboard's.
 * What a demo needs from them (its own filters, its own groups) it passes in.
 */
import React from 'react';
import {
  AdvancedVizInspectorProvider,
  AutofitScope,
  AvailableFilterValuesProvider,
  DashboardLoadingProvider,
  InspectorProvider,
  SaveGroupContext,
} from 'depictio-react-core';
import type { InspectorControl, SaveGroupApi, StoredMetadata } from 'depictio-react-core';

/** The namespace a Guide copy measures its content height under. */
const GUIDE_AUTOFIT_SCOPE = 'guide:';

export interface GuideSandboxProps {
  /** The components drawn inside: what a filter control lists values for. */
  metadata: StoredMetadata[];
  /** The demo's own groups, or none: the save-as-group action is then off. */
  saveGroup?: SaveGroupApi | null;
  /** The demo's own inspector, or none: the inspect action is then off. */
  inspector?: InspectorControl | null;
  children: React.ReactNode;
}

export const GuideSandbox: React.FC<GuideSandboxProps> = ({
  metadata,
  saveGroup = null,
  inspector = null,
  children,
}) => (
  <DashboardLoadingProvider>
    <AutofitScope value={GUIDE_AUTOFIT_SCOPE}>
      <InspectorProvider value={inspector}>
        <AdvancedVizInspectorProvider value={null}>
          <SaveGroupContext.Provider value={saveGroup}>
            <AvailableFilterValuesProvider dashboardMetadata={metadata}>
              {children}
            </AvailableFilterValuesProvider>
          </SaveGroupContext.Provider>
        </AdvancedVizInspectorProvider>
      </InspectorProvider>
    </AutofitScope>
  </DashboardLoadingProvider>
);

export default GuideSandbox;
