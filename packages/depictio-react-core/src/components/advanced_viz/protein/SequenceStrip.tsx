import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { stableColorMap } from '../../../colors';
import { contrastingText, sampleColorscale } from '../../../utils/colorScale';
import {
  fitCellWidth,
  fitText,
  lettersFit,
  prepareCanvas,
  roundRectPath,
  rulerStep,
  scrollToReveal,
  visibleWindow,
} from './canvas';
import { useDrawScheduler, useViewSize } from './canvasHooks';
import { cssToRgb, panelColours, type PanelColours } from './panelTheme';
import { plddtBand, plddtIsFractional, rgbCss, type SecondaryStructure } from './residueColours';
import {
  isPlddtLabel,
  looksLikeSecondaryStructure,
  normaliseResidues,
  runsOf,
  secondaryStructureOf,
  stackVariants,
  stripSpan,
  valueExtent,
  type Run,
} from './sequence';
import { SEQUENCE_RESIDUE_WIDTH_MAX_PX } from './chainStrips';
import { drawCoil, drawSecondaryStructureRuns } from './ssGlyphs';
import { layoutLanes, type LaneKey, type LanePresence, type PlacedLane } from './stripLanes';
import type { SequenceStripProps, StripDomain, StripHover, StripResidue } from './types';
import { useModifierWheelZoom } from './useWheelZoom';

const LABEL_PX = 72;
const DRAG_PX = 3;
const HEAD_R = 3.5;

/** A placed lane (`stripLanes.ts`) with the title drawn in the label column. */
interface Lane extends PlacedLane {
  title: string;
}

/** Baseline of the variants lane. */
function variantBaseY(lane: Lane): number {
  return lane.y + lane.h - 1.5;
}

/** Height of the head of a stack of `n` variants, the tallest stack filling the lane. */
function variantHeadY(lane: Lane, n: number, maxStack: number): number {
  const room = lane.h - HEAD_R * 2 - 4;
  return variantBaseY(lane) - 4 - (room * n) / maxStack;
}

/** The value a residue's category run groups on: its secondary-structure class
 *  on a structure lane, else the category itself. */
function categoryKey(r: StripResidue, isSS: boolean): string | null {
  if (isSS) return secondaryStructureOf(r.category);
  return r.category != null && r.category !== '' ? String(r.category) : null;
}

/**
 * One protein's linear sequence with its per-residue lanes, on one 2D canvas:
 * a ruler, the one-letter sequence (blocks when too dense to read), a value
 * lane (AlphaFold confidence bands when it is pLDDT, else a colour scale), a
 * category lane (secondary structure glyphs when it looks like DSSP / S4PRED
 * classes, else categorical blocks), domain spans and variant lollipops.
 * Horizontally virtualised and zoomable through `cellWidth`; a brush reports a
 * residue range, a click one residue. Controlled like `MsaPanel`.
 */
const SequenceStrip: React.FC<SequenceStripProps> = ({
  residues: rawResidues,
  domains = [],
  variants = [],
  valueLabel,
  valueScale,
  categoryColours,
  selectedRange,
  highlight,
  onHover,
  onBrush,
  onClickVariant,
  height,
  cellWidth,
  onCellWidthChange,
  scrollSync,
  showLetters = true,
  followSelection = true,
  onDrawn,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const colours: PanelColours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const view = useViewSize(scrollRef);

  // ---- data ------------------------------------------------------------------
  const residues = useMemo(() => normaliseResidues(rawResidues), [rawResidues]);
  const byPosition = useMemo(() => {
    const m = new Map<number, StripResidue>();
    for (const r of residues) m.set(r.position, r);
    return m;
  }, [residues]);
  const span = useMemo(() => stripSpan(residues, domains, variants), [residues, domains, variants]);
  const hasLetters = showLetters && residues.some((r) => r.letter);
  const extent = useMemo(() => valueExtent(residues), [residues]);
  const plddt = isPlddtLabel(valueLabel) || valueScale === 'plddt';
  const fractional = useMemo(
    () => plddt && plddtIsFractional(residues.map((r) => r.value)),
    [plddt, residues],
  );
  const categories = useMemo(() => residues.map((r) => r.category), [residues]);
  const hasCategory = categories.some((c) => c != null && c !== '');
  const isSS = useMemo(
    () => hasCategory && looksLikeSecondaryStructure(categories),
    [hasCategory, categories],
  );
  const categoryRuns = useMemo(
    () => (hasCategory ? runsOf(residues, (r) => categoryKey(r, isSS)) : []),
    [hasCategory, isSS, residues],
  );
  const stacks = useMemo(() => stackVariants(variants), [variants]);
  const maxStack = useMemo(() => stacks.reduce((m, s) => Math.max(m, s.variants.length), 1), [stacks]);

  // One stable map for every categorical value the strip draws, so the same
  // consequence reads the same colour on the category lane and on the heads.
  const catMap = useMemo(() => {
    const universe = new Set<string>();
    if (!isSS) for (const c of categories) if (c != null && c !== '') universe.add(String(c));
    for (const v of variants) if (v.category) universe.add(String(v.category));
    for (const d of domains) if (d.label) universe.add(String(d.label));
    return stableColorMap(Array.from(universe), colours.categorical, categoryColours ?? null);
  }, [isSS, categories, variants, domains, colours.categorical, categoryColours]);

  // ---- lanes -----------------------------------------------------------------
  // The lanes share the height the cell gives them, each up to its cap, and
  // what they cannot take centres the stack (see `stripLanes.ts`). The offset
  // is part of every lane's `y`, so drawing and hit-testing agree.
  const present = useMemo<LanePresence>(
    () => ({
      letters: hasLetters,
      category: hasCategory,
      value: extent !== null,
      domains: domains.length > 0,
      variants: stacks.length > 0,
    }),
    [hasLetters, hasCategory, extent, domains.length, stacks.length],
  );
  const layout = useMemo(() => layoutLanes(present, view.h), [present, view.h]);
  const lanes = useMemo<Lane[]>(() => {
    const titles: Record<LaneKey, string> = {
      ruler: 'Residue',
      letters: 'Sequence',
      category: isSS ? 'Structure' : 'Category',
      value: valueLabel || 'Value',
      domains: 'Domains',
      variants: 'Variants',
    };
    return layout.lanes.map((l) => ({ ...l, title: titles[l.key] }));
  }, [layout, isSS, valueLabel]);
  const naturalH = layout.naturalH;

  const minPos = span?.min ?? 1;
  const count = span ? span.max - span.min + 1 : 0;
  const gridW = Math.max(0, view.w - LABEL_PX);
  const cw = cellWidth && cellWidth > 0 ? cellWidth : fitCellWidth(gridW, count, 0.05, 24);
  const contentW = LABEL_PX + count * cw;
  useModifierWheelZoom(scrollRef, {
    value: cw,
    setValue: onCellWidthChange,
    min: 1,
    max: SEQUENCE_RESIDUE_WIDTH_MAX_PX,
    gutter: LABEL_PX,
  });
  // The chains of a complex scroll together.
  useEffect(() => {
    const el = scrollRef.current;
    return el && scrollSync ? scrollSync.register(el) : undefined;
  }, [scrollSync]);

  const brushRef = useRef<{
    start: number;
    end: number;
    x: number;
    moved: boolean;
    inGrid: boolean;
  } | null>(null);
  const hoverRef = useRef<{ position: number | null; x: number; y: number } | null>(null);
  const [tooltip, setTooltip] = useState<{ position: number; x: number; y: number } | null>(null);
  const drawnRef = useRef(false);
  // A new sequence is a new first frame: report it again once drawn.
  useEffect(() => {
    drawnRef.current = false;
  }, [rawResidues]);

  const valueColour = useCallback(
    (v: number): string => {
      if (plddt) return rgbCss(plddtBand(v, fractional).rgb);
      const [lo, hi] = extent ?? [0, 1];
      const t = hi > lo ? (v - lo) / (hi - lo) : 1;
      return rgbCss(sampleColorscale(valueScale && valueScale !== 'plddt' ? valueScale : 'Viridis', t));
    },
    [plddt, fractional, extent, valueScale],
  );
  const valueHeight = useCallback(
    (v: number): number => {
      if (plddt) return Math.max(0, Math.min(1, fractional ? v : v / 100));
      const [lo, hi] = extent ?? [0, 1];
      const base = Math.min(0, lo);
      return hi > base ? (v - base) / (hi - base) : 1;
    },
    [plddt, fractional, extent],
  );

  // ---- drawing ---------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const el = scrollRef.current;
    if (!canvas || !el || view.w <= 0 || view.h <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, view.h);
    if (!ctx || !span) return;
    const sx = el.scrollLeft;
    const [i0, i1] = visibleWindow(sx, gridW, cw, count, 2);
    const p0 = minPos + i0;
    const p1 = minPos + i1;
    const xOf = (pos: number) => LABEL_PX + (pos - minPos) * cw - sx;
    const lane = (key: LaneKey) => lanes.find((l) => l.key === key);
    // The bands span the drawn stack, not the cell: a centred stack leaves
    // room above and below it.
    const bandTop = layout.top;
    const bandH = Math.max(0, Math.min(layout.stackH, view.h - bandTop));
    const brush = brushRef.current;
    const hover = hoverRef.current;

    ctx.save();
    ctx.beginPath();
    ctx.rect(LABEL_PX, 0, gridW, view.h);
    ctx.clip();

    // Background bands: selection, incoming highlight, live brush, hover.
    const band = (a: number, b: number, fill: string) => {
      ctx.fillStyle = fill;
      ctx.fillRect(xOf(Math.min(a, b)), bandTop, (Math.abs(b - a) + 1) * cw, bandH);
    };
    if (selectedRange) band(selectedRange.start, selectedRange.end ?? selectedRange.start, colours.accentFill);
    if (highlight) band(highlight.start, highlight.end ?? highlight.start, colours.highlightFill);
    if (brush && brush.moved) band(brush.start, brush.end, colours.accentFill);
    if (hover && hover.position != null && !brush) band(hover.position, hover.position, colours.hoverFill);

    // Ruler.
    const ruler = lane('ruler');
    if (ruler) {
      const step = rulerStep(cw);
      ctx.strokeStyle = colours.dimmed;
      ctx.fillStyle = colours.dimmed;
      ctx.lineWidth = 1;
      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      const first = Math.ceil(p0 / step) * step;
      const tick = (pos: number) => {
        const x = Math.round(xOf(pos) + cw / 2) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, ruler.y + ruler.h - 5);
        ctx.lineTo(x, ruler.y + ruler.h);
        ctx.stroke();
        ctx.fillText(String(pos), x, ruler.y + ruler.h - 7);
      };
      if (p0 <= 1 && 1 <= p1 && step > 1) tick(1);
      for (let pos = Math.max(first, step); pos <= p1; pos += step) tick(pos);
      ctx.strokeStyle = colours.grid;
      ctx.beginPath();
      ctx.moveTo(xOf(minPos), ruler.y + ruler.h - 0.5);
      ctx.lineTo(xOf(minPos + count), ruler.y + ruler.h - 0.5);
      ctx.stroke();
    }

    // Letters, or density blocks when the cells are too narrow to read.
    const letters = lane('letters');
    if (letters) {
      const readable = lettersFit(cw, letters.h);
      ctx.font = `${Math.max(7, Math.min(12, cw, letters.h - 2))}px ${colours.monoFont}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const neutral = rgbCss(colours.neutral, 0.6);
      for (let pos = p0; pos <= p1; pos++) {
        const r = byPosition.get(pos);
        if (!r?.letter) continue;
        if (readable) {
          ctx.fillStyle = colours.text;
          ctx.fillText(String(r.letter), xOf(pos) + cw / 2, letters.y + letters.h / 2 + 0.5);
        } else {
          ctx.fillStyle = neutral;
          ctx.fillRect(xOf(pos), letters.y + 3, Math.max(cw, 0.5), letters.h - 6);
        }
      }
    }

    // Category: secondary-structure glyphs or categorical blocks.
    const cat = lane('category');
    if (cat) {
      const mid = cat.y + cat.h / 2;
      if (isSS) {
        const baseline: [number, number] = [
          xOf(Math.max(minPos, p0)),
          xOf(Math.min(minPos + count, p1 + 1)),
        ];
        drawCoil(ctx, baseline[0], baseline[1], mid, colours.dimmed);
        drawSecondaryStructureRuns(ctx, categoryRuns as Run<SecondaryStructure>[], {
          xOf,
          cellWidth: cw,
          yMid: mid,
          height: cat.h,
          visible: [p0, p1],
        });
      } else {
        for (const run of categoryRuns) {
          if (run.end < p0 || run.start > p1) continue;
          const x = xOf(run.start);
          const w = (run.end - run.start + 1) * cw;
          ctx.fillStyle = catMap.get(String(run.value));
          ctx.fillRect(x, cat.y + 1, Math.max(w, 0.5), cat.h - 2);
        }
      }
    }

    // Value lane: bars coloured by band / scale.
    const val = lane('value');
    if (val) {
      ctx.strokeStyle = colours.grid;
      ctx.beginPath();
      ctx.moveTo(xOf(minPos), val.y + val.h - 0.5);
      ctx.lineTo(xOf(minPos + count), val.y + val.h - 0.5);
      ctx.stroke();
      for (let pos = p0; pos <= p1; pos++) {
        const v = byPosition.get(pos)?.value;
        if (v == null || !Number.isFinite(v)) continue;
        const h = Math.max(1, valueHeight(v) * (val.h - 1));
        ctx.fillStyle = valueColour(v);
        ctx.fillRect(xOf(pos), val.y + val.h - h, Math.max(cw - (cw > 4 ? 0.5 : 0), 0.5), h);
      }
    }

    // Domain spans.
    const dom = lane('domains');
    if (dom) {
      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const d of domains) {
        if (d.end < p0 || d.start > p1) continue;
        const x = xOf(d.start);
        const w = (d.end - d.start + 1) * cw;
        const fill = catMap.get(String(d.label ?? ''));
        ctx.fillStyle = fill;
        roundRectPath(ctx, x, dom.y + 1, w, dom.h - 2, 3);
        ctx.fill();
        const label = d.label ? fitText(ctx, String(d.label), w - 6) : '';
        if (label) {
          ctx.fillStyle = contrastingText(cssToRgb(fill));
          const visX0 = Math.max(x, LABEL_PX);
          const visX1 = Math.min(x + w, view.w);
          ctx.fillText(label, (visX0 + visX1) / 2, dom.y + dom.h / 2 + 0.5);
        }
      }
    }

    // Variant lollipops, stacked per position.
    const vl = lane('variants');
    if (vl) {
      const base = variantBaseY(vl);
      ctx.strokeStyle = colours.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xOf(minPos), base + 0.5);
      ctx.lineTo(xOf(minPos + count), base + 0.5);
      ctx.stroke();
      for (const s of stacks) {
        if (s.position < p0 || s.position > p1) continue;
        const x = xOf(s.position) + cw / 2;
        const top = variantHeadY(vl, s.variants.length, maxStack);
        const counts = new Map<string, number>();
        for (const v of s.variants) {
          const k = String(v.category ?? '');
          counts.set(k, (counts.get(k) ?? 0) + 1);
        }
        const lead = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '';
        const fill = lead ? catMap.get(lead) : colours.text;
        ctx.strokeStyle = colours.dimmed;
        ctx.beginPath();
        ctx.moveTo(x, base);
        ctx.lineTo(x, top);
        ctx.stroke();
        ctx.fillStyle = fill;
        ctx.beginPath();
        ctx.arc(x, top, HEAD_R, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Edges of the selection and the highlight, over the lanes.
    const edges = (a: number, b: number, stroke: string) => {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(xOf(Math.min(a, b)), bandTop + 0.75, (Math.abs(b - a) + 1) * cw, bandH - 1.5);
    };
    if (selectedRange) edges(selectedRange.start, selectedRange.end ?? selectedRange.start, colours.accent);
    if (highlight) edges(highlight.start, highlight.end ?? highlight.start, colours.highlight);
    ctx.restore();

    // Lane titles.
    ctx.font = `10px ${colours.font}`;
    ctx.fillStyle = colours.dimmed;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (const l of lanes) {
      if (l.key === 'ruler') continue;
      ctx.fillText(fitText(ctx, l.title, LABEL_PX - 8), 4, l.y + l.h / 2);
    }
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(LABEL_PX - 0.5, bandTop);
    ctx.lineTo(LABEL_PX - 0.5, bandTop + bandH);
    ctx.stroke();

    if (!drawnRef.current && (residues.length > 0 || variants.length > 0 || domains.length > 0)) {
      drawnRef.current = true;
      onDrawn?.();
    }
  }, [
    view,
    span,
    gridW,
    cw,
    count,
    minPos,
    lanes,
    layout,
    colours,
    selectedRange,
    highlight,
    byPosition,
    isSS,
    categoryRuns,
    catMap,
    valueColour,
    valueHeight,
    domains,
    stacks,
    maxStack,
    residues.length,
    variants.length,
    onDrawn,
  ]);

  const requestDraw = useDrawScheduler(draw);

  // ---- follow ------------------------------------------------------------------
  const follow = highlight ?? selectedRange ?? null;
  const followStart = follow ? Math.min(follow.start, follow.end ?? follow.start) : null;
  const followEnd = follow ? Math.max(follow.start, follow.end ?? follow.start) : null;
  useEffect(() => {
    const el = scrollRef.current;
    if (!followSelection || !el || followStart == null || followEnd == null || gridW <= 0) return;
    const next = scrollToReveal(
      el.scrollLeft,
      gridW,
      (followStart - minPos) * cw,
      (followEnd - minPos + 1) * cw,
    );
    if (next != null) el.scrollLeft = next;
  }, [followSelection, followStart, followEnd, minPos, cw, gridW]);

  // ---- pointer -------------------------------------------------------------------
  const pointAt = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const x = rect ? e.clientX - rect.left : 0;
      const y = rect ? e.clientY - rect.top : 0;
      const sx = scrollRef.current?.scrollLeft ?? 0;
      const inGrid = x >= LABEL_PX && count > 0;
      const raw = minPos + Math.floor((x - LABEL_PX + sx) / cw);
      const position = inGrid ? Math.max(minPos, Math.min(minPos + count - 1, raw)) : null;
      return { x, y, position, inGrid };
    },
    [count, minPos, cw],
  );

  const variantHit = useCallback(
    (x: number, y: number) => {
      const vl = lanes.find((l) => l.key === 'variants');
      if (!vl || y < vl.y || y > vl.y + vl.h) return null;
      const sx = scrollRef.current?.scrollLeft ?? 0;
      let best: { d: number; stack: (typeof stacks)[number] } | null = null;
      for (const s of stacks) {
        const hx = LABEL_PX + (s.position - minPos) * cw - sx + cw / 2;
        const hy = variantHeadY(vl, s.variants.length, maxStack);
        const d = Math.hypot(hx - x, hy - y);
        if (d <= HEAD_R + 3 && (!best || d < best.d)) best = { d, stack: s };
      }
      return best?.stack ?? null;
    },
    [lanes, stacks, minPos, cw, maxStack],
  );

  const hoverOf = useCallback(
    (position: number): StripHover => ({
      position,
      residue: byPosition.get(position) ?? null,
      domains: domains.filter((d: StripDomain) => d.start <= position && position <= d.end),
      variants: variants.filter((v) => Number(v.position) === position),
    }),
    [byPosition, domains, variants],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const p = pointAt(e);
    brushRef.current = {
      start: p.position ?? minPos,
      end: p.position ?? minPos,
      x: p.x,
      moved: false,
      inGrid: p.inGrid,
    };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const p = pointAt(e);
    const brush = brushRef.current;
    if (brush && brush.inGrid && onBrush) {
      if (!brush.moved && Math.abs(p.x - brush.x) > DRAG_PX) brush.moved = true;
      if (brush.moved) {
        const sx = scrollRef.current?.scrollLeft ?? 0;
        const raw = minPos + Math.floor((p.x - LABEL_PX + sx) / cw);
        brush.end = Math.max(minPos, Math.min(minPos + count - 1, raw));
        requestDraw();
        return;
      }
    }
    hoverRef.current = { position: p.position, x: p.x, y: p.y };
    setTooltip(p.position != null ? { position: p.position, x: p.x, y: p.y } : null);
    onHover?.(p.position != null ? hoverOf(p.position) : null);
    requestDraw();
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const brush = brushRef.current;
    brushRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!brush) return;
    const p = pointAt(e);
    if (brush.moved && onBrush) {
      onBrush({ start: Math.min(brush.start, brush.end), end: Math.max(brush.start, brush.end) });
    } else if (!brush.inGrid) {
      if (onBrush && selectedRange) onBrush(null);
    } else {
      const stack = variantHit(p.x, p.y);
      if (stack && onClickVariant) {
        onClickVariant(stack.variants[0]);
      } else if (onBrush && p.position != null) {
        const same =
          selectedRange &&
          selectedRange.start === p.position &&
          (selectedRange.end ?? selectedRange.start) === p.position;
        onBrush(same ? null : { start: p.position, end: p.position });
      }
    }
    requestDraw();
  };

  const onPointerLeave = () => {
    if (brushRef.current) return;
    hoverRef.current = null;
    setTooltip(null);
    onHover?.(null);
    requestDraw();
  };

  const tip = useMemo(() => {
    if (!tooltip) return null;
    const h = hoverOf(tooltip.position);
    const lines: string[] = [];
    const r = h.residue;
    lines.push(`${r?.letter ? `${r.letter} ` : ''}${h.position}`);
    if (r?.value != null && Number.isFinite(r.value)) {
      const band = plddt ? ` (${plddtBand(r.value, fractional).label.split(' (')[0].toLowerCase()})` : '';
      lines.push(`${valueLabel || 'Value'} ${Number(r.value.toFixed(3))}${band}`);
    }
    if (r?.category) {
      const ss = isSS ? secondaryStructureOf(r.category) : null;
      lines.push(ss ? `Structure: ${ss}` : String(r.category));
    }
    for (const d of h.domains.slice(0, 3)) {
      lines.push(`${d.label ?? 'Domain'} ${d.start}-${d.end}${d.source ? ` (${d.source})` : ''}`);
    }
    for (const v of h.variants.slice(0, 5)) {
      lines.push([v.label, v.category].filter(Boolean).join(', ') || 'Variant');
    }
    if (h.variants.length > 5) lines.push(`and ${h.variants.length - 5} more variants`);
    return lines;
  }, [tooltip, hoverOf, plddt, fractional, valueLabel, isSS]);

  const cssHeight = height ?? naturalH;

  return (
    <Box
      className="depictio-sequence-strip"
      pos="relative"
      style={{ width: '100%', height: cssHeight, minHeight: Math.min(naturalH, 60) }}
    >
      <div
        ref={scrollRef}
        onScroll={(e) => {
          scrollSync?.follow(e.currentTarget);
          requestDraw();
        }}
        style={{ position: 'absolute', inset: 0, overflowX: 'auto', overflowY: 'hidden' }}
      >
        <div style={{ position: 'relative', width: contentW, height: '100%', minWidth: '100%' }}>
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Sequence track, ${count} residues`}
            style={{
              position: 'sticky',
              left: 0,
              top: 0,
              display: 'block',
              cursor: onBrush ? 'crosshair' : 'default',
              touchAction: 'none',
            }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerLeave}
          />
        </div>
      </div>
      {tip && tooltip ? (
        <Paper
          withBorder
          shadow="sm"
          p={6}
          style={{
            position: 'absolute',
            pointerEvents: 'none',
            zIndex: 2,
            left: Math.min(tooltip.x + 14, Math.max(0, view.w - 220)),
            top: Math.min(tooltip.y + 14, Math.max(0, view.h - 60)),
            maxWidth: 260,
          }}
        >
          {tip.map((line, i) => (
            <Text key={i} size="xs" fw={i === 0 ? 600 : 400} lineClamp={1}>
              {line}
            </Text>
          ))}
        </Paper>
      ) : null}
    </Box>
  );
};

export default SequenceStrip;
