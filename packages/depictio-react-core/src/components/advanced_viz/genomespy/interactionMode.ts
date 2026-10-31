/**
 * What the pointer does on a `genome_view`'s genome axis.
 *
 * Three modes, switched from the tile's header (`InteractionModeSwitch`), kept
 * apart from the Settings panel because they are a tool the reader picks up and
 * puts down, not a property of the figure:
 *
 *  - `pointer`: hover tooltips and clicks. A drag does nothing, the wheel
 *    scrolls the page (Cmd / Ctrl + wheel still zooms, as on every figure).
 *  - `pan` (the default): a drag moves the view, the wheel zooms; hover
 *    tooltips and clicks work as in `pointer`.
 *  - `select`: a drag draws the region brush, which publishes the region.
 *
 * GenomeSpy ties panning to a plain drag and the brush to a drag the interval
 * param's `on` accepts, so the mode is two things: the brush trigger in the
 * spec (pure, below) and, for `pointer`, a guard on the container that keeps
 * the drag from reaching GenomeSpy's pan (`attachInteractionMode`). A mode
 * change rebuilds the embed like any other spec change, and the view it showed
 * is restored (`restoreViewDomain`).
 */

export type InteractionMode = 'pointer' | 'pan' | 'select';

export const INTERACTION_MODES: readonly InteractionMode[] = ['pointer', 'pan', 'select'];

/** The slice of a `genome_view` config that names a mode. */
export interface InteractionModeConfig {
  interaction_mode?: InteractionMode | null;
  /** The field older dashboards carry: it decides the opening mode when
   *  `interaction_mode` is unset. */
  drag_mode?: 'select' | 'pan' | null;
}

const isMode = (v: unknown): v is InteractionMode =>
  typeof v === 'string' && (INTERACTION_MODES as readonly string[]).includes(v);

/** The mode a tile opens in: its own `interaction_mode`, else what the older
 *  `drag_mode` asks for, else pan (a genome axis is read by moving along it). */
export function initialInteractionMode(config: InteractionModeConfig): InteractionMode {
  if (isMode(config.interaction_mode)) return config.interaction_mode;
  if (config.drag_mode === 'pan') return 'pan';
  if (config.drag_mode === 'select') return 'select';
  return 'pan';
}

/**
 * The mode a *spec* is built for. A config that names neither field builds the
 * brush spec it always has (a plain drag brushes): the pointer default belongs
 * to the renderer, which resolves it with {@link initialInteractionMode}
 * before it builds, so a caller of the builder alone keeps the old shape.
 */
export function specInteractionMode(config: InteractionModeConfig): InteractionMode {
  if (isMode(config.interaction_mode)) return config.interaction_mode;
  return config.drag_mode === 'pan' ? 'pan' : 'select';
}

/** The interval param's `on`: which mouse-down starts a brush. */
export type BrushTrigger = 'mousedown' | { type: 'mousedown'; filter: string };

/**
 * The brush trigger of a mode. Select takes a plain drag. Pan leaves the plain
 * drag to the pan and takes shift + drag, GenomeSpy's own default on a
 * zoomable axis. The pointer takes none: a filter that is never true.
 */
export function brushTrigger(mode: InteractionMode): BrushTrigger {
  if (mode === 'select') return 'mousedown';
  if (mode === 'pan') return { type: 'mousedown', filter: 'event.shiftKey' };
  return { type: 'mousedown', filter: 'false' };
}

/** The cursor a lane shows over empty space; a mark under the pointer sets its
 *  own. Unset lets the canvas keep the arrow. */
export function laneCursor(mode: InteractionMode): string | undefined {
  if (mode === 'select') return 'crosshair';
  if (mode === 'pan') return 'grab';
  return undefined;
}

/** Whether a plain wheel zooms the axis (otherwise the page scrolls and only
 *  Cmd / Ctrl + wheel zooms). */
export function wheelZooms(mode: InteractionMode): boolean {
  return mode === 'pan';
}

/** What the zoom hint adds after "Cmd + scroll to zoom". */
export function modeHint(mode: InteractionMode, brushEnabled: boolean): string {
  if (mode === 'select') return brushEnabled ? 'drag to select a region' : 'select is off on this tile';
  if (mode === 'pan') return 'drag to pan';
  return brushEnabled ? 'switch to pan or select to drag' : 'switch to pan to drag';
}

/** Every label the switch shows, with the sentence its tooltip says. */
export const MODE_LABELS: Record<InteractionMode, { label: string; tooltip: string; icon: string }> = {
  pointer: {
    label: 'Pointer',
    tooltip: 'Pointer (V): hover for details, click a mark. The wheel scrolls the page.',
    icon: 'tabler:pointer',
  },
  pan: {
    label: 'Pan',
    tooltip: 'Pan (H): drag moves the view, the wheel zooms.',
    icon: 'tabler:hand-grab',
  },
  select: {
    label: 'Select',
    tooltip: 'Select (M): drag a region to filter the dashboard and move the linked browsers.',
    icon: 'tabler:marquee-2',
  },
};

/** The key that picks each mode while the pointer is over the tile, as in
 *  drawing tools: V the pointer, H the hand, M the marquee. */
export const MODE_KEYS: Record<string, InteractionMode> = { v: 'pointer', h: 'pan', m: 'select' };

/** The mode a key press asks for, or null when the key is not a mode key,
 *  carries a modifier, or asks for Select on a tile that cannot take it. */
export function modeForKey(
  e: { key: string; altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean },
  selectEnabled: boolean,
): InteractionMode | null {
  if (e.altKey || e.ctrlKey || e.metaKey) return null;
  const mode = MODE_KEYS[e.key.toLowerCase()] ?? null;
  if (mode === 'select' && !selectEnabled) return null;
  return mode;
}

/** Whether a key press comes from a field the reader is typing in. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.tagName !== 'string') return false;
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
}

/** The slice of a document the guard listens on. */
interface GuardDocument {
  addEventListener: (type: string, fn: (e: Event) => void, capture: boolean) => void;
  removeEventListener: (type: string, fn: (e: Event) => void, capture: boolean) => void;
}

/** The slice of the container the guard listens on. */
interface GuardTarget {
  ownerDocument: GuardDocument;
  addEventListener: (type: string, fn: (e: MouseEvent) => void, options: { capture: boolean }) => void;
  removeEventListener: (type: string, fn: (e: MouseEvent) => void, options: { capture: boolean }) => void;
}

/**
 * In pointer mode, keep a drag from panning the axis.
 *
 * GenomeSpy starts a pan on the canvas' `mousedown` and follows it with
 * `mousemove` listeners it puts on the document. The press is left alone, so
 * the tooltip, the click and the press-and-hold sticky tooltip all work; only
 * the moves that follow it, until the button is up, are stopped before any
 * listener sees them. A click is a press and a release with no move between
 * them, and is not affected. Any other mode needs no guard.
 *
 * Returns the function that removes it.
 */
export function attachInteractionMode(el: GuardTarget, mode: InteractionMode): () => void {
  if (mode !== 'pointer') return () => {};
  const doc = el.ownerDocument;
  let release: (() => void) | null = null;

  const onDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    release?.();
    const freeze = (ev: Event) => {
      // A release outside the window never arrives: no button held means the
      // drag is over.
      if ((ev as MouseEvent).buttons === 0) {
        end();
        return;
      }
      ev.stopImmediatePropagation();
    };
    const end = () => {
      doc.removeEventListener('mousemove', freeze, true);
      doc.removeEventListener('mouseup', end, true);
      release = null;
    };
    // On the document, in the capture phase, before GenomeSpy adds its own.
    doc.addEventListener('mousemove', freeze, true);
    doc.addEventListener('mouseup', end, true);
    release = end;
  };

  el.addEventListener('mousedown', onDown, { capture: true });
  return () => {
    release?.();
    el.removeEventListener('mousedown', onDown, { capture: true });
  };
}
