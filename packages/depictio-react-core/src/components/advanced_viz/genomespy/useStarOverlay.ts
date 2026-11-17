/**
 * Draws a `genome_view`'s `top_stars` as SVG stars over the GenomeSpy canvas.
 *
 * The spec (`buildDataLane`) keeps the starred rows as an invisible point
 * layer, so the tooltip and the pointer cursor still work; the visible star is
 * the overlay's, because GenomeSpy has no star shape (see `starOverlay.ts`).
 *
 * Placement is exact, not estimated. Per lane it reads, through the public
 * embed API: the lane's last rendered layout box (`views.getLayoutBounds`,
 * CSS pixels of the canvas), the genome axis' visible linearised domain and the
 * lane's score domain (`getScaleResolutionByName(...).getDomain()`), and maps
 * every starred row with them (`placeStars`). It redraws when the genome or a
 * score scale changes domain (a zoom, a pan, an animated transition),
 * when a layout pass completes (`views.subscribeToLayout`: a resize, a lane
 * appearing) and when the container resizes, and the rows are read afresh on
 * every redraw. The SVG ignores the pointer, so the canvas keeps every gesture.
 */
import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

import { GENOME_SCALE_NAME } from './genomeSpySpec';
import type { Contig, StarLane } from './genomeSpySpec';
import { contigOffsets, intersectBounds, placeStars, starPath, starRowsOf, starRadius } from './starOverlay';
import type { Bounds } from './starOverlay';
import { isGenomeSpyLive } from './useGenomeSpy';

/** Marks the overlay's `<svg>` (tests and tooling find it by this). */
export const STAR_OVERLAY_ATTR = 'data-depictio-stars';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** The view that holds the scrolling lanes (see `buildGenomeSpySpec`); a lane
 *  taller than its viewport is clipped to it. */
const LANES_VIEW = 'lanes';

export interface StarOverlayInput {
  api: EmbedResult | null;
  container: RefObject<HTMLElement | null>;
  /** The lanes that draw stars (`BuiltGenomeSpec.starLanes`); empty: no overlay. */
  lanes: readonly StarLane[];
  contigs: readonly Contig[] | null;
  /** Every row the embed shows, as `markTopStars` left them. */
  rows: readonly Record<string, unknown>[] | null;
  cols: { chr: string; pos: string; score: string; sample?: string | null };
  /** Gold, silver and bronze. */
  medals: readonly string[];
  /** The outline: the tile's text colour, so it reads on light and dark. */
  outline: string;
  pointSize: number;
}

function removeOverlay(el: HTMLElement | null): void {
  el?.querySelectorAll(`[${STAR_OVERLAY_ATTR}]`).forEach((n) => n.remove());
}

function boundsOf(api: EmbedResult, name: string): Bounds | undefined {
  try {
    return api.views.getLayoutBounds({ scope: [], view: name });
  } catch {
    return undefined;
  }
}

function domainOf(api: EmbedResult, scale: string): [number, number] | null {
  try {
    const d = api.getScaleResolutionByName(scale)?.getDomain();
    if (!d || d.length < 2) return null;
    const lo = Number(d[0]);
    const hi = Number(d[d.length - 1]);
    return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : null;
  } catch {
    return null;
  }
}

export function useStarOverlay({
  api,
  container,
  lanes,
  contigs,
  rows,
  cols,
  medals,
  outline,
  pointSize,
}: StarOverlayInput): void {
  // The latest rows, read at every redraw without re-subscribing.
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const redrawRef = useRef<(() => void) | null>(null);

  const colsKey = `${cols.chr}|${cols.pos}|${cols.score}|${cols.sample ?? ''}`;
  const lanesKey = lanes.map((l) => `${l.lane}:${l.scale}:${l.sample ?? ''}`).join(',');
  const medalsKey = medals.join(',');

  useEffect(() => {
    const el = container.current;
    removeOverlay(el);
    redrawRef.current = null;
    if (!el || !api || !lanes.length || !contigs?.length || medals.length < 3) return undefined;

    const offsets = contigOffsets(contigs);
    const radius = starRadius(pointSize);
    const doc = el.ownerDocument;

    const svg = doc.createElementNS(SVG_NS, 'svg');
    svg.setAttribute(STAR_OVERLAY_ATTR, '');
    svg.setAttribute('aria-hidden', 'true');
    Object.assign(svg.style, {
      position: 'absolute',
      left: '0',
      top: '0',
      width: '100%',
      height: '100%',
      overflow: 'hidden',
      pointerEvents: 'none',
    });
    const clipIds = lanes.map((_, i) => `depictio-star-clip-${Math.random().toString(36).slice(2, 8)}-${i}`);
    el.appendChild(svg);

    const redraw = () => {
      if (!isGenomeSpyLive(api)) return;
      const canvas = el.querySelector('canvas');
      if (!canvas) return;
      // Layout bounds are in the canvas' own coordinates. The SVG sits in the
      // canvas' wrapper and is offset by layout, not by screen boxes: GenomeSpy
      // fades the canvas in from scale(0.95), and an offset read mid-animation
      // stayed on every star.
      const wrapper = canvas.parentElement ?? el;
      if (svg.parentElement !== wrapper) wrapper.appendChild(svg);
      const dx = canvas.offsetParent === wrapper ? canvas.offsetLeft : 0;
      const dy = canvas.offsetParent === wrapper ? canvas.offsetTop : 0;
      const xDomain = domainOf(api, GENOME_SCALE_NAME);
      const viewport = boundsOf(api, LANES_VIEW);
      const parts: string[] = [];
      lanes.forEach((lane, i) => {
        const own = boundsOf(api, lane.lane);
        const yDomain = domainOf(api, lane.scale);
        if (!own || !xDomain || !yDomain) return;
        // Stars are placed against the lane's own box and clipped to the part
        // of it a scrolling viewport shows.
        const visible = viewport ? intersectBounds(own, viewport) : own;
        if (!visible) return;
        const placed = placeStars({
          rows: starRowsOf(rowsRef.current, cols, lane.sample),
          offsets,
          bounds: own,
          xDomain,
          yDomain,
          reach: radius,
        });
        if (!placed.length) return;
        const clip =
          `<clipPath id="${clipIds[i]}"><rect x="${visible.x + dx}" y="${visible.y + dy}" ` +
          `width="${visible.width}" height="${visible.height}"/></clipPath>`;
        const stars = placed
          .map(
            (s) =>
              `<path d="${starPath(s.x + dx, s.y + dy, radius)}" fill="${medals[Math.min(2, s.medal - 1)]}" ` +
              `stroke="${outline}" stroke-width="1" stroke-linejoin="round" data-medal="${s.medal}" ` +
              `data-x="${Math.round((s.x + dx) * 100) / 100}" data-y="${Math.round((s.y + dy) * 100) / 100}"/>`,
          )
          .join('');
        parts.push(`${clip}<g clip-path="url(#${clipIds[i]})">${stars}</g>`);
      });
      svg.innerHTML = parts.join('');
    };
    redrawRef.current = redraw;

    const unsubscribes: Array<() => void> = [];
    const listen = (name: string) => {
      try {
        const res = api.getScaleResolutionByName(name);
        if (!res) return;
        res.addEventListener('domain', redraw);
        unsubscribes.push(() => res.removeEventListener('domain', redraw));
      } catch {
        // No such scale in this build: the layout listener still redraws.
      }
    };
    listen(GENOME_SCALE_NAME);
    for (const scale of new Set(lanes.map((l) => l.scale))) listen(scale);
    try {
      unsubscribes.push(api.views.subscribeToLayout(redraw));
    } catch {
      // Older build: domain events and the resize observer carry on.
    }
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(redraw);
      observer.observe(el);
    }
    redraw();

    return () => {
      for (const off of unsubscribes) off();
      observer?.disconnect();
      redrawRef.current = null;
      svg.remove();
    };
    // `lanes`, `cols` and `medals` are keyed by value: a fresh array with the
    // same content must not rebuild the overlay.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, container, lanesKey, contigs, colsKey, medalsKey, outline, pointSize]);

  // New rows (a filter moved): redraw in place, no rebuild.
  useEffect(() => {
    redrawRef.current?.();
  }, [rows]);
}
