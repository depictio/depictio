import { createContext } from 'react';

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
 */
export type ControlsPlacement = 'auto' | 'right' | 'top' | 'popover';
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
  if (p === 'popover') return null;
  if (p === 'right' || p === 'top') return p;
  if (showcase || rowShare == null || width <= 0) return null;
  if (rowShare >= FULL_ROW_SHARE && width >= MIN_RIGHT_DOCK_PX) return 'right';
  return width >= MIN_TOP_DOCK_PX ? 'top' : null;
}

export function isControlsPlacement(v: unknown): v is ControlsPlacement {
  return v === 'auto' || v === 'right' || v === 'top' || v === 'popover';
}

/** Handed by the dispatch to the frame: the component's setting, and whether
 *  the viewer folded the docked panel away. */
export interface ControlsDockState {
  placement: ControlsPlacement | null;
  collapsed: boolean;
}

export const ControlsDockContext = createContext<ControlsDockState | null>(null);
