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

/**
 * The top dock is one line: as many controls as fit beside the placement
 * picker, the rest behind "More options". Five at most, so a wide tile still
 * reads as a toolbar and not a form.
 */
export const DOCK_TOP_MAX = 5;

export interface FitInlineOptions {
  /** Space between two inline controls, px. */
  gap?: number;
  /** Room the "More options" button takes (with its gap) once anything is
   *  folded, px. Not reserved when every control fits. */
  reserve?: number;
  /** Most controls shown inline, whatever the width. */
  max?: number;
}

/**
 * Which of a panel's controls fit on the top dock's single line.
 *
 * The same order and the same rule as `pickEssentials` (only controls that do
 * something now, most important first), but bounded by width instead of a
 * count: `widths` are the controls' own widths, measured with every one of
 * them shown, and `available` is the line's width. Stops at the first control
 * that does not fit rather than skipping to a narrower one further down, so a
 * less important control never jumps ahead of a more important one. The first
 * live control is always kept, even alone too wide for the line: a panel with
 * nothing inline but "More options" is a popover with extra steps.
 */
export function fitInline(
  widths: readonly number[],
  live: readonly boolean[],
  available: number,
  { gap = 0, reserve = 0, max = Number.POSITIVE_INFINITY }: FitInlineOptions = {},
): boolean[] {
  const pick = (budget: number): boolean[] => {
    let used = 0;
    let shown = 0;
    let stopped = false;
    return live.map((ok, i) => {
      if (!ok || stopped || shown >= max) return false;
      const w = Math.max(0, Number.isFinite(widths[i]) ? widths[i] : 0);
      const next = used + (shown > 0 ? gap : 0) + w;
      if (shown > 0 && next > budget) {
        stopped = true;
        return false;
      }
      used = next;
      shown++;
      return true;
    });
  };
  const all = pick(available);
  // Everything inline: no "More options" button, so no room to keep for it.
  if (all.every(Boolean)) return all;
  return pick(available - reserve);
}

/**
 * Width of an inline control on the top dock's line, from the width it takes
 * in a column: about two thirds, enough for a number box's digits or a short
 * dropdown value, never under 56 px. Content-sized controls stay so.
 */
export function rowControlWidth(width: number | 'auto' | 'fill'): number | 'auto' {
  if (width === 'auto' || width === 'fill') return 'auto';
  return Math.max(56, Math.round(width * 0.65));
}

export interface GroupPlan {
  /** The caption drawn over the group, or null for none. */
  caption: string | null;
  /** The group's only control is unlabelled and takes the group's title as
   *  its own label (on the single line, where captions are not drawn). */
  adoptTitle: boolean;
}

function sameLabel(a: string | null | undefined, b: string): boolean {
  return (a ?? '').trim().toLowerCase() === b.trim().toLowerCase();
}

/**
 * How a titled group of controls (`VizControlGroup`) is labelled.
 *
 * On the top dock's single line (`row`) groups are not drawn at all: their
 * controls join the line, each under its own label, which is what keeps the
 * line one line. A group of one unlabelled control lends it its title, so it
 * is not left unnamed. Stacked (`stack`: the column, the strip, the popover),
 * the caption is dropped only where it would repeat: a "Legend" group holding
 * nothing but a "Legend" dropdown said "Legend" twice.
 *
 * `labels` are the group's controls' own labels, null for one without a text
 * label.
 */
export function planGroup(
  title: string,
  labels: readonly (string | null | undefined)[],
  layout: 'row' | 'stack',
): GroupPlan {
  const single = labels.length === 1;
  if (layout === 'row') {
    return { caption: null, adoptTitle: single && !(labels[0] ?? '').trim() };
  }
  return {
    caption: single && sameLabel(labels[0], title) ? null : title,
    adoptTitle: false,
  };
}
