import type { FloatingComponent, StoredMetadata } from '../../api';

/**
 * What a floating panel can hold.
 *
 * The panel started as the dashboard's map and is now one shell for two
 * things: a `map`, and a `structure` (a `molecule_3d` advanced viz, the "light
 * 3D module"). Each kind gets its own panel instance (its own header control,
 * its own saved position and size), so a map and a structure can sit on screen
 * together. Everything the two share lives in `useMapPanel`, `MapPanelBody`,
 * `MapPanelSurface` and `MapPanelDock`, which read this table for what differs.
 */
export type FloatingPanelKind = 'map' | 'structure';

/**
 * The advanced viz kinds that may float. Mirrors `FLOATING_ADVANCED_VIZ_KINDS`
 * in depictio/models/components/constants.py, which is where the author's
 * `placement: floating` is validated and where the cross-tab endpoint decides
 * what to serve: widen both together. A kind missing here is left on the grid
 * rather than dropped from it, so a mismatch shows a tile in the wrong place
 * instead of losing one.
 */
export const FLOATING_VIZ_KINDS: ReadonlySet<string> = new Set(['molecule_3d']);

/** The fields `floatingPanelKindOf` reads: kept narrow so a test can pass a literal. */
type FloatingCandidate = Pick<StoredMetadata, 'component_type' | 'placement'> & {
  viz_kind?: unknown;
};

/**
 * Which panel a component belongs in, or `null` when it is a normal grid tile.
 *
 * Both halves of "lifted out of the grid" ask this one question: the shells
 * leave a floating component off the grid, and the panels pick up what the
 * family's cross-tab request returned.
 */
export function floatingPanelKindOf(m: FloatingCandidate): FloatingPanelKind | null {
  if (m.placement !== 'floating') return null;
  if (m.component_type === 'map') return 'map';
  if (
    m.component_type === 'advanced_viz' &&
    typeof m.viz_kind === 'string' &&
    FLOATING_VIZ_KINDS.has(m.viz_kind)
  ) {
    return 'structure';
  }
  return null;
}

/** True for a component the grid must not draw because a floating panel does. */
export function isFloatingComponent(m: FloatingCandidate): boolean {
  return floatingPanelKindOf(m) !== null;
}

/** The family's floating components, split by the panel that shows them. Order
 *  (tab order, then declaration order) is kept within each kind. */
export function partitionFloating(
  floating: readonly FloatingComponent[],
): Record<FloatingPanelKind, FloatingComponent[]> {
  const out: Record<FloatingPanelKind, FloatingComponent[]> = { map: [], structure: [] };
  for (const c of floating) {
    const kind = floatingPanelKindOf(c.metadata);
    if (kind) out[kind].push(c);
  }
  return out;
}

export interface PanelKindSpec {
  /** localStorage key prefix; the dashboard family id is appended. The map's is
   *  the one it has always used, so a saved map layout survives. */
  storagePrefix: string;
  /** Lower-case noun for labels and tooltips ("Hide map panel"). */
  noun: string;
  /** Capitalised name, and the title of a component that has none. */
  label: string;
  /** What "the thing" is called in a sentence ("Show the map"). */
  thing: string;
  icon: string;
  /** The header control's glyph while the panel is hidden. */
  hiddenIcon: string;
  /** `data-testid` stem: `<stem>-surface`, `<stem>-dock`, `<stem>-control`. */
  testId: string;
  /** The floating card's compact footprint, px. Small enough to leave the
   *  dashboard readable behind it; a structure gets a little more height than a
   *  map because its card keeps a header row of its own above the viewer. */
  compact: { width: number; height: number };
  /** Where the floating card sits until it is dragged. The map keeps the
   *  bottom-right corner clear of the Notes button; the structure takes the
   *  top-right, below the header whichever chrome style draws it (the header's
   *  height is `--dc-header-h`), so the two never start on top of each other. */
  anchor: { right: number; top?: string; bottom?: number };
}

export const PANEL_KINDS: Record<FloatingPanelKind, PanelKindSpec> = {
  map: {
    storagePrefix: 'depictio:map-panel:',
    noun: 'map',
    label: 'Map',
    thing: 'the map',
    icon: 'mdi:map-marker-multiple',
    hiddenIcon: 'mdi:map-marker-off-outline',
    testId: 'map-panel',
    compact: { width: 360, height: 280 },
    anchor: { right: 16, bottom: 72 },
  },
  structure: {
    storagePrefix: 'depictio:structure-panel:',
    noun: '3D structure',
    label: '3D structure',
    thing: 'the structure',
    icon: 'mdi:cube-outline',
    hiddenIcon: 'mdi:cube-off-outline',
    testId: 'structure-panel',
    compact: { width: 380, height: 340 },
    anchor: { right: 16, top: 'calc(var(--dc-header-h, 50px) + 16px)' },
  },
};
