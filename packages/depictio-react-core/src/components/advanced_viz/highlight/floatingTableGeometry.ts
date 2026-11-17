/**
 * Where a tile's floating data table sits and how big it is, remembered per
 * viewer. Pure helpers: the component reads and writes `localStorage` around
 * them, wrapped in try/catch because storage can be absent or full.
 */

export interface TableGeometry {
  /** Top-left corner, px; null until the card has been dragged. */
  x: number | null;
  y: number | null;
  width: number;
  height: number;
}

export const DEFAULT_TABLE_SIZE = { width: 560, height: 420 } as const;
const MIN_SIZE = { width: 280, height: 200 } as const;
/** Gap from the viewport edge for the card's first position. */
const EDGE_GAP = 16;
/** Clear of the Notes button and the dock that sit in the bottom-right corner. */
const BOTTOM_GAP = 72;

export const TABLE_PANEL_STORAGE_PREFIX = 'depictio:viz-table-panel:';

export function storageKey(index: string): string {
  return `${TABLE_PANEL_STORAGE_PREFIX}${index}`;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export function defaultGeometry(): TableGeometry {
  return { x: null, y: null, ...DEFAULT_TABLE_SIZE };
}

/** A stored geometry, or the default when `raw` is missing or malformed. A size
 *  below the card's minimum is raised to it; a half-saved position is dropped. */
export function parseGeometry(raw: string | null | undefined): TableGeometry {
  if (!raw) return defaultGeometry();
  try {
    const v = JSON.parse(raw) as Partial<Record<keyof TableGeometry, unknown>> | null;
    if (!v || typeof v !== 'object') return defaultGeometry();
    const placed = finite(v.x) && finite(v.y);
    return {
      x: placed ? (v.x as number) : null,
      y: placed ? (v.y as number) : null,
      width: finite(v.width) ? Math.max(MIN_SIZE.width, v.width) : DEFAULT_TABLE_SIZE.width,
      height: finite(v.height) ? Math.max(MIN_SIZE.height, v.height) : DEFAULT_TABLE_SIZE.height,
    };
  } catch {
    return defaultGeometry();
  }
}

export function serializeGeometry(g: TableGeometry): string {
  return JSON.stringify(g);
}

/** The card's size fitted to the viewport, so a saved size from a bigger screen
 *  never overflows a smaller one. */
export function fitSize(
  g: Pick<TableGeometry, 'width' | 'height'>,
  viewport: { width: number; height: number },
): { width: number; height: number } {
  return {
    width: Math.max(MIN_SIZE.width, Math.min(g.width, viewport.width - 2 * EDGE_GAP)),
    height: Math.max(MIN_SIZE.height, Math.min(g.height, viewport.height - 2 * EDGE_GAP)),
  };
}

/** Where the card first appears: bottom-right, above the corner furniture. */
export function initialPosition(
  size: { width: number; height: number },
  viewport: { width: number; height: number },
): { x: number; y: number } {
  return {
    x: Math.max(EDGE_GAP, viewport.width - size.width - EDGE_GAP),
    y: Math.max(EDGE_GAP, viewport.height - size.height - BOTTOM_GAP),
  };
}
