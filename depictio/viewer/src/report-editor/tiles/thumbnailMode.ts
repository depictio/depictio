import type { StoredMetadata } from 'depictio-react-core';

/** Types the real renderer draws well at thumbnail size. */
const LIVE_TYPES = new Set(['card', 'figure', 'table', 'text', 'image', 'highlight', 'advanced_viz', 'interactive']);

/** Too heavy (maps, genome browsers, MultiQC reports) to draw once per tile. */
const HEAVY_TYPES = new Set(['jbrowse', 'multiqc', 'map']);

/** A table above this many rows is drawn from the snapshot, not live. */
export const MAX_LIVE_TABLE_ROWS = 2000;

/** Row count of a table, when the stored metadata tells (the key has varied). */
function tableRows(metadata: StoredMetadata | null | undefined): number | null {
  const m = metadata as unknown as Record<string, unknown> | null | undefined;
  for (const key of ['row_count', 'n_rows', 'num_rows', 'total_rows']) {
    const v = m?.[key];
    if (typeof v === 'number') return v;
  }
  return null;
}

export type ThumbnailMode = 'live' | 'image' | 'icon';

/**
 * How a tile is drawn, in this order:
 *  1. `live`: the app's own React renderer. For the light types, unless the
 *     live render already failed or timed out, or a table holds more than
 *     2,000 rows.
 *  2. `image`: the Plotly PNG or the HTML snapshot the preview frame sent
 *     (heavy kinds, unsupported types, failed or timed-out live renders).
 *  3. `icon`: the type icon, when the frame has sent nothing.
 */
export function thumbnailMode(input: {
  componentType: string | null | undefined;
  metadata?: StoredMetadata | null;
  liveFailed: boolean;
  hasImage: boolean;
}): ThumbnailMode {
  const type = input.componentType ?? '';
  const rows = type === 'table' ? tableRows(input.metadata) : null;
  const heavy = HEAVY_TYPES.has(type) || (rows != null && rows > MAX_LIVE_TABLE_ROWS);
  if (LIVE_TYPES.has(type) && !heavy && !input.liveFailed) return 'live';
  return input.hasImage ? 'image' : 'icon';
}

/** The enlarged view draws one component, so even the heavy kinds may be live
 *  there; only types the renderer does not know fall back to the snapshot. */
export function enlargedCanBeLive(componentType: string | null | undefined): boolean {
  const type = componentType ?? '';
  return LIVE_TYPES.has(type) || HEAVY_TYPES.has(type);
}
