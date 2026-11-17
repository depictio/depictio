import { useEffect, useRef, type RefObject } from 'react';

import { genomeDebugEnabled, traceGenome } from '../genomeLink/genomeDebug';

/** True when Escape belongs to a field (closing its dropdown, leaving it), not to
 *  the tile: an input, a textarea, a select or anything editable. */
export function escapeOwnedByField(target: EventTarget | null): boolean {
  if (!target || typeof (target as Element).closest !== 'function') return false;
  const el = target as HTMLElement;
  if (el.isContentEditable) return true;
  return Boolean(el.closest('input, textarea, select, [contenteditable="true"]'));
}

/** Whether an Escape keydown should clear the tile's selection: the pointer is
 *  over the tile or the focus is inside it, no field takes the key, and no
 *  dialog or menu handled it first. */
export function shouldClearOnEscape(
  event: Pick<KeyboardEvent, 'key' | 'defaultPrevented' | 'target'>,
  hovered: boolean,
  focusInside: boolean,
): boolean {
  if (event.key !== 'Escape' || event.defaultPrevented) return false;
  if (!hovered && !focusInside) return false;
  return !escapeOwnedByField(event.target);
}

/**
 * Escape clears the tile's own selection (a lasso, a brush, picked rows) while
 * the pointer is over the tile or the focus is in it. Returns the pointer
 * handlers to spread on the tile's root.
 */
export function useEscapeClear(
  rootRef: RefObject<HTMLElement | null>,
  onClear: (() => void) | undefined,
  /** The tile's index, for the genome trace (`genomeDebug.ts`). */
  traceIndex?: string,
): { onPointerEnter: () => void; onPointerLeave: () => void } {
  const hovered = useRef(false);
  const clearRef = useRef(onClear);
  clearRef.current = onClear;
  const active = Boolean(onClear);
  // With the trace on, an Escape that clears nothing is worth a line too.
  const listen = active || (Boolean(traceIndex) && genomeDebugEnabled());

  useEffect(() => {
    if (!listen) return undefined;
    const onKey = (event: KeyboardEvent) => {
      const root = rootRef.current;
      const focusInside = !!root && root.contains(document.activeElement);
      if (!shouldClearOnEscape(event, hovered.current, focusInside)) return;
      if (!clearRef.current) {
        if (traceIndex) traceGenome(traceIndex, 'Escape: nothing of this tile to clear');
        return;
      }
      if (traceIndex) traceGenome(traceIndex, 'Escape: clearing the tile selection');
      event.preventDefault();
      clearRef.current();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [listen, rootRef, traceIndex]);

  return {
    onPointerEnter: () => {
      hovered.current = true;
    },
    onPointerLeave: () => {
      hovered.current = false;
    },
  };
}
