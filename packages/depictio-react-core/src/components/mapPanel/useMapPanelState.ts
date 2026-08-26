import { useCallback, useState } from 'react';

/**
 * How the panel presents itself.
 *
 * `floating` is a draggable card that sits over the dashboard; `docked` pins it
 * below the filter panel, in flow, so it never covers anything; `hidden` leaves
 * only the header control.
 */
export type MapPanelMode = 'hidden' | 'floating' | 'docked';

/** The floating card's footprint. Docked height is not on this axis — the dock
 *  is resized by dragging its top edge, which gives a pixel value rather than
 *  one of two presets. */
export type MapPanelCardSize = 'compact' | 'expanded';

export interface MapPanelState {
  mode: MapPanelMode;
  cardSize: MapPanelCardSize;
  /** Card's top-left corner in viewport pixels. `null` means "use the default
   *  bottom-right anchor". Only meaningful while floating. */
  x: number | null;
  y: number | null;
  /** Free-dragged card size in pixels (corner resize). `null` means "use the
   *  `cardSize` preset". Only meaningful while floating; the compact/expanded
   *  toggle clears it, so the presets stay reachable. */
  cardWidth: number | null;
  cardHeight: number | null;
  /** Dock height in pixels, as dragged. `null` means "use the default". Only
   *  meaningful while docked. */
  dockHeight: number | null;
  /** Docked, folded down to its title bar. Its own axis rather than a fourth
   *  `mode`: the panel is still docked, and unfolding has to bring back the
   *  height the viewer dragged, not a default. */
  dockCollapsed: boolean;
  /** Whether the viewer has folded the figure's legend / colour bar away. It
   *  overlays the map rather than shrinking it, but on a narrow dock a long
   *  category list still covers most of the tiles. */
  legendHidden: boolean;
}

const STORAGE_PREFIX = 'depictio:map-panel:';

const DEFAULT_AXES: Pick<MapPanelState, 'mode' | 'cardSize'> = {
  mode: 'floating',
  cardSize: 'compact',
};

/** Translate the author's `floating_initial_state` into the two axes the panel
 *  actually runs on. */
export function axesFromAuthorDefault(
  value: string | undefined,
): Pick<MapPanelState, 'mode' | 'cardSize'> {
  switch (value) {
    case 'hidden':
      return { mode: 'hidden', cardSize: 'compact' };
    case 'docked':
      return { mode: 'docked', cardSize: 'compact' };
    case 'expanded':
      return { mode: 'floating', cardSize: 'expanded' };
    default:
      return DEFAULT_AXES;
  }
}

function axesFromStored(
  mode: unknown,
  cardSize: unknown,
): Pick<MapPanelState, 'mode' | 'cardSize'> | null {
  const size: MapPanelCardSize = cardSize === 'expanded' ? 'expanded' : 'compact';
  if (mode === 'hidden' || mode === 'docked' || mode === 'floating') {
    return { mode, cardSize: size };
  }
  return null;
}

/** Everything outside the two axes, at its default. Entries written before a
 *  field existed simply fall back to these. */
const DEFAULT_VIEW: Omit<MapPanelState, 'mode' | 'cardSize'> = {
  x: null,
  y: null,
  cardWidth: null,
  cardHeight: null,
  dockHeight: null,
  dockCollapsed: false,
  legendHidden: false,
};

function readState(familyId: string | null): MapPanelState | null {
  if (!familyId) return null;
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${familyId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const axes = axesFromStored(parsed.mode, parsed.cardSize);
    if (!axes) return null;
    return {
      ...axes,
      ...DEFAULT_VIEW,
      x: typeof parsed.x === 'number' ? parsed.x : null,
      y: typeof parsed.y === 'number' ? parsed.y : null,
      cardWidth: typeof parsed.cardWidth === 'number' ? parsed.cardWidth : null,
      cardHeight: typeof parsed.cardHeight === 'number' ? parsed.cardHeight : null,
      dockHeight: typeof parsed.dockHeight === 'number' ? parsed.dockHeight : null,
      dockCollapsed: parsed.dockCollapsed === true,
      legendHidden: parsed.legendHidden === true,
    };
  } catch {
    // Private-browsing or corrupted entry: fall back to the author's default.
    return null;
  }
}

function writeState(familyId: string | null, state: MapPanelState): void {
  if (!familyId) return;
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${familyId}`, JSON.stringify(state));
  } catch {
    // Storage unavailable (private browsing, quota): the panel still works for
    // this page load, it just will not remember across tab switches.
  }
}

/**
 * Panel state persisted per *dashboard family*, not per tab.
 *
 * Keying on the family id is what makes the panel feel dashboard-wide: tab
 * switches are full page navigations, so in-memory state cannot survive them
 * and the panel would otherwise snap back to its default on every switch.
 * This mirrors how the ingestion banner is keyed by project rather than by
 * dashboard (`App.tsx`).
 *
 * `familyId` arrives asynchronously (it comes back with the floating
 * components). Until it does we hold the author's default and persist nothing,
 * then adopt whatever the viewer had saved once the key is known.
 */
export function useMapPanelState(
  familyId: string | null,
  authorDefault: string | undefined,
) {
  const [state, setState] = useState<MapPanelState>(() => ({
    ...axesFromAuthorDefault(authorDefault),
    ...DEFAULT_VIEW,
  }));

  // Which family `state` was resolved for.
  const [resolvedFor, setResolvedFor] = useState<string | null>(null);

  // Adopt the saved state as soon as the family id resolves; the viewer's own
  // preference wins over the author's default from then on. During render
  // rather than from an effect, which is React's own way of deriving state from
  // a changed input: an effect would commit one render of the author's default
  // first, and for a dock the viewer had left folded away that render mounts
  // the map and fires its request before anything folds it back up.
  if (familyId && familyId !== resolvedFor) {
    setResolvedFor(familyId);
    setState(
      readState(familyId) ?? {
        ...axesFromAuthorDefault(authorDefault),
        ...DEFAULT_VIEW,
      },
    );
  }

  // Persisting from the setters rather than from an effect on `state` is
  // deliberate: an effect would fire on the render that adopts the stored
  // value and write it straight back, racing the adoption itself.
  const update = useCallback(
    (patch: Partial<MapPanelState>) => {
      const next = { ...state, ...patch };
      setState(next);
      writeState(familyId, next);
    },
    [familyId, state],
  );

  const setMode = useCallback((mode: MapPanelMode) => update({ mode }), [update]);
  const setCardSize = useCallback(
    // Choosing a preset clears any free-dragged size — otherwise the toggle
    // would appear dead while a custom size overrides both presets.
    (cardSize: MapPanelCardSize) => update({ cardSize, cardWidth: null, cardHeight: null }),
    [update],
  );
  const setPosition = useCallback((x: number, y: number) => update({ x, y }), [update]);
  /** Committed corner-resize size in pixels; `null` restores the preset. */
  const setCardDims = useCallback(
    (cardWidth: number | null, cardHeight: number | null) => update({ cardWidth, cardHeight }),
    [update],
  );
  const setDockHeight = useCallback(
    (dockHeight: number | null) => update({ dockHeight }),
    [update],
  );
  const setDockCollapsed = useCallback(
    (dockCollapsed: boolean) => update({ dockCollapsed }),
    [update],
  );
  const setLegendHidden = useCallback(
    (legendHidden: boolean) => update({ legendHidden }),
    [update],
  );

  return {
    state,
    setMode,
    setCardSize,
    setCardDims,
    setPosition,
    setDockHeight,
    setDockCollapsed,
    setLegendHidden,
  };
}
