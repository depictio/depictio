import { createContext, type ReactNode } from 'react';

/**
 * Where an advanced visualisation's controls sit.
 *
 * Behind the settings icon, every control took a hover and a click to reach,
 * and a reader could not see how the figure was set. Docked, they stay in
 * view: beside the plot on a tile that spans its row (a column of controls
 * costs little width there), above it on a narrower one (a row of controls
 * costs little height). Too narrow for either, or a landing-page card meant
 * to be read at a glance, they stay behind the icon. The icon folds a docked
 * panel away and back.
 *
 * `overlay` is the one placement that is not a dock: the panel floats over the
 * plot, top right, and the figure keeps its full size. It suits a tile with
 * little room (a workbench cell) where a column or a row of controls would
 * take the plot's.
 */
export type ControlsPlacement = 'auto' | 'right' | 'top' | 'popover' | 'overlay';
export type DockSide = 'right' | 'top';

/** A tile at least this share of its row's width spans it. */
export const FULL_ROW_SHARE = 0.9;
/** Narrower than this, a column of controls leaves the plot too little. */
export const MIN_RIGHT_DOCK_PX = 720;
/** Narrower than this, a row of controls is a stack that buries the plot. */
export const MIN_TOP_DOCK_PX = 300;

export interface DockMeasure {
  /** The tile's width over its grid row's, or null off a grid (a builder
   *  preview, the catalog). */
  rowShare: number | null;
  /** The tile's own width, px. */
  width: number;
  /** The `minimal` landing-page card. */
  showcase: boolean;
}

/** Where the controls go, or null for behind the settings icon. */
export function resolveDock(
  placement: ControlsPlacement | null | undefined,
  { rowShare, width, showcase }: DockMeasure,
): DockSide | null {
  const p = placement ?? 'auto';
  if (p === 'popover' || p === 'overlay') return null;
  if (p === 'right' || p === 'top') return p;
  if (showcase || rowShare == null || width <= 0) return null;
  if (rowShare >= FULL_ROW_SHARE && width >= MIN_RIGHT_DOCK_PX) return 'right';
  return width >= MIN_TOP_DOCK_PX ? 'top' : null;
}

export function isControlsPlacement(v: unknown): v is ControlsPlacement {
  return v === 'auto' || v === 'right' || v === 'top' || v === 'popover' || v === 'overlay';
}

/**
 * The view a compact tile's header menu offers, in the menu's order. `hidden`
 * is the folded state; the other three are where the controls are drawn.
 */
export type ControlsView = 'hidden' | 'overlay' | 'top' | 'right';
export const CONTROLS_VIEWS: readonly ControlsView[] = ['hidden', 'overlay', 'top', 'right'];

/**
 * What a reader (or an editor's session) picked: a view, or `open` for the
 * fold button's "show" (the controls in the component's own placement, which
 * on `auto` the tile's width decides).
 *
 * Kept per component in localStorage under the key the fold always used, so
 * the stored string extends the old one: `1` folded, `0` opened on purpose,
 * and now `overlay`, `top`, `right`. An old reader meeting a new value finds
 * nothing it knows and falls back to the layout's default.
 */
export type ControlsChoice = ControlsView | 'open';

export function parseChoice(raw: string | null | undefined): ControlsChoice | null {
  if (raw === '1') return 'hidden';
  if (raw === '0') return 'open';
  return raw === 'overlay' || raw === 'top' || raw === 'right' ? raw : null;
}

export function serializeChoice(choice: ControlsChoice): string {
  return choice === 'hidden' ? '1' : choice === 'open' ? '0' : choice;
}

/**
 * Where the controls go and whether they are folded, from the viewer's choice,
 * the component's own `controls_placement` and the section's density.
 *
 * With no choice, a workbench cell starts folded unless the author stated a
 * placement (`auto`, `right`, `top` and `overlay` start open: the author asked
 * for them); everywhere else they start open, as they always did.
 */
export function resolveControls(
  choice: ControlsChoice | null,
  stored: ControlsPlacement | null,
  compact: boolean,
): { placement: ControlsPlacement | null; collapsed: boolean } {
  if (choice === 'hidden') return { placement: stored, collapsed: true };
  if (choice === 'open') return { placement: stored, collapsed: false };
  if (choice) return { placement: choice, collapsed: false };
  return { placement: stored, collapsed: compact && stored === null };
}

/**
 * The placement an editor saves on the component for a menu pick. `hidden`
 * is `popover`, which is what that value says: behind the icon. The other
 * views are their own placement.
 */
export function placementForView(view: ControlsView): ControlsPlacement {
  return view === 'hidden' ? 'popover' : view;
}

/** The view on screen now, which is what the menu checks: folded or with
 *  nothing to show (a tile too narrow to dock) is `hidden`. */
export function currentView(
  overlay: boolean,
  dockSide: DockSide | null,
  collapsed: boolean,
): ControlsView {
  if (collapsed) return 'hidden';
  if (overlay) return 'overlay';
  return dockSide ?? 'hidden';
}

/** Handed by the dispatch to the frame: the placement in force (the
 *  component's own, or the one a viewer picked), and whether the panel is
 *  folded away. */
export interface ControlsDockState {
  placement: ControlsPlacement | null;
  collapsed: boolean;
  /** Folds the docked panel away or brings it back, in the view it was last
   *  shown in: the chrome's settings icon. */
  toggle?: () => void;
  /** Picks where the controls are drawn: the menu a compact header draws (the
   *  chrome's settings icon is hover-only). Absent where the tile cannot take
   *  a choice, e.g. one split into panels. */
  setView?: (view: ControlsView) => void;
}

export const ControlsDockContext = createContext<ControlsDockState | null>(null);

/**
 * A control that a router puts ahead of the renderer's own, above the "More
 * options" fold: the switch between the views of one component (volcano, MA,
 * QQ), which belongs to none of the renderers it picks between.
 */
export const ControlsLeadContext = createContext<ReactNode>(null);

/** How many controls a docked panel shows before "More options". */
export const DOCK_ESSENTIALS = 3;

/**
 * Which of a panel's controls show before "More options": the first `max`
 * that do something now, in the order the renderer lists them (most important
 * first). A control that is disabled or a toggle that is off is not one of
 * them, nor is a line of text; they wait under "More options" with the rest.
 */
export function pickEssentials(live: readonly boolean[], max = DOCK_ESSENTIALS): boolean[] {
  let shown = 0;
  return live.map((ok) => {
    if (!ok || shown >= max) return false;
    shown++;
    return true;
  });
}
