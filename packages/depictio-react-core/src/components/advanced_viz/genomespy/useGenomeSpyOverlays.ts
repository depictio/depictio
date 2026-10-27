/**
 * Feeds the overlays of a `genome_view`: the region selected on it (framed),
 * and what other tiles drive: the genome
 * browser's visible window (a dashed band) and a hovered feature (a rule).
 *
 * Primary path: the spec declares named data sources for both
 * (`buildOverlayLayers`) and this hook hands them rows through the embed's
 * named-data API (`pushOverlayRows`), so GenomeSpy draws them on its own
 * scale and they follow every zoom.
 *
 * Fallback, for an embed that has no such API or a spec without overlay layers
 * (a file-backed tile): a pointer-transparent `<div>` over the canvas, placed
 * from the genome axis' visible domain when the build exposes it. That one is
 * approximate on purpose: it spans the whole canvas width, so it ignores the
 * y-axis gutter and is a few pixels off at the plot's edges. It draws nothing
 * rather than guess when the domain is unreadable, and leaves the selection
 * out: the brush already marks it there.
 *
 * Neither path brushes, filters or zooms, and neither emits anything.
 */
import { useEffect } from 'react';
import type { RefObject } from 'react';
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

import { fallbackBoxes } from './overlayRows';
import type { HoverRow, SelectionRow, WindowRow } from './overlayRows';
import type { Contig, OverlayColors, OverlaySources } from './genomeSpySpec';
import { onScaleDomainChange, pushOverlayRows, readScaleDomain } from './useGenomeSpy';

const FALLBACK_ATTR = 'data-depictio-genomespy-overlay';

function clearFallback(el: HTMLElement | null): void {
  el?.querySelector(`[${FALLBACK_ATTR}]`)?.remove();
}

function paintFallback(
  el: HTMLElement,
  boxes: ReturnType<typeof fallbackBoxes>,
  colors: OverlayColors,
): void {
  clearFallback(el);
  if (!boxes.length) return;
  const layer = el.ownerDocument.createElement('div');
  layer.setAttribute(FALLBACK_ATTR, '');
  Object.assign(layer.style, {
    position: 'absolute',
    inset: '0',
    pointerEvents: 'none',
    overflow: 'hidden',
  });
  for (const box of boxes) {
    const mark = el.ownerDocument.createElement('div');
    const hover = box.kind === 'hover';
    Object.assign(mark.style, {
      position: 'absolute',
      top: '0',
      bottom: '0',
      left: `${box.left * 100}%`,
      width: `${box.width * 100}%`,
      minWidth: hover ? '2px' : '1px',
      background: hover ? colors.hoverColor : colors.windowColor,
      opacity: hover ? '0.9' : '0.18',
    });
    layer.appendChild(mark);
  }
  el.appendChild(layer);
}

export interface GenomeSpyOverlayInput {
  api: EmbedResult | null;
  container: RefObject<HTMLElement | null>;
  /** The spec's overlay sources, one pair per data lane; empty when it has none. */
  overlays: readonly OverlaySources[];
  contigs: readonly Contig[] | null;
  window: readonly WindowRow[];
  hover: readonly HoverRow[];
  selection: readonly SelectionRow[];
  colors: OverlayColors;
}

export function useGenomeSpyOverlays({
  api,
  container,
  overlays,
  contigs,
  window: windowRows,
  hover: hoverRows,
  selection: selectionRows,
  colors,
}: GenomeSpyOverlayInput): void {
  useEffect(() => {
    const el = container.current;
    if (!api) return undefined;
    let named = overlays.length > 0;
    for (const o of overlays) {
      const w = pushOverlayRows(api, o.window, windowRows as WindowRow[]);
      const h = pushOverlayRows(api, o.hover, hoverRows as HoverRow[]);
      const s = pushOverlayRows(api, o.selection, selectionRows as SelectionRow[]);
      if (w === null || h === null || s === null) named = false;
    }
    if (named) {
      clearFallback(el);
      return undefined;
    }
    if (!el || !contigs?.length) return undefined;
    const paint = () =>
      paintFallback(el, fallbackBoxes(contigs, readScaleDomain(api), windowRows, hoverRows), colors);
    paint();
    const off = onScaleDomainChange(api, paint);
    return () => {
      off();
      clearFallback(el);
    };
  }, [api, container, overlays, contigs, windowRows, hoverRows, selectionRows, colors]);
}
