import { createContext, useContext } from 'react';

import type { PreviewStyles } from './previewProtocol';

export interface SnapshotSource {
  /** Tile snapshots (inert HTML) by `tab_id:component_id`. */
  snapshots: Record<string, string>;
  /** The report's look; null until the frame has sent it. */
  styles: PreviewStyles | null;
  /** Where the preview files live: the snapshots' <base>. */
  baseUrl: string | null;
}

const EMPTY: SnapshotSource = { snapshots: {}, styles: null, baseUrl: null };

export const SnapshotContext = createContext<SnapshotSource>(EMPTY);

export function useSnapshotSource(): SnapshotSource {
  return useContext(SnapshotContext);
}
