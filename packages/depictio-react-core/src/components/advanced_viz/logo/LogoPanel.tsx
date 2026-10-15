import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from '@iconify/react';
import { ActionIcon, alpha, Box, Paper, Text, Tooltip, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { useFullscreenPortalTarget } from '../../chrome/useFullscreenPortalTarget';

import { fitCellWidth, prepareCanvas, rulerStep, scrollToReveal } from '../protein/canvas';
import { useDrawScheduler, useViewSize } from '../protein/canvasHooks';
import { useModifierWheelZoom } from '../protein/useWheelZoom';
import { rgbCss } from '../protein/residueColours';
import type { MsaColourScheme, ProteinHighlight, ResidueRange } from '../protein/types';
import {
  columnsInView,
  extentAtX,
  indexAtX,
  placeColumns,
  planColumns,
  spanOfIndices,
  STUB_PX,
  visibleSegments,
  type HiddenRange,
  type StubSegment,
} from './collapse';
import { atlasCellPx, atlasKey, GlyphAtlas, glyphAtlasFor } from './glyphAtlas';
import { columnHeights, logoHeights, type HeightMode } from './heights';
import {
  drawnHitCount,
  evalueScale,
  formatEvalue,
  hitAt,
  HITS_LABEL_SEPARATOR,
  hitsLaneLabel,
  packHits,
  partialEdges,
  type LogoHit,
} from './hitsModel';
import {
  hitBarTop,
  hitRowAt,
  insertLengthShare,
  laneAt,
  layoutLanes,
  LOGO_TOP_PAD,
  logoAxis,
  rampColour,
  type Lane,
} from './layout';
import { logoColours } from './logoTheme';
import { TRACK_LABELS, type TrackKey } from './tracks';
import {
  letterColours,
  residueRangeOfStates,
  stateColumnLookup,
  stateSpanOfRange,
  topLetters,
  type LogoProfile,
} from './profileModel';

/** Left gutter: lane labels and the logo's y axis. */
const GUTTER_PX = 76;
/** Width kept free at the right of the gutter for a track's collapse button. */
const TRACK_BUTTON_PX = 14;
/** Below this many px per state, letters become stacked colour bars. */
export const DENSITY_PX = 6;
const MAX_FIT_PX = 40;
/** Pointer travel that turns a press into a brush rather than a click. */
const DRAG_PX = 3;
/** Px per state from which lane values are written as numbers. */
const NUMBERS_PX = 24;

export interface LogoHover {
  /** State index under the pointer (null over the gutter). */
  index: number | null;
  /** Hit bar under the pointer. */
  hit: LogoHit | null;
}

export interface LogoPanelProps {
  profile: LogoProfile;
  heightMode: HeightMode;
  colourScheme: MsaColourScheme;
  showConsensus: boolean;
  showIndelRows: boolean;
  /** Occupancy bars, or their complement, the delete probability. */
  occupancyMode: 'occupancy' | 'delete';
  /** Hit bars to draw (best first); null without a hits companion. */
  hits: LogoHit[] | null;
  /** Coverage depth per match state (`depth[k - 1]`), over `coverageCount` hits. */
  coverage: Int32Array | null;
  coverageCount: number;
  /** The model's length, for the partial-hit edges of hits without `hmm_length`. */
  modelLength: number;
  /** Protein whose hits are ringed (a pick on the hits' entity column). */
  selectedHitEntity: string | null;
  /** The hit whose aligned residues are the current pick. */
  selectedHitKey: string | null;
  /** Protein pointed at elsewhere: its hits are outlined. */
  highlightHitEntity: string | null;
  /** Reference residues to shade (the profile's own entity). */
  selectedRange: ResidueRange | null;
  /** Hover from another tile, in reference residues. */
  highlight: ProteinHighlight | null;
  onHover?: (hover: LogoHover | null) => void;
  /** A brush over state indices `a..b` (a click is `a === b`). Omit to disable picks. */
  onPickStates?: (a: number, b: number) => void;
  onClear?: () => void;
  onClickHit?: (hit: LogoHit) => void;
  /** Px per state; 0 or undefined fits the model to the width. */
  cellWidth?: number;
  /** Ctrl / Cmd + wheel asks for this many px per state (whole pixels). */
  onCellWidthChange?: (px: number) => void;
  followSelection?: boolean;
  onDrawn?: () => void;
  /** Draw only the states numbered `windowStart..windowEnd` (1-based); null is open. */
  windowStart?: number | null;
  windowEnd?: number | null;
  /** Fold runs of at least `collapseMinRun` states whose information is under this many bits. */
  collapseBelowIc?: number | null;
  collapseMinRun?: number;
  /** State index ranges hidden by hand, and the auto runs the user opened. */
  hidden?: readonly HiddenRange[];
  expanded?: readonly string[];
  /** A click on a stub. */
  onExpandStub?: (stub: StubSegment) => void;
  /** Tracks left out of the panel, and tracks reduced to a thin strip. */
  hiddenTracks?: readonly TrackKey[];
  collapsedTracks?: readonly TrackKey[];
  /** Toggle one track between expanded and collapsed; omit for no header buttons. */
  onToggleTrack?: (track: TrackKey) => void;
}

interface BrushState {
  /** Column under the press (-1 outside the grid or over a stub). */
  startCol: number;
  /** Where the press and the pointer are, px from the first drawn column. */
  startGx: number;
  endGx: number;
  stub: StubSegment | null;
  x: number;
  y: number;
  moved: boolean;
  hit: LogoHit | null;
  inGrid: boolean;
}

interface PointerAt {
  col: number | null;
  stub: StubSegment | null;
  lane: Lane | null;
  hit: LogoHit | null;
  x: number;
  y: number;
  /** Pointer x in px from the first drawn column. */
  gx: number;
  /** Over a drawn column or a stub (not the gutter or past the last column). */
  over: boolean;
}

const fmt = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '-' : v.toFixed(digits);

/**
 * An HMM logo on one DPR-aware 2D canvas: stacked letters (glyph atlas,
 * stacked colour bars below `DENSITY_PX`), consensus / RF / CS rows, insert
 * probability and length strips, occupancy bars, a hit coverage area with
 * packed hit bars, and a ruler in HMM states and reference residues.
 * Virtualised to the visible states; the browser's horizontal scrollbar
 * drives it (a sticky canvas in a scroll spacer, like `MsaPanel`).
 * Controlled: the caller resolves selections and the hover bus.
 */
const LogoPanel: React.FC<LogoPanelProps> = ({
  profile,
  heightMode,
  colourScheme,
  showConsensus,
  showIndelRows,
  occupancyMode,
  hits,
  coverage,
  coverageCount,
  modelLength,
  selectedHitEntity,
  selectedHitKey,
  highlightHitEntity,
  selectedRange,
  highlight,
  onHover,
  onPickStates,
  onClear,
  onClickHit,
  cellWidth,
  onCellWidthChange,
  followSelection = true,
  onDrawn,
  windowStart = null,
  windowEnd = null,
  collapseBelowIc = null,
  collapseMinRun = 4,
  hidden,
  expanded,
  onExpandStub,
  hiddenTracks,
  collapsedTracks,
  onToggleTrack,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const colours = useMemo(() => logoColours(theme, isDark), [theme, isDark]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const view = useViewSize(scrollRef);
  const fsPortalTarget = useFullscreenPortalTarget();

  // ---- derived model -------------------------------------------------------
  const k = profile.letters.length;
  const m = profile.states.length;
  const heights = useMemo(
    () => logoHeights(profile.emissions, k, profile.background, heightMode),
    [profile, k, heightMode],
  );
  // The tooltip always reports the relative entropy, whatever the mode draws.
  const information = useMemo(
    () =>
      Float64Array.from({ length: m }, (_, i) =>
        columnHeights(profile.emissions.subarray(i * k, (i + 1) * k), profile.background, 'relent_all').info,
      ),
    [profile, k, m],
  );
  const colourOf = useMemo(() => {
    const rgb = letterColours(profile, colourScheme);
    const fallback = colourScheme === 'none' ? colours.text : colours.dimmed;
    return rgb.map((c) => (c ? rgbCss(c) : fallback));
  }, [profile, colourScheme, colours.text, colours.dimmed]);
  const axis = useMemo(() => logoAxis(heights.maxInfo, heightMode), [heights.maxInfo, heightMode]);
  const colOfState = useMemo(() => stateColumnLookup(profile.states), [profile.states]);
  const hasPositions = useMemo(() => profile.positions.some((p) => p != null), [profile.positions]);
  const packing = useMemo(() => (hits && hits.length ? packHits(hits) : null), [hits]);
  const evalueT = useMemo(() => evalueScale(hits ?? []), [hits]);
  const maxDepth = useMemo(() => (coverage ? coverage.reduce((a, b) => Math.max(a, b), 0) : 0), [coverage]);
  const maxInsertLength = useMemo(
    () => (profile.insertLength ?? []).reduce<number>((a, b) => Math.max(a, b ?? 0), 1),
    [profile.insertLength],
  );

  // ---- geometry ------------------------------------------------------------
  const layout = useMemo(
    () =>
      layoutLanes(view.h, {
        consensus: showConsensus && profile.consensus != null,
        rf: showConsensus && profile.rf != null,
        cs: showConsensus && profile.cs != null,
        insertProb: showIndelRows && profile.insertProb != null,
        insertLength: showIndelRows && profile.insertLength != null,
        occupancy: showIndelRows && profile.occupancy != null,
        hits: hits != null,
        hitRows: packing?.rows ?? 0,
        hiddenTracks,
        collapsedTracks,
      }),
    [view.h, showConsensus, showIndelRows, profile, hits, packing, hiddenTracks, collapsedTracks],
  );
  // Hits the bars show, for the lane label: rows past the budget are summarised.
  const hitsDrawn = useMemo(
    () => drawnHitCount(packing, layout.hitRowsShown),
    [packing, layout.hitRowsShown],
  );
  const gridW = Math.max(0, view.w - GUTTER_PX);
  // Which columns are drawn (window, folded runs, hidden ranges); the state
  // width fits what is left once the stubs have their fixed width.
  const plan = useMemo(
    () =>
      planColumns({
        states: profile.states,
        windowStart,
        windowEnd,
        information,
        belowIc: collapseBelowIc,
        minRun: collapseMinRun,
        hidden,
        expanded,
      }),
    [profile.states, windowStart, windowEnd, information, collapseBelowIc, collapseMinRun, hidden, expanded],
  );
  const cw =
    cellWidth && cellWidth > 0
      ? cellWidth
      : fitCellWidth(Math.max(0, gridW - plan.stubs * STUB_PX), plan.shown, 1, MAX_FIT_PX);
  const columns = useMemo(() => placeColumns(plan, cw), [plan, cw]);
  const contentW = GUTTER_PX + columns.width;
  useModifierWheelZoom(scrollRef, {
    value: cw,
    setValue: onCellWidthChange,
    min: 1,
    max: 40,
    gutter: GUTTER_PX,
  });

  const selectedSpan = useMemo(() => stateSpanOfRange(profile.positions, selectedRange), [profile.positions, selectedRange]);
  const highlightSpan = useMemo(() => stateSpanOfRange(profile.positions, highlight), [profile.positions, highlight]);

  // ---- interaction state (refs: a pointer move redraws, it does not re-render)
  const brushRef = useRef<BrushState | null>(null);
  const hoverRef = useRef<PointerAt | null>(null);
  const [tooltip, setTooltip] = useState<PointerAt | null>(null);
  const drawnRef = useRef(false);
  useEffect(() => {
    drawnRef.current = false;
  }, [profile]);

  // ---- drawing ---------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const el = scrollRef.current;
    if (!canvas || !el || view.w <= 0 || view.h <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, view.h);
    if (!ctx) return;
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
    const atlas = glyphAtlasFor(atlasKey(colours.font, dpr, isDark ? 'dark' : 'light'), () =>
      new GlyphAtlas({ fontFamily: colours.font, cellPx: atlasCellPx(dpr) }),
    );
    const sx = el.scrollLeft;
    const segs = visibleSegments(columns, sx, gridW);
    const stubs = segs.filter((sg): sg is StubSegment => sg.kind === 'stub');
    // Every drawn column in the viewport, left to right, with its left edge.
    const eachColumn = (fn: (i: number, x: number, firstOfRun: boolean) => void) => {
      for (const sg of segs) {
        if (sg.kind !== 'states') continue;
        const [a, b] = columnsInView(columns, sg, sx, gridW);
        for (let i = a; i <= b; i++) fn(i, GUTTER_PX + sg.x + (i - sg.start) * cw - sx, i === sg.start);
      }
    };
    const anyColumn = segs.some((sg) => sg.kind === 'states');
    const lanes = layout.byKey;
    const gridBottom = layout.gridBottom;
    const brush = brushRef.current;
    const hover = hoverRef.current;

    // Column bands shared by every lane (a span over a stub covers it whole).
    const bands: Array<[number, number, string]> = [];
    if (selectedSpan) bands.push([selectedSpan[0], selectedSpan[1], colours.accentFill]);
    if (highlightSpan) bands.push([highlightSpan[0], highlightSpan[1], colours.highlightFill]);
    if (brush?.moved) {
      const extent = extentAtX(columns, brush.startGx, brush.endGx);
      if (extent) bands.push([extent[0], extent[1], colours.accentFill]);
    }
    if (hover?.col != null && !brush && !hover.hit) bands.push([hover.col, hover.col, colours.hoverFill]);

    ctx.save();
    ctx.beginPath();
    ctx.rect(GUTTER_PX, 0, gridW, view.h);
    ctx.clip();
    for (const [a, b, fill] of bands) {
      const span = spanOfIndices(columns, a, b);
      if (!span) continue;
      ctx.fillStyle = fill;
      ctx.fillRect(GUTTER_PX + span.x0 - sx, 0, span.x1 - span.x0, gridBottom);
    }

    // Logo: stacks of letters, the tallest on top.
    const logo = lanes.logo;
    if (logo && anyColumn) {
      const base = logo.y + logo.h;
      const scale = (logo.h - LOGO_TOP_PAD) / axis.top;
      ctx.strokeStyle = colours.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const t of axis.ticks) {
        const y = Math.round(base - t * scale) + 0.5;
        ctx.moveTo(GUTTER_PX, y);
        ctx.lineTo(view.w, y);
      }
      ctx.stroke();
      const dense = cw < DENSITY_PX;
      const pad = cw >= 12 ? 1 : 0;
      eachColumn((i, x) => {
        let y = base;
        for (let j = 0; j < k; j++) {
          const a = heights.order[i * k + j];
          const h = heights.heights[i * k + a] * scale;
          if (!(h > 0)) continue;
          y -= h;
          if (h < 0.4) continue;
          const colour = colourOf[i * k + a];
          if (dense || !atlas.draw(ctx, profile.letters[a], colour, x + pad, y, cw - 2 * pad, h)) {
            ctx.fillStyle = colour;
            ctx.fillRect(x, y, cw, h);
          }
        }
      });
    }

    // Consensus, RF and CS rows: characters when they fit.
    const textRow = (lane: Lane | undefined, values: (string | null)[] | null, coloured: boolean) => {
      if (!lane || !values) return;
      const fontPx = Math.max(7, Math.min(lane.h - 2, cw - 1, 12));
      const legible = cw >= 6;
      ctx.font = `600 ${fontPx}px ${colours.monoFont}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      eachColumn((i, x) => {
        const v = values[i];
        if (!v) return;
        let fill = colours.text;
        if (coloured) {
          const a = profile.letters.indexOf(v.toUpperCase());
          fill = a >= 0 ? colourOf[i * k + a] : colours.dimmed;
          if (v !== v.toUpperCase()) fill = alpha(fill, 0.55);
        } else {
          fill = colours.dimmed;
        }
        if (legible) {
          ctx.fillStyle = fill;
          ctx.fillText(v, x + cw / 2, lane.y + lane.h / 2 + 0.5);
        } else if (coloured) {
          ctx.fillStyle = fill;
          ctx.fillRect(x, lane.y + 3, cw, lane.h - 6);
        }
      });
    };
    textRow(lanes.consensus, profile.consensus, true);
    textRow(lanes.rf, profile.rf, false);
    textRow(lanes.cs, profile.cs, false);

    // Insert probability and expected length: heat strips, values when wide.
    const strip = (
      lane: Lane | undefined,
      values: (number | null)[] | null,
      colour: string,
      share: (v: number) => number,
      label: (v: number) => string,
    ) => {
      if (!lane || !values) return;
      const writeValues = cw >= NUMBERS_PX;
      ctx.font = `9px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      eachColumn((i, x) => {
        const v = values[i];
        if (v == null) return;
        const t = share(v);
        if (t > 0) {
          ctx.fillStyle = alpha(colour, 0.12 + 0.88 * t);
          ctx.fillRect(x, lane.y + 1, cw, lane.h - 2);
        }
        if (writeValues) {
          ctx.fillStyle = t > 0.6 ? colours.text : colours.dimmed;
          ctx.fillText(label(v), x + cw / 2, lane.y + lane.h / 2 + 0.5);
        }
      });
    };
    strip(lanes.insertProb, profile.insertProb, colours.insert, (v) => Math.max(0, Math.min(1, v)), (v) =>
      v.toFixed(2).replace(/^0\./, '.'),
    );
    strip(
      lanes.insertLength,
      profile.insertLength,
      colours.insertLength,
      (v) => insertLengthShare(v, maxInsertLength),
      (v) => (v >= 10 ? v.toFixed(0) : v.toFixed(1)),
    );

    // Occupancy (or deletion) bars.
    const occ = lanes.occupancy;
    if (occ && profile.occupancy) {
      ctx.fillStyle = colours.bars;
      const barH = occ.h - 4;
      eachColumn((i, x) => {
        const o = profile.occupancy![i];
        if (o == null) return;
        const v = Math.max(0, Math.min(1, occupancyMode === 'delete' ? 1 - o : o));
        const h = v * barH;
        if (h <= 0) return;
        ctx.fillRect(x + (cw > 3 ? 0.5 : 0), occ.y + 2 + barH - h, cw > 3 ? cw - 1 : cw, h);
      });
    }

    // Hit coverage: depth per state as a stepped area, in the coverage lane or,
    // collapsed, as the density summary of the hits strip.
    const coverageArea = (top: number, barH: number) => {
      if (!coverage || maxDepth <= 0 || !anyColumn) return;
      const yOf = (d: number) => top + barH - (d / maxDepth) * barH;
      // One area per run of letters: a stub breaks it.
      for (const sg of segs) {
        if (sg.kind !== 'states') continue;
        const [a, b] = columnsInView(columns, sg, sx, gridW);
        if (b < a) continue;
        const x0 = GUTTER_PX + sg.x + (a - sg.start) * cw - sx;
        ctx.beginPath();
        ctx.moveTo(x0, top + barH);
        for (let i = a; i <= b; i++) {
          const d = coverage[profile.states[i] - 1] ?? 0;
          ctx.lineTo(x0 + (i - a) * cw, yOf(d));
          ctx.lineTo(x0 + (i - a + 1) * cw, yOf(d));
        }
        ctx.lineTo(x0 + (b - a + 1) * cw, top + barH);
        ctx.closePath();
        ctx.fillStyle = colours.coverageFill;
        ctx.fill();
        ctx.strokeStyle = colours.bars;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    };
    const cov = lanes.coverage;
    if (cov) coverageArea(cov.y + 3, cov.h - 5);

    // Collapsed tracks: a thin tinted strip; the hits one keeps a tiny density summary.
    for (const [track, strip] of Object.entries(layout.strips) as Array<[TrackKey, Lane]>) {
      ctx.fillStyle = colours.hoverFill;
      ctx.fillRect(GUTTER_PX, strip.y, gridW, strip.h);
      ctx.strokeStyle = colours.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(GUTTER_PX, Math.round(strip.y) + 0.5);
      ctx.lineTo(view.w, Math.round(strip.y) + 0.5);
      ctx.stroke();
      if (track === 'hits') coverageArea(strip.y + 2, strip.h - 3);
    }

    // Hit bars, packed in rows, coloured by E-value, partial ends jagged.
    const lane = lanes.hits;
    if (lane && hits && packing) {
      const barH = layout.hitBarPx;
      const rings: Array<[number, number, number, boolean, boolean]> = [];
      hits.forEach((h, idx) => {
        const row = packing.rowOf[idx];
        if (row >= layout.hitRowsShown) return;
        // A hit across a stub runs over it; one outside the window is not drawn.
        const span = spanOfIndices(columns, colOfState(h.from), colOfState(h.to));
        if (!span) return;
        const x0 = GUTTER_PX + span.x0 - sx;
        const x1 = GUTTER_PX + span.x1 - sx;
        if (x1 < GUTTER_PX || x0 > view.w) return;
        const y = hitBarTop(lane, row);
        ctx.fillStyle = rgbCss(rampColour(colours.evalueRamp, evalueT(h.evalue)));
        const edges = partialEdges(h, modelLength);
        // The window's cut is not the hit's own end.
        if (span.clippedStart) edges.left = false;
        if (span.clippedEnd) edges.right = false;
        const tooth = Math.min(3, barH / 2, (x1 - x0) / 4);
        if ((edges.left || edges.right) && barH >= 4 && tooth >= 1.5) {
          // Pfam-style jagged end where the hit stops short of the model.
          ctx.beginPath();
          ctx.moveTo(x0, y);
          ctx.lineTo(x1, y);
          if (edges.right) {
            ctx.lineTo(x1 - tooth, y + barH / 4);
            ctx.lineTo(x1, y + barH / 2);
            ctx.lineTo(x1 - tooth, y + (3 * barH) / 4);
          }
          ctx.lineTo(x1, y + barH);
          ctx.lineTo(x0, y + barH);
          if (edges.left) {
            ctx.lineTo(x0 + tooth, y + (3 * barH) / 4);
            ctx.lineTo(x0, y + barH / 2);
            ctx.lineTo(x0 + tooth, y + barH / 4);
          }
          ctx.closePath();
          ctx.fill();
        } else {
          ctx.fillRect(x0, y, x1 - x0, barH);
        }
        const selected = selectedHitKey != null && h.key === selectedHitKey;
        const ringed = selected || (selectedHitEntity != null && h.entity === selectedHitEntity);
        const pointed = highlightHitEntity != null && h.entity === highlightHitEntity;
        if (ringed || pointed || hover?.hit === h) rings.push([x0, y, x1 - x0, selected, pointed && !ringed]);
      });
      // Rings last: on bars this thin, the next row's fill would cover them.
      for (const [x0, y, w, selected, pointedOnly] of rings) {
        ctx.strokeStyle = pointedOnly ? colours.highlight : colours.accent;
        ctx.lineWidth = selected ? 2 : 1.25;
        ctx.strokeRect(x0 - 0.5, y - 0.5, w + 1, barH + 1);
      }
    }

    // Crosshair of a hover elsewhere.
    const highlightPx = highlightSpan ? spanOfIndices(columns, highlightSpan[0], highlightSpan[1]) : null;
    if (highlightPx && logo) {
      ctx.strokeStyle = colours.highlight;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(GUTTER_PX + highlightPx.x0 - sx, logo.y + 0.75, highlightPx.x1 - highlightPx.x0, gridBottom - logo.y - 1.5);
    }

    // Ruler: HMM states above, reference residues below.
    const ruler = lanes.ruler;
    if (ruler && anyColumn) {
      const half = ruler.h / 2;
      const step = rulerStep(cw);
      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      ctx.strokeStyle = colours.dimmed;
      ctx.fillStyle = colours.dimmed;
      ctx.lineWidth = 1;
      // A label is kept whole inside the grid, shifted off its tick at an edge.
      const label = (text: string, x: number, y: number) => {
        const hw = ctx.measureText(text).width / 2;
        ctx.fillText(text, Math.max(GUTTER_PX + hw + 1, Math.min(view.w - hw - 1, x)), y);
      };
      let lastState = -Infinity;
      let lastResidue = -Infinity;
      eachColumn((i, colLeft, firstOfRun) => {
        const x = Math.round(colLeft + cw / 2) + 0.5;
        const state = profile.states[i];
        // The first column of every run is labelled, so a stub never leaves the reader without a bearing.
        if ((state % step === 0 || firstOfRun) && x - lastState >= 28) {
          ctx.beginPath();
          ctx.moveTo(x, ruler.y);
          ctx.lineTo(x, ruler.y + 3);
          ctx.stroke();
          label(String(state), x, ruler.y + half - 2);
          lastState = x;
        }
        const pos = profile.positions[i];
        if (pos != null && (pos % step === 0 || firstOfRun) && x - lastResidue >= 28) {
          label(String(pos), x, ruler.y + ruler.h - 3);
          lastResidue = x;
        }
      });
    }

    // Folded runs: a dimmed, hatched strip over every lane, with the number of
    // states when the logo lane is tall enough to carry it sideways.
    for (const stub of stubs) {
      const x = GUTTER_PX + stub.x - sx;
      const hovered = hover?.stub?.key === stub.key;
      ctx.save();
      ctx.beginPath();
      ctx.rect(x, 0, stub.w, gridBottom);
      ctx.clip();
      ctx.fillStyle = hovered ? colours.accentFill : colours.hoverFill;
      ctx.fillRect(x, 0, stub.w, gridBottom);
      ctx.strokeStyle = hovered ? colours.accent : colours.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let yy = 0; yy < gridBottom + stub.w; yy += 6) {
        ctx.moveTo(x, yy);
        ctx.lineTo(x + stub.w, yy - stub.w);
      }
      ctx.stroke();
      ctx.restore();
      ctx.strokeStyle = hovered ? colours.accent : colours.dimmed;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, gridBottom);
      ctx.moveTo(Math.round(x + stub.w) - 0.5, 0);
      ctx.lineTo(Math.round(x + stub.w) - 0.5, gridBottom);
      ctx.stroke();
      if (logo) {
        const text = `${stub.count} ${stub.count === 1 ? 'state' : 'states'}`;
        ctx.font = `9px ${colours.font}`;
        if (ctx.measureText(text).width + 8 <= logo.h) {
          ctx.save();
          ctx.translate(x + stub.w / 2, logo.y + logo.h / 2);
          ctx.rotate(-Math.PI / 2);
          ctx.fillStyle = colours.dimmed;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          // A plain fill would hatch through the digits: knock a pill out first.
          const tw = ctx.measureText(text).width;
          ctx.clearRect(-tw / 2 - 2, -6, tw + 4, 12);
          ctx.fillText(text, 0, 0.5);
          ctx.restore();
        }
      }
    }
    ctx.restore();

    // Gutter: lane labels and the logo's y axis.
    ctx.fillStyle = colours.dimmed;
    ctx.font = `10px ${colours.font}`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const labels: Partial<Record<string, string>> = {
      consensus: 'Consensus',
      rf: profile.source === 'msa' ? 'Reference' : 'RF',
      cs: 'CS',
      insertProb: 'Insert P',
      insertLength: 'Insert len',
      occupancy: occupancyMode === 'delete' ? 'Delete P' : 'Occupancy',
      coverage: hitsLaneLabel(coverageCount, hitsDrawn),
    };
    const labelRoom = GUTTER_PX - 8 - (onToggleTrack ? TRACK_BUTTON_PX : 0);
    for (const l of layout.lanes) {
      if (l.key === 'strip' && l.track) {
        ctx.font = `9px ${colours.font}`;
        const name =
          l.track === 'hits'
            ? `Hits ${coverageCount}`
            : l.track === 'occupancy'
              ? (labels.occupancy ?? TRACK_LABELS.occupancy)
              : l.track === 'ruler'
                ? 'Ruler'
                : TRACK_LABELS[l.track].replace(' rows', '');
        ctx.fillText(name, 4, l.y + l.h / 2 + 0.5);
        ctx.font = `10px ${colours.font}`;
        continue;
      }
      const text = labels[l.key];
      if (!text) continue;
      if (ctx.measureText(text).width > labelRoom && text.includes(HITS_LABEL_SEPARATOR)) {
        // The summary does not fit the gutter on one line: count above, drawn below.
        const [head, tail] = text.split(HITS_LABEL_SEPARATOR);
        ctx.fillText(head, 4, l.y + l.h / 2 - 5.5);
        ctx.fillText(tail, 4, l.y + l.h / 2 + 6.5);
      } else {
        ctx.fillText(text, 4, l.y + l.h / 2 + 0.5);
      }
    }
    if (ruler) {
      ctx.fillText('State', 4, ruler.y + ruler.h / 4 + 1);
      ctx.fillText('Residue', 4, ruler.y + (3 * ruler.h) / 4);
    }
    if (logo) {
      const base = logo.y + logo.h;
      const scale = (logo.h - LOGO_TOP_PAD) / axis.top;
      ctx.textAlign = 'right';
      let lastY = Infinity;
      for (const t of axis.ticks) {
        const y = base - t * scale;
        if (lastY - y < 12 && t !== 0) continue;
        ctx.fillText(t % 1 === 0 ? String(t) : t.toFixed(1), GUTTER_PX - 6, Math.max(6, y));
        lastY = y;
      }
      ctx.save();
      ctx.translate(10, logo.y + logo.h / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillText(axis.unit, 0, 0);
      ctx.restore();
    }
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(GUTTER_PX - 0.5, 0);
    ctx.lineTo(GUTTER_PX - 0.5, view.h);
    if (logo) {
      ctx.moveTo(GUTTER_PX, logo.y + logo.h - 0.5);
      ctx.lineTo(view.w, logo.y + logo.h - 0.5);
    }
    ctx.stroke();

    if (!drawnRef.current && m > 0) {
      drawnRef.current = true;
      onDrawn?.();
    }
  }, [
    view,
    gridW,
    cw,
    columns,
    k,
    layout,
    colours,
    isDark,
    axis,
    heights,
    colourOf,
    profile,
    selectedSpan,
    highlightSpan,
    occupancyMode,
    coverage,
    coverageCount,
    hitsDrawn,
    onToggleTrack,
    maxDepth,
    maxInsertLength,
    hits,
    packing,
    evalueT,
    colOfState,
    modelLength,
    selectedHitKey,
    selectedHitEntity,
    highlightHitEntity,
    onDrawn,
  ]);

  const requestDraw = useDrawScheduler(draw);

  // ---- follow an incoming selection / highlight ------------------------------
  const followSpan = highlightSpan ?? selectedSpan;
  const followPx = followSpan ? spanOfIndices(columns, followSpan[0], followSpan[1]) : null;
  useEffect(() => {
    const el = scrollRef.current;
    if (!followSelection || !el || !followPx || gridW <= 0) return;
    const next = scrollToReveal(el.scrollLeft, gridW, followPx.x0, followPx.x1);
    if (next != null) el.scrollLeft = next;
  }, [followSelection, followPx?.x0, followPx?.x1, gridW]);

  // ---- pointer ---------------------------------------------------------------
  const pointerAt = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>): PointerAt => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const x = rect ? e.clientX - rect.left : 0;
      const y = rect ? e.clientY - rect.top : 0;
      const sx = scrollRef.current?.scrollLeft ?? 0;
      const gx = x - GUTTER_PX + sx;
      const found = x >= GUTTER_PX ? indexAtX(columns, gx) : null;
      const stub = found?.segment.kind === 'stub' ? found.segment : null;
      const col = found && !stub ? found.index : null;
      const lane = laneAt(layout, y);
      let hit: LogoHit | null = null;
      if (col != null && lane?.key === 'hits' && hits && packing) {
        const row = hitRowAt(layout, y);
        if (row >= 0) hit = hitAt(hits, packing, row, profile.states[col]);
      }
      return { col, stub, lane, hit, x, y, gx, over: found != null };
    },
    [columns, layout, hits, packing, profile.states],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const at = pointerAt(e);
    brushRef.current = {
      startCol: at.col ?? -1,
      startGx: at.gx,
      endGx: at.gx,
      stub: at.stub,
      x: at.x,
      y: at.y,
      moved: false,
      hit: at.hit,
      inGrid: at.over,
    };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const at = pointerAt(e);
    const brush = brushRef.current;
    if (brush) {
      if (!brush.moved && brush.inGrid && onPickStates && Math.hypot(at.x - brush.x, at.y - brush.y) > DRAG_PX) {
        brush.moved = true;
      }
      if (brush.moved) {
        brush.endGx = at.gx;
        requestDraw();
        return;
      }
    }
    hoverRef.current = at;
    setTooltip(at.col != null || at.stub ? at : null);
    onHover?.(at.col != null ? { index: at.col, hit: at.hit } : null);
    requestDraw();
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const brush = brushRef.current;
    brushRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!brush) return;
    if (brush.moved && onPickStates) {
      const extent = extentAtX(columns, brush.startGx, brush.endGx);
      if (extent) onPickStates(extent[0], extent[1]);
    } else if (brush.stub && onExpandStub) {
      onExpandStub(brush.stub);
    } else if (brush.hit && onClickHit) {
      onClickHit(brush.hit);
    } else if (brush.inGrid && brush.startCol >= 0 && onPickStates) {
      onPickStates(brush.startCol, brush.startCol);
    } else if (!brush.inGrid) {
      onClear?.();
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

  // ---- tooltip -----------------------------------------------------------------
  const tip = useMemo(() => {
    if (tooltip?.stub) {
      const stub = tooltip.stub;
      const first = profile.states[stub.start];
      const last = profile.states[stub.end];
      const lines = [`${stub.count} ${stub.count === 1 ? 'state' : 'states'} folded`];
      lines.push(first === last ? `State ${first}` : `States ${first}-${last}`);
      const residues = residueRangeOfStates(profile.positions, stub.start, stub.end);
      if (residues) lines.push(`Residues ${residues.start}-${residues.end}`);
      lines.push(stub.source === 'auto' ? `Information under ${fmt(collapseBelowIc)} bits` : 'Hidden by hand');
      lines.push(onExpandStub ? 'Click to expand' : '');
      return lines.filter(Boolean);
    }
    if (!tooltip || tooltip.col == null) return null;
    const i = tooltip.col;
    const h = tooltip.hit;
    if (h) {
      const edges = partialEdges(h, modelLength);
      const partial = [edges.left ? 'N-terminal' : null, edges.right ? 'C-terminal' : null].filter(Boolean);
      const lines = [
        h.entity,
        `HMM ${h.from}-${h.to}${h.modelLength ?? modelLength ? ` of ${h.modelLength ?? modelLength}` : ''}${
          partial.length ? ` (partial: ${partial.join(', ')} end missing)` : ''
        }`,
      ];
      if (h.aliFrom != null) lines.push(`Residues ${h.aliFrom}-${h.aliTo ?? h.aliFrom}`);
      const stats = [
        h.evalue != null ? `E-value ${formatEvalue(h.evalue)}` : null,
        h.score != null ? `score ${fmt(h.score, 1)}` : null,
      ].filter(Boolean);
      if (stats.length) lines.push(stats.join(' · '));
      return lines;
    }
    const state = profile.states[i];
    const pos = profile.positions[i];
    const where = pos != null ? `residue ${pos}` : hasPositions ? 'reference deletion' : null;
    const lines = [where ? `State ${state} · ${where}` : `State ${state}`];
    const top = topLetters(profile, i, 4);
    if (top.length) lines.push(top.map((t) => `${t.letter} ${t.p.toFixed(2)}`).join('  '));
    lines.push(`Information ${fmt(information[i])} bits`);
    const indel: string[] = [];
    if (profile.insertProb?.[i] != null) indel.push(`insert P ${fmt(profile.insertProb[i], 3)}`);
    if (profile.insertLength?.[i] != null) indel.push(`insert length ${fmt(profile.insertLength[i])}`);
    if (indel.length) lines.push(indel.join(' · ').replace(/^./, (c) => c.toUpperCase()));
    if (profile.occupancy?.[i] != null) lines.push(`Occupancy ${fmt(profile.occupancy[i], 3)}`);
    const notes = [
      profile.consensus?.[i] ? `consensus ${profile.consensus[i]}` : null,
      profile.rf?.[i] ? `${profile.source === 'msa' ? 'reference' : 'RF'} ${profile.rf[i]}` : null,
      profile.cs?.[i] ? `CS ${profile.cs[i]}` : null,
    ].filter(Boolean);
    if (notes.length) lines.push(notes.join(' · ').replace(/^./, (c) => c.toUpperCase()));
    if (coverage && tooltip.lane?.key === 'coverage') {
      lines.push(`Covered by ${coverage[state - 1] ?? 0} of ${coverageCount} hits`);
    }
    return lines;
  }, [tooltip, profile, hasPositions, information, coverage, coverageCount, modelLength, collapseBelowIc, onExpandStub]);

  return (
    <Box className="depictio-hmm-logo-panel" pos="relative" style={{ width: '100%', height: '100%', minHeight: 0 }}>
      <div
        ref={scrollRef}
        onScroll={() => requestDraw()}
        style={{ position: 'absolute', inset: 0, overflowX: 'auto', overflowY: 'hidden' }}
      >
        <div style={{ position: 'relative', width: contentW, height: '100%', minWidth: '100%' }}>
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`HMM logo of ${profile.model ?? 'the model'}, ${m} match states${plan.shown < m ? `, ${plan.shown} drawn` : ''}`}
            style={{
              position: 'sticky',
              left: 0,
              top: 0,
              display: 'block',
              cursor: tooltip?.stub && onExpandStub ? 'pointer' : onPickStates ? 'crosshair' : 'default',
              touchAction: 'none',
            }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerLeave}
          />
        </div>
      </div>
      {onToggleTrack
        ? layout.tracks.map((span) => (
            <Tooltip
              key={span.track}
              label={span.collapsed ? 'Expand track' : 'Collapse track'}
              withArrow
              position="right"
              openDelay={300}
              portalProps={{ target: fsPortalTarget }}
            >
              <ActionIcon
                variant="subtle"
                color="gray"
                size={TRACK_BUTTON_PX}
                radius="xs"
                aria-label={`${span.collapsed ? 'Expand' : 'Collapse'} ${TRACK_LABELS[span.track]} track`}
                aria-expanded={!span.collapsed}
                data-testid={`hmm-logo-track-toggle-${span.track}`}
                onClick={() => onToggleTrack(span.track)}
                style={{
                  position: 'absolute',
                  zIndex: 3,
                  left: GUTTER_PX - TRACK_BUTTON_PX - 2,
                  top: span.y + (Math.min(span.h, TRACK_BUTTON_PX) - TRACK_BUTTON_PX) / 2,
                }}
              >
                <Icon
                  icon={span.collapsed ? 'tabler:chevron-right' : 'tabler:chevron-down'}
                  width={10}
                  height={10}
                />
              </ActionIcon>
            </Tooltip>
          ))
        : null}
      {tip && tooltip ? (
        <Paper
          withBorder
          shadow="sm"
          p={6}
          style={{
            position: 'absolute',
            pointerEvents: 'none',
            zIndex: 2,
            left: Math.min(tooltip.x + 14, Math.max(0, view.w - 250)),
            top: Math.min(tooltip.y + 14, Math.max(0, view.h - 110)),
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

export default LogoPanel;
