import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import {
  fitCellWidth,
  fitText,
  lettersFit,
  prepareCanvas,
  rulerStep,
  scrollToReveal,
  visibleWindow,
} from '../protein/canvas';
import { useDrawScheduler, useViewSize } from '../protein/canvasHooks';
import type { ZoomSyncHandle } from '../../../highlight/zoomSync';
import { useModifierWheelZoom } from '../protein/useWheelZoom';
import { uniformAxis } from '../protein/zoomAxis';
import { panelColours, type PanelColours } from '../protein/panelTheme';
import { rgbCss, type SecondaryStructure } from '../protein/residueColours';
import type { Run } from '../protein/sequence';
import { drawSecondaryStructureRuns, SS_GLYPH_FILLS } from '../protein/ssGlyphs';
import type { ProteinHighlight, ResidueRange } from '../protein/types';
import type { SsStateColours } from './stateColours';
import {
  agreementRuns,
  alphaRuns,
  confidenceAlpha,
  denseByPosition,
  meanFinite,
  runsOfSource,
  spanOf,
  tooltipLines,
  type AlphaRun,
  type SsAgreement,
  type SsModel,
} from './ssModel';
import { layoutPanelLanes, LETTERS_PX, type PanelLaneKey } from './panelLanes';
import { DEFAULT_RIBBON_PX } from './ribbonHeight';

const LABEL_PX = 88;
export { DEFAULT_RIBBON_PX };
const DRAG_PX = 3;
/** Narrower cells than this cannot show a residue's own opacity: a run gets its mean. */
const PER_RESIDUE_ALPHA_MIN_CW = 1.5;
/** Opacity of the coil share of the probability lanes (coil has no glyph colour). */
const COIL_AREA_ALPHA = 0.55;

interface Lane {
  key: PanelLaneKey;
  title: string;
  y: number;
  h: number;
  /** Index in `model.sources` of a ribbon lane. */
  source: number;
}

/** A run with the pieces it is drawn in, one opacity each. */
interface RibbonRun {
  run: Run<SecondaryStructure>;
  pieces: AlphaRun<SecondaryStructure>[];
}

export interface SecondaryStructurePanelProps {
  model: SsModel;
  /** The sources compared, from `agreementOf(model)`; null with one source. */
  agreement: SsAgreement | null;
  showProbabilities?: boolean;
  /** Draw the agreement lane (when `agreement` is not null). */
  showAgreement?: boolean;
  /** Write the one-letter sequence under the ruler when the cells are wide enough. */
  showLetters?: boolean;
  /** Shade each residue's glyph by its confidence. */
  shadeConfidence?: boolean;
  /** Height of the main ribbon lane, drawn exactly. Null or omitted: the
   *  default height, growing into spare room up to its cap (`ribbonHeight.ts`). */
  ribbonHeight?: number | null;
  /** Colours of the classes the tile, its config or the dashboard sets; the
   *  others keep the defaults. */
  stateColours?: SsStateColours;
  selectedRange?: ResidueRange | null;
  highlight?: ProteinHighlight | null;
  /** Pointer over a residue; null when it leaves. */
  onHover?: (position: number | null) => void;
  /** Brush released: the residue range, or null for a click that clears. Omit
   *  to disable brushing. A plain click selects one residue. */
  onBrush?: (range: ResidueRange | null) => void;
  /** CSS height of the panel; defaults to its natural lane height. */
  height?: number | string;
  /** Pixels per residue; defaults to fitting the width. */
  cellWidth?: number;
  /** Ctrl / Cmd + wheel asks for this many px per residue (whole pixels; 0 fits). */
  onCellWidthChange?: (px: number) => void;
  /** Zoom sync with the view's other residue tiles. */
  zoomSync?: ZoomSyncHandle | null;
  /** Scroll an incoming `selectedRange` / `highlight` into view. Default true. */
  followSelection?: boolean;
  /** Called once the first frame with data has been drawn. */
  onDrawn?: () => void;
}

/**
 * One protein's secondary structure on one 2D canvas: a ruler, the sequence
 * letters when the cells are wide enough, a topology ribbon per prediction
 * source (helix bars, strand arrows, turns and a coil line, each residue
 * shaded by its confidence), the lane marking where the sources agree and the
 * stacked helix / strand / coil probabilities. Horizontally virtualised and
 * zoomable through `cellWidth`; controlled like `SequenceStrip`.
 */
const SecondaryStructurePanel: React.FC<SecondaryStructurePanelProps> = ({
  model,
  agreement,
  showProbabilities = true,
  showAgreement = true,
  showLetters = true,
  shadeConfidence = true,
  ribbonHeight,
  stateColours,
  selectedRange,
  highlight,
  onHover,
  onBrush,
  height,
  cellWidth,
  onCellWidthChange,
  zoomSync = null,
  followSelection = true,
  onDrawn,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const colours: PanelColours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);
  // Pinned colours over the defaults: the three filled glyphs and the coil
  // line (the panel's own grey unless the dashboard pins one).
  const fills = useMemo(
    () => ({
      helix: stateColours?.helix ?? SS_GLYPH_FILLS.helix,
      strand: stateColours?.strand ?? SS_GLYPH_FILLS.strand,
      turn: stateColours?.turn ?? SS_GLYPH_FILLS.turn,
    }),
    [stateColours],
  );
  const pinnedCoil = stateColours?.coil ?? null;
  const agreeColour = theme.colors.teal[isDark ? 4 : 6];
  const disagreeColour = theme.colors.red[isDark ? 4 : 6];

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const view = useViewSize(scrollRef);

  // ---- axis ------------------------------------------------------------------
  const span = useMemo(() => spanOf(model), [model]);
  const minPos = span?.min ?? 1;
  const count = span ? span.max - span.min + 1 : 0;
  const gridW = Math.max(0, view.w - LABEL_PX);
  const fitCw = fitCellWidth(gridW, count, 0.05, 24);
  const cw = cellWidth && cellWidth > 0 ? cellWidth : fitCw;
  const contentW = LABEL_PX + count * cw;
  // The floor is the smallest fitted width, so zooming out from "fit" rounds
  // to 0 (fit) instead of jumping to a wider column.
  useModifierWheelZoom(scrollRef, {
    value: cw,
    setValue: onCellWidthChange,
    min: 0.05,
    max: 24,
    gutter: LABEL_PX,
    sync: zoomSync && {
      ...zoomSync,
      axis: uniformAxis(minPos, cw),
      fit: fitCw,
      requested: cellWidth && cellWidth > 0 ? cellWidth : 0,
      ready: count > 0 && gridW > 0,
    },
  });

  // ---- data ------------------------------------------------------------------
  const hasLetters = showLetters && model.letters.some((l) => l != null);
  const lettersOn = hasLetters && lettersFit(cw, LETTERS_PX);
  const agreementOn = showAgreement && agreement != null;
  const probSource = showProbabilities ? model.sources.findIndex((s) => s.hasProbabilities) : -1;
  const perResidueAlpha = cw >= PER_RESIDUE_ALPHA_MIN_CW;

  const ribbons = useMemo<RibbonRun[][]>(
    () =>
      model.sources.map((source, k) => {
        const runs = runsOfSource(model, k);
        const shaded = shadeConfidence && source.confidence.some((c) => c != null);
        const alphaAt = (p: number): number => {
          const i = model.index.get(p);
          return i === undefined ? 1 : confidenceAlpha(source.confidence[i]);
        };
        return runs.map((run) => ({
          run,
          pieces: shaded
            ? alphaRuns([run], alphaAt, { perResidue: perResidueAlpha })
            : [{ ...run, alpha: 1 }],
        }));
      }),
    [model, shadeConfidence, perResidueAlpha],
  );
  const agreeRuns = useMemo(
    () => (agreementOn ? agreementRuns(model, agreement) : []),
    [agreementOn, model, agreement],
  );
  const dense = useMemo(() => {
    if (probSource < 0 || count <= 0) return null;
    const s = model.sources[probSource];
    return {
      helix: denseByPosition(model, s.pHelix, minPos, count),
      strand: denseByPosition(model, s.pStrand, minPos, count),
      coil: denseByPosition(model, s.pCoil, minPos, count),
    };
  }, [model, probSource, minPos, count]);

  // ---- lanes -----------------------------------------------------------------
  // The lanes share the height the cell gives them, each up to its cap, and
  // what they cannot take centres the stack (see `panelLanes.ts`). The offset
  // is part of every lane's `y`, so drawing and hit-testing agree.
  const layout = useMemo(
    () =>
      layoutPanelLanes(
        {
          ribbonHeight,
          letters: lettersOn,
          extraSources: Math.max(0, model.sources.length - 1),
          agreement: agreementOn,
          probabilities: probSource >= 0,
        },
        view.h,
      ),
    [ribbonHeight, lettersOn, model.sources.length, agreementOn, probSource, view.h],
  );
  const lanes = useMemo<Lane[]>(() => {
    const pct = agreement?.fraction != null ? ` ${Math.round(agreement.fraction * 100)}%` : '';
    const titleOf = (key: PanelLaneKey, source: number): string => {
      switch (key) {
        case 'ruler':
          return 'Residue';
        case 'letters':
          return 'Sequence';
        case 'ribbon':
          return model.sources[source]?.name ?? '';
        case 'agreement':
          return `Agreement${pct}`;
        case 'probabilities':
          return model.sources.length > 1 ? `P · ${model.sources[probSource].name}` : 'P(H/E/C)';
      }
    };
    return layout.lanes.map((l) => {
      // The probabilities come from the first source that has them, not the main one.
      const source = l.key === 'probabilities' ? probSource : l.source;
      return { ...l, source, title: titleOf(l.key, source) };
    });
  }, [layout, model.sources, agreement, probSource]);
  const naturalH = layout.naturalH;

  // ---- interaction state -------------------------------------------------------
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
  // A new protein is a new first frame: report it again once drawn.
  useEffect(() => {
    drawnRef.current = false;
  }, [model]);

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
    const lane = (key: PanelLaneKey) => lanes.find((l) => l.key === key);
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

    // Letters (the lane exists only when the cells are wide enough to read).
    const letters = lane('letters');
    if (letters) {
      ctx.font = `${Math.max(7, Math.min(12, cw, letters.h - 2))}px ${colours.monoFont}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = colours.text;
      for (let pos = p0; pos <= p1; pos++) {
        const i = model.index.get(pos);
        const letter = i === undefined ? null : model.letters[i];
        if (letter) ctx.fillText(letter, xOf(pos) + cw / 2, letters.y + letters.h / 2 + 0.5);
      }
    }

    // Ribbons, one per source: each run as its glyph, drawn at each piece's opacity.
    for (const l of lanes) {
      if (l.key !== 'ribbon') continue;
      const geometry = {
        xOf,
        cellWidth: cw,
        yMid: l.y + l.h / 2,
        height: l.h,
        visible: [p0, p1] as const,
      };
      const glyphColours = { fills, coil: pinnedCoil ?? colours.dimmed };
      for (const { run, pieces } of ribbons[l.source] ?? []) {
        if (run.end < p0 || run.start > p1) continue;
        if (pieces.length === 1) {
          ctx.globalAlpha = pieces[0].alpha;
          drawSecondaryStructureRuns(ctx, [run], geometry, glyphColours);
          ctx.globalAlpha = 1;
          continue;
        }
        for (const piece of pieces) {
          if (piece.end < p0 || piece.start > p1) continue;
          ctx.save();
          ctx.beginPath();
          ctx.rect(xOf(piece.start), l.y, (piece.end - piece.start + 1) * cw, l.h);
          ctx.clip();
          ctx.globalAlpha = piece.alpha;
          drawSecondaryStructureRuns(ctx, [run], geometry, glyphColours);
          ctx.restore();
        }
      }
    }

    // Agreement: a tall mark where the sources differ, a short one where they agree.
    const agr = lane('agreement');
    if (agr) {
      for (const run of agreeRuns) {
        if (run.end < p0 || run.start > p1) continue;
        const x = xOf(run.start);
        const w = Math.max((run.end - run.start + 1) * cw, 0.5);
        if (run.value === 'agree') {
          ctx.fillStyle = agreeColour;
          ctx.globalAlpha = 0.55;
          ctx.fillRect(x, agr.y + agr.h * 0.55, w, agr.h * 0.45);
          ctx.globalAlpha = 1;
        } else {
          ctx.fillStyle = disagreeColour;
          ctx.fillRect(x, agr.y + 1, w, agr.h - 1);
        }
      }
    }

    // Probabilities: the three shares of each residue stacked to the lane height.
    const probs = lane('probabilities');
    if (probs && dense) {
      const top = probs.y + 1;
      const room = probs.h - 2;
      const baseY = top + room;
      const perBin = cw >= 1 ? 1 : Math.ceil(1 / cw);
      // Bar edges are snapped to device pixels so neighbours abut exactly: no
      // seams between opaque bars, no doubled alpha on the coil share.
      const dpr = typeof window !== 'undefined' ? Math.max(1, window.devicePixelRatio || 1) : 1;
      const snap = (v: number) => Math.round(v * dpr) / dpr;
      const shares = [
        fills.helix,
        fills.strand,
        pinnedCoil ?? rgbCss(colours.neutral, COIL_AREA_ALPHA),
      ];
      // Bins start on multiples of `perBin` from the axis origin, so they do not shift with the scroll.
      for (let pos = p0 - ((p0 - minPos) % perBin); pos <= p1; pos += perBin) {
        const last = Math.min(minPos + count - 1, pos + perBin - 1);
        const a = pos - minPos;
        const b = last - minPos;
        const parts = [
          meanFinite(dense.helix, a, b),
          meanFinite(dense.strand, a, b),
          meanFinite(dense.coil, a, b),
        ];
        if (parts.every((v) => v == null)) continue;
        const sum = parts.reduce<number>((s, v) => s + (v ?? 0), 0);
        // Shares that overshoot 1 (rounding) are scaled back; short ones leave a gap.
        const denom = Math.max(sum, 1);
        const x0 = snap(xOf(pos));
        const w = Math.max(snap(xOf(last + 1)) - x0, 1 / dpr);
        let acc = 0;
        parts.forEach((v, k) => {
          if (v == null || v <= 0) return;
          const next = acc + v / denom;
          const yTop = snap(baseY - next * room);
          const yBottom = snap(baseY - acc * room);
          acc = next;
          if (yBottom <= yTop) return;
          ctx.fillStyle = shares[k];
          // A pinned coil colour is opaque: it takes the share's opacity here.
          if (k === 2 && pinnedCoil) ctx.globalAlpha = COIL_AREA_ALPHA;
          ctx.fillRect(x0, yTop, w, yBottom - yTop);
          ctx.globalAlpha = 1;
        });
      }
      ctx.strokeStyle = colours.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xOf(minPos), top + room / 2 + 0.5);
      ctx.lineTo(xOf(minPos + count), top + room / 2 + 0.5);
      ctx.stroke();
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

    if (!drawnRef.current && model.positions.length > 0) {
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
    agreeColour,
    disagreeColour,
    fills,
    pinnedCoil,
    selectedRange,
    highlight,
    model,
    ribbons,
    agreeRuns,
    dense,
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
    onHover?.(p.position);
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
    } else if (onBrush && p.position != null) {
      const same =
        selectedRange &&
        selectedRange.start === p.position &&
        (selectedRange.end ?? selectedRange.start) === p.position;
      onBrush(same ? null : { start: p.position, end: p.position });
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

  const tip = useMemo(
    () => (tooltip ? tooltipLines(model, tooltip.position, agreement) : null),
    [tooltip, model, agreement],
  );

  const cssHeight = height ?? naturalH;

  return (
    <Box
      className="depictio-secondary-structure-panel"
      pos="relative"
      style={{ width: '100%', height: cssHeight, minHeight: Math.min(naturalH, 60) }}
    >
      <div
        ref={scrollRef}
        onScroll={() => requestDraw()}
        style={{ position: 'absolute', inset: 0, overflowX: 'auto', overflowY: 'hidden' }}
      >
        <div style={{ position: 'relative', width: contentW, height: '100%', minWidth: '100%' }}>
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Secondary structure, ${model.positions.length} residues, ${model.sources.length} ${
              model.sources.length === 1 ? 'source' : 'sources'
            }`}
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

export default SecondaryStructurePanel;
