import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { prepareCanvas, rulerStep } from '../protein/canvas';
import { useDrawScheduler, useViewSize } from '../protein/canvasHooks';
import { panelColours, type PanelColours } from '../protein/panelTheme';
import { plddtBand, plddtIsFractional, rgbCss } from '../protein/residueColours';
import { axisTicks, chainSpans, residueLabel, type ResidueAxis } from './axis';
import {
  cellAt,
  clickGesture,
  dragGesture,
  hitTest,
  hoverIndex,
  paeLayout,
  PAE_GEOMETRY,
  type BrushMode,
  type Cell,
  type PaeGesture,
  type PaeHit,
} from './brush';
import { imageSide, lutColour, renderPaeImage } from './paeImage';
import { paeAt, type PaeMatrix } from './paeParse';

/** Pointer travel (CSS px) before a press becomes a drag. */
const DRAG_PX = 3;
/** Colour bar gradient stops. */
const BAR_STOPS = 16;

export interface PaePanelProps {
  matrix: PaeMatrix;
  axis: ResidueAxis;
  /** Colour lookup table (`paeImage.buildLut`), 0 Å first. */
  lut: Uint8Array;
  /** Upper bound of the colour scale, Å. */
  colourMax: number;
  /** Draw the pLDDT strips (the axis carries values). */
  showStrips: boolean;
  brushMode: BrushMode;
  /** The residue pick in force (this tile's or another's), as matrix indices:
   *  its row and column bands are shaded and its square outlined. */
  selected: [number, number] | null;
  /** This tile's rectangle brush: the scored range is `selected`, the aligned
   *  range only lives here, as an outline. */
  outline: { x: [number, number]; y: [number, number] } | null;
  /** Another tile's hover, as matrix indices: crosshair lines. */
  highlight: [number, number] | null;
  /** Pointer over a residue (the scored one on a cell), null on leave. */
  onHover?: (index: number | null) => void;
  /** A drag or a click; null for a click off the plot. Omit to disable. */
  onSelect?: (gesture: PaeGesture | null) => void;
  /** First frame drawn for this matrix. */
  onDrawn?: () => void;
  /** What the strips show, for the tooltip. */
  valueLabel?: string;
}

interface Drag {
  start: Cell;
  current: Cell;
  x: number;
  y: number;
  moved: boolean;
  shift: boolean;
  inMatrix: boolean;
}

function formatTick(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/**
 * The PAE heatmap on one DPR-aware 2D canvas: the matrix as an image rendered
 * once per (matrix, colour scale, maximum, theme, size) and blitted without
 * smoothing, so a hover redraw costs a blit and a few lines; residue ticks on
 * both axes, optional pLDDT strips, chain boundaries on a complex and a colour
 * bar in Å. Controlled: picks and hovers come in as matrix indices and go out
 * as gestures (`brush.ts`).
 */
const PaePanel: React.FC<PaePanelProps> = ({
  matrix,
  axis,
  lut,
  colourMax,
  showStrips,
  brushMode,
  selected,
  outline,
  highlight,
  onHover,
  onSelect,
  onDrawn,
  valueLabel = 'pLDDT',
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const colours: PanelColours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const view = useViewSize(wrapRef);
  const n = matrix.n;

  const layout = useMemo(() => paeLayout(view.w, view.h, n, showStrips), [view.w, view.h, n, showStrips]);

  // ---- the matrix image ------------------------------------------------------
  const dpr = typeof window !== 'undefined' ? Math.max(1, window.devicePixelRatio || 1) : 1;
  const side = layout.plot.w > 0 ? imageSide(n, Math.round(layout.plot.w * dpr)) : 0;
  const image = useMemo(() => {
    if (side <= 0 || typeof document === 'undefined') return null;
    const { pixels } = renderPaeImage(matrix, side, lut, colourMax, colours.neutral);
    const canvas = document.createElement('canvas');
    canvas.width = side;
    canvas.height = side;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    const data = ctx.createImageData(side, side);
    data.data.set(pixels);
    ctx.putImageData(data, 0, 0);
    return canvas;
  }, [matrix, side, lut, colourMax, colours.neutral]);

  // ---- strips, ticks, chains -----------------------------------------------------
  const strips = useMemo(() => {
    const values = axis.residues.map((r) => r.value);
    const fractional = plddtIsFractional(values);
    const runs: { start: number; end: number; colour: string | null }[] = [];
    values.forEach((v, k) => {
      const colour = v == null || !Number.isFinite(v) ? null : rgbCss(plddtBand(v, fractional).rgb);
      const last = runs[runs.length - 1];
      if (last && last.colour === colour) last.end = k;
      else runs.push({ start: k, end: k, colour });
    });
    return { runs, fractional };
  }, [axis]);
  const xTicks = useMemo(() => axisTicks(axis, layout.cell, 40), [axis, layout.cell]);
  const yTicks = useMemo(() => axisTicks(axis, layout.cell, 22), [axis, layout.cell]);
  const chains = useMemo(() => chainSpans(axis), [axis]);

  const dragRef = useRef<Drag | null>(null);
  const hoverRef = useRef<PaeHit | null>(null);
  const lastHover = useRef<number | null>(null);
  const [tip, setTip] = useState<{ hit: PaeHit; x: number; y: number } | null>(null);
  const drawnRef = useRef(false);
  useEffect(() => {
    drawnRef.current = false;
  }, [matrix]);

  // ---- drawing -------------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || view.w <= 0 || view.h <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, view.h);
    if (!ctx) return;
    const { plot, cell, topStrip, leftStrip, bar } = layout;
    if (plot.w < 8 || !image) return;
    const S = plot.w;
    const px = plot.x;
    const py = plot.y;
    const at = (k: number) => k * cell;
    const drag = dragRef.current;
    const hover = hoverRef.current;

    // The matrix.
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(image, px, py, S, S);

    // Chain boundaries across the matrix.
    if (chains.length > 1) {
      ctx.strokeStyle = colours.dimmed;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const c of chains.slice(1)) {
        const o = Math.round(at(c.start)) + 0.5;
        ctx.moveTo(px + o, py);
        ctx.lineTo(px + o, py + S);
        ctx.moveTo(px, py + o);
        ctx.lineTo(px + S, py + o);
      }
      ctx.stroke();
    }

    // The pick: its row and column bands shaded outside the square, so the
    // square itself keeps its colours, and the square outlined.
    if (selected) {
      const a = at(selected[0]);
      const w = Math.max(at(selected[1] + 1) - a, 1);
      ctx.fillStyle = colours.accentFill;
      ctx.fillRect(px + a, py, w, a);
      ctx.fillRect(px + a, py + a + w, w, S - a - w);
      ctx.fillRect(px, py + a, a, w);
      ctx.fillRect(px + a + w, py + a, S - a - w, w);
      ctx.strokeStyle = colours.accent;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(px + a, py + a, w, w);
    }
    // The aligned range of this tile's rectangle brush.
    if (outline) {
      const x0 = at(outline.x[0]);
      const y0 = at(outline.y[0]);
      ctx.strokeStyle = colours.accent;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(
        px + x0,
        py + y0,
        Math.max(at(outline.x[1] + 1) - x0, 1),
        Math.max(at(outline.y[1] + 1) - y0, 1),
      );
      ctx.setLineDash([]);
    }
    // A brush in progress.
    if (drag && drag.moved) {
      const g = dragGesture(drag.start, drag.current, brushMode, drag.shift);
      const x0 = at(g.x[0]);
      const y0 = at(g.y[0]);
      const w = Math.max(at(g.x[1] + 1) - x0, 1);
      const h = Math.max(at(g.y[1] + 1) - y0, 1);
      ctx.fillStyle = colours.accentFill;
      ctx.fillRect(px + x0, py + y0, w, h);
      ctx.strokeStyle = colours.accent;
      ctx.lineWidth = 1;
      ctx.strokeRect(px + x0, py + y0, w, h);
    }

    // pLDDT strips, runs of one band merged.
    if (topStrip && leftStrip) {
      ctx.fillStyle = rgbCss(colours.neutral, 0.35);
      ctx.fillRect(topStrip.x, topStrip.y, topStrip.w, topStrip.h);
      ctx.fillRect(leftStrip.x, leftStrip.y, leftStrip.w, leftStrip.h);
      for (const run of strips.runs) {
        if (!run.colour) continue;
        const a = at(run.start);
        const len = Math.max(at(run.end + 1) - a, 0.5);
        ctx.fillStyle = run.colour;
        ctx.fillRect(px + a, topStrip.y, len, topStrip.h);
        ctx.fillRect(leftStrip.x, py + a, leftStrip.w, len);
      }
    }

    // Crosshairs: another tile's hover (highlight colour, through the strips),
    // then the pointer's own (dimmed).
    const crossFrom = { x: leftStrip ? leftStrip.x : px, y: topStrip ? topStrip.y : py };
    const crosshair = (k0: number, k1: number, stroke: string, fill: string) => {
      const a = at(k0);
      const w = at(k1 + 1) - a;
      if (w >= 3) {
        ctx.fillStyle = fill;
        ctx.fillRect(px + a, crossFrom.y, w, py + S - crossFrom.y);
        ctx.fillRect(crossFrom.x, py + a, px + S - crossFrom.x, w);
      }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1;
      ctx.beginPath();
      const mid = Math.round(a + w / 2) + 0.5;
      ctx.moveTo(px + mid, crossFrom.y);
      ctx.lineTo(px + mid, py + S);
      ctx.moveTo(crossFrom.x, py + mid);
      ctx.lineTo(px + S, py + mid);
      ctx.stroke();
    };
    if (highlight) crosshair(highlight[0], highlight[1], colours.highlight, colours.highlightFill);
    if (hover && !drag) {
      ctx.save();
      ctx.globalAlpha = 0.85;
      ctx.strokeStyle = colours.dimmed;
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (hover.region === 'matrix' || hover.region === 'top') {
        const x = Math.round(px + at(hover.j) + cell / 2) + 0.5;
        ctx.moveTo(x, crossFrom.y);
        ctx.lineTo(x, py + S);
      }
      if (hover.region === 'matrix' || hover.region === 'left') {
        const y = Math.round(py + at(hover.i) + cell / 2) + 0.5;
        ctx.moveTo(crossFrom.x, y);
        ctx.lineTo(px + S, y);
      }
      ctx.stroke();
      ctx.restore();
      if (hover.region === 'matrix' && cell >= 4) {
        ctx.strokeStyle = colours.text;
        ctx.strokeRect(px + at(hover.j) + 0.5, py + at(hover.i) + 0.5, cell - 1, cell - 1);
      }
    }

    // Frame.
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    ctx.strokeRect(px + 0.5, py + 0.5, S - 1, S - 1);

    // Axes: ticks, labels, titles.
    ctx.fillStyle = colours.dimmed;
    ctx.strokeStyle = colours.dimmed;
    ctx.font = `10px ${colours.font}`;
    ctx.beginPath();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const t of xTicks) {
      const x = Math.round(px + at(t.index) + cell / 2) + 0.5;
      ctx.moveTo(x, py + S);
      ctx.lineTo(x, py + S + 4);
      ctx.fillText(t.label, x, py + S + 5);
    }
    const yAxisX = leftStrip ? leftStrip.x : px;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const t of yTicks) {
      const y = Math.round(py + at(t.index) + cell / 2) + 0.5;
      ctx.moveTo(yAxisX - 4, y);
      ctx.lineTo(yAxisX, y);
      ctx.fillText(t.label, yAxisX - 6, y);
    }
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = colours.text;
    ctx.font = `11px ${colours.font}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('Scored residue', px + S / 2, py + S + PAE_GEOMETRY.xTicks + 1);
    ctx.save();
    ctx.translate(yAxisX - PAE_GEOMETRY.yTicks - PAE_GEOMETRY.yTitle / 2, py + S / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = 'middle';
    ctx.fillText('Aligned residue', 0, 0);
    ctx.restore();

    // Chain labels over their spans.
    if (chains.length > 1) {
      ctx.fillStyle = colours.dimmed;
      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      const y = (topStrip ? topStrip.y : py) - 2;
      for (const c of chains) {
        const w = at(c.end + 1) - at(c.start);
        if (w >= 14) ctx.fillText(c.chain, px + at(c.start) + w / 2, y);
      }
    }

    // Colour bar, 0 Å at the bottom.
    const gradient = ctx.createLinearGradient(0, bar.y + bar.h, 0, bar.y);
    for (let s = 0; s <= BAR_STOPS; s++) {
      const t = s / BAR_STOPS;
      gradient.addColorStop(t, rgbCss(lutColour(lut, t * colourMax, colourMax)));
    }
    ctx.fillStyle = gradient;
    ctx.fillRect(bar.x, bar.y, bar.w, bar.h);
    ctx.strokeStyle = colours.grid;
    ctx.strokeRect(bar.x + 0.5, bar.y + 0.5, bar.w - 1, bar.h - 1);
    ctx.fillStyle = colours.dimmed;
    ctx.strokeStyle = colours.dimmed;
    ctx.font = `10px ${colours.font}`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const step = rulerStep(bar.h / colourMax, 24);
    let topLabel = Infinity;
    ctx.beginPath();
    for (let v = 0; v <= colourMax + 1e-9; v += step) {
      const y = Math.round(bar.y + bar.h - (v / colourMax) * bar.h) + 0.5;
      ctx.moveTo(bar.x + bar.w, y);
      ctx.lineTo(bar.x + bar.w + 3, y);
      ctx.fillText(formatTick(v), bar.x + bar.w + 5, y);
      topLabel = y;
    }
    if (topLabel - bar.y > 14) {
      ctx.moveTo(bar.x + bar.w, bar.y + 0.5);
      ctx.lineTo(bar.x + bar.w + 3, bar.y + 0.5);
      ctx.fillText(formatTick(Number(colourMax.toFixed(2))), bar.x + bar.w + 5, bar.y + 1);
    }
    ctx.stroke();
    ctx.textBaseline = 'bottom';
    ctx.fillText('PAE (Å)', bar.x - 2, bar.y - 7);

    if (!drawnRef.current) {
      drawnRef.current = true;
      onDrawn?.();
    }
  }, [
    view,
    layout,
    image,
    chains,
    colours,
    selected,
    outline,
    brushMode,
    strips,
    highlight,
    xTicks,
    yTicks,
    lut,
    colourMax,
    onDrawn,
  ]);

  const requestDraw = useDrawScheduler(draw);

  // ---- pointer -----------------------------------------------------------------
  const pointAt = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    return { x: rect ? e.clientX - rect.left : 0, y: rect ? e.clientY - rect.top : 0 };
  };

  const hover = useCallback(
    (index: number | null) => {
      if (lastHover.current === index) return;
      lastHover.current = index;
      onHover?.(index);
    },
    [onHover],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const p = pointAt(e);
    const hit = hitTest(layout, n, p.x, p.y);
    const start = cellAt(layout, n, p.x, p.y);
    dragRef.current = {
      start,
      current: start,
      x: p.x,
      y: p.y,
      moved: false,
      shift: e.shiftKey,
      inMatrix: hit.region === 'matrix',
    };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const p = pointAt(e);
    const drag = dragRef.current;
    if (drag && drag.inMatrix && onSelect) {
      if (!drag.moved && Math.hypot(p.x - drag.x, p.y - drag.y) > DRAG_PX) drag.moved = true;
      if (drag.moved) {
        drag.current = cellAt(layout, n, p.x, p.y);
        drag.shift = e.shiftKey;
        setTip(null);
        requestDraw();
        return;
      }
    }
    const hit = hitTest(layout, n, p.x, p.y);
    hoverRef.current = hit.region === 'none' ? null : hit;
    setTip(hit.region === 'none' ? null : { hit, x: p.x, y: p.y });
    hover(hoverIndex(hit));
    requestDraw();
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!drag || !onSelect) {
      requestDraw();
      return;
    }
    if (drag.moved) {
      onSelect(dragGesture(drag.start, drag.current, brushMode, drag.shift));
    } else {
      const p = pointAt(e);
      const gesture = clickGesture(hitTest(layout, n, p.x, p.y));
      if (gesture) onSelect(gesture);
      else if (selected) onSelect(null);
    }
    requestDraw();
  };

  const onPointerLeave = () => {
    if (dragRef.current) return;
    hoverRef.current = null;
    setTip(null);
    hover(null);
    requestDraw();
  };

  const onPointerCancel = () => {
    dragRef.current = null;
    requestDraw();
  };

  // ---- tooltip -------------------------------------------------------------------
  const tipLines = useMemo(() => {
    if (!tip) return null;
    const band = (v: number | null) =>
      v == null || !Number.isFinite(v)
        ? null
        : `${Number(v.toFixed(2))} (${plddtBand(v, strips.fractional).label.split(' (')[0].toLowerCase()})`;
    const lines: string[] = [];
    const { hit } = tip;
    if (hit.region === 'matrix') {
      lines.push(`Scored ${residueLabel(axis, hit.j)} · aligned ${residueLabel(axis, hit.i)}`);
      const v = paeAt(matrix, hit.i, hit.j);
      lines.push(Number.isFinite(v) ? `PAE ${v.toFixed(2)} Å` : 'PAE missing');
      const vj = band(axis.residues[hit.j]?.value ?? null);
      const vi = band(axis.residues[hit.i]?.value ?? null);
      if (vj) lines.push(`${valueLabel} scored ${vj}`);
      if (vi && hit.i !== hit.j) lines.push(`${valueLabel} aligned ${vi}`);
    } else if (hit.region === 'top' || hit.region === 'left') {
      const k = hit.region === 'top' ? hit.j : hit.i;
      lines.push(`Residue ${residueLabel(axis, k)}`);
      const v = band(axis.residues[k]?.value ?? null);
      lines.push(v ? `${valueLabel} ${v}` : `No ${valueLabel}`);
    }
    return lines.length ? lines : null;
  }, [tip, axis, matrix, strips.fractional, valueLabel]);

  return (
    <Box className="depictio-pae-panel" pos="relative" style={{ width: '100%', height: '100%' }}>
      <div ref={wrapRef} style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`Predicted aligned error, ${n} by ${n} residues`}
          style={{
            display: 'block',
            cursor: onSelect ? 'crosshair' : 'default',
            touchAction: 'none',
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerLeave}
          onPointerCancel={onPointerCancel}
        />
      </div>
      {tip && tipLines ? (
        <Paper
          withBorder
          shadow="sm"
          p={6}
          style={{
            position: 'absolute',
            pointerEvents: 'none',
            zIndex: 2,
            left: Math.min(tip.x + 14, Math.max(0, view.w - 230)),
            top: Math.min(tip.y + 14, Math.max(0, view.h - 80)),
            maxWidth: 260,
          }}
        >
          {tipLines.map((line, k) => (
            <Text key={k} size="xs" fw={k === 0 ? 600 : 400} lineClamp={1}>
              {line}
            </Text>
          ))}
        </Paper>
      ) : null}
    </Box>
  );
};

export default PaePanel;
