import { createContext, useContext } from 'react';

import type { AnalysisState } from 'depictio-react-core';

import type { PreviewStyles } from './previewProtocol';

export interface SnapshotSource {
  /** Tile snapshots (inert HTML) by `tab_id:component_id`. */
  snapshots: Record<string, string>;
  /** The report's look; null until the frame has sent it. */
  styles: PreviewStyles | null;
  /** Where the preview files live: the snapshots' <base>. */
  baseUrl: string | null;
  /** The report's analysis state (the layer's `state`): the filters and groups
   *  the live tiles are drawn with. Absent or null = unfiltered. */
  state?: AnalysisState | null;
}

const EMPTY: SnapshotSource = { snapshots: {}, styles: null, baseUrl: null };

export const SnapshotContext = createContext<SnapshotSource>(EMPTY);

export function useSnapshotSource(): SnapshotSource {
  return useContext(SnapshotContext);
}
