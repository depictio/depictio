import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { contrastingText } from '../../../utils/colorScale';
import {
  chainLayoutLength,
  columnConservation,
  columnProfiles,
  columnRangeToResidueRange,
  concatToChain,
  percentIdentity,
  referenceColumnMap,
  residueRangeToColumnRange,
} from './alignment';
import {
  fitCellWidth,
  fitText,
  lettersFit,
  prepareCanvas,
  rulerStep,
  scrollToReveal,
  visibleWindow,
} from './canvas';
import { useDrawScheduler, useViewSize } from './canvasHooks';
import { panelColours, type PanelColours } from './panelTheme';
import { isGap, rgbCss, schemeColour, type ColumnProfile, type RGB } from './residueColours';
import type { MsaHover, MsaPanelProps } from './types';

/** Row height of an aligned sequence, CSS px. */
const ROW_PX = 14;
const RULER_PX = 18;
const CONSENSUS_PX = 14;
const CONSERVATION_PX = 20;
const ID_MIN_PX = 64;
const ID_MAX_PX = 180;
/** Pointer travel that turns a press into a brush rather than a click. */
const DRAG_PX = 3;

type Zone = 'cell' | 'id' | 'header' | 'corner';

/** A press in progress: where it started, whether it became a column brush. */
interface BrushState {
  startCol: number;
  endCol: number;
  x: number;
  y: number;
  moved: boolean;
  zone: Zone;
  row: number | null;
}

interface PointerCell {
  zone: Zone;
  col: number | null;
  row: number | null;
  x: number;
  y: number;
}

function zoneOf(inGridX: boolean, inGridY: boolean): Zone {
  if (inGridX) return inGridY ? 'cell' : 'header';
  return inGridY ? 'id' : 'corner';
}

/** Indices in `rows` of the given sequence ids (unknown ids skipped). */
function rowIndicesOf(keys: readonly string[] | undefined, indexById: Map<string, number>): Set<number> {
  const out = new Set<number>();
  for (const k of keys ?? []) {
    const i = indexById.get(k);
    if (i !== undefined) out.add(i);
  }
  return out;
}

/**
 * The residue colour of every cell, one pixel per cell, built once per data /
 * scheme change and blitted scaled (no smoothing) for whatever window is on
 * screen. That is what keeps a 500 x 1500 alignment smooth at any zoom: a
 * frame is one `drawImage`, plus letters only when cells are wide enough.
 */
function buildCellImage(
  sequences: readonly string[],
  width: number,
  scheme: string,
  profiles: readonly ColumnProfile[],
  neutral: RGB,
): HTMLCanvasElement | null {
  if (typeof document === 'undefined' || width === 0 || sequences.length === 0) return null;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = sequences.length;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(width, sequences.length);
  const data = img.data;
  // Column-major so each column resolves each of its letters once: a
  // context-aware scheme (Clustal X, identity) reads the column profile per
  // call, which over 750k cells would be the whole cost of the build.
  for (let c = 0; c < width; c++) {
    const perLetter = new Map<string, RGB | null>();
    for (let r = 0; r < sequences.length; r++) {
      const letter = sequences[r][c] ?? '-';
      if (isGap(letter)) continue;
      let rgb = perLetter.get(letter);
      if (rgb === undefined) {
        rgb = schemeColour(scheme, letter, profiles[c]);
        perLetter.set(letter, rgb);
      }
      const o = (r * width + c) * 4;
      const fill = rgb ?? neutral;
      data[o] = fill[0];
      data[o + 1] = fill[1];
      data[o + 2] = fill[2];
      // Uncoloured residues stay visible as faint blocks, so the shape of the
      // alignment (gaps, coverage) reads even under a sparse scheme.
      data[o + 3] = rgb ? 255 : 70;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

/**
 * A lightweight multiple sequence alignment viewer on one 2D canvas.
 *
 * Virtualised in both directions (a sticky canvas inside a scroll spacer, so
 * the browser's own scrollbars drive it), with a sticky id column, a ruler in
 * the reference row's numbering, consensus and conservation rows, a hover
 * crosshair, a column brush reported in reference residues and a row click.
 * Controlled: the caller passes the selection and the highlight back in.
 */
const MsaPanel: React.FC<MsaPanelProps> = ({
  rows,
  referenceIndex,
  chains,
  colourScheme = 'clustal',
  selectedRange,
  highlight,
  selectedRowKeys,
  onHoverColumn,
  onBrushColumns,
  onClickRow,
  height = '100%',
  cellWidth,
  showConsensus = true,
  showConservation = true,
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

  // ---- derived alignment ------------------------------------------------
  const sequences = useMemo(() => rows.map((r) => r.sequence), [rows]);
  const width = useMemo(() => sequences.reduce((m, s) => Math.max(m, s.length), 0), [sequences]);
  const refIdx = useMemo(() => {
    if (referenceIndex != null && referenceIndex >= 0 && referenceIndex < rows.length) {
      return referenceIndex;
    }
    const zero = rows.findIndex((r) => r.rank === 0);
    return zero >= 0 ? zero : 0;
  }, [rows, referenceIndex]);
  const refSeq = sequences[refIdx] ?? '';
  const refMap = useMemo(() => referenceColumnMap(refSeq), [refSeq]);
  const profiles = useMemo(() => columnProfiles(sequences, width), [sequences, width]);
  // Per column: the chain and the residue's own number in it, when a chain
  // layout is given and covers the reference exactly (else it is ignored: a
  // layout that does not add up would mislabel every residue after the break).
  const chainCols = useMemo(() => {
    if (!chains || !chains.length || chainLayoutLength(chains) !== refMap.residueCount) return null;
    const chain: (string | null)[] = new Array(width).fill(null);
    const local = new Int32Array(width).fill(-1);
    for (let c = 0; c < width; c++) {
      const res = refMap.colToRes[c];
      if (res < 0) continue;
      const hit = concatToChain(res, chains);
      if (!hit) continue;
      chain[c] = hit.chain;
      local[c] = hit.position;
    }
    return { chain, local, firstOf: new Map(chains.map((ch) => [ch.chain, ch.first])) };
  }, [chains, refMap, width]);
  const conservation = useMemo(
    () => Float32Array.from(profiles, (p) => columnConservation(p, sequences.length)),
    [profiles, sequences.length],
  );
  const cellImage = useMemo(
    () => buildCellImage(sequences, width, colourScheme, profiles, colours.neutral),
    [sequences, width, colourScheme, profiles, colours.neutral],
  );
  const rowIndexById = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => m.set(r.seqId, i));
    return m;
  }, [rows]);

  // ---- geometry ----------------------------------------------------------
  const idWidth = useMemo(() => {
    if (typeof document === 'undefined') return ID_MAX_PX;
    const ctx = document.createElement('canvas').getContext('2d');
    if (!ctx) return ID_MAX_PX;
    ctx.font = `600 11px ${colours.font}`;
    let widest = ctx.measureText('Conservation').width;
    for (const r of rows) widest = Math.max(widest, ctx.measureText(r.seqId).width);
    return Math.round(Math.min(ID_MAX_PX, Math.max(ID_MIN_PX, widest + 14)));
  }, [rows, colours.font]);
  const headerH =
    RULER_PX + (showConsensus ? CONSENSUS_PX : 0) + (showConservation ? CONSERVATION_PX : 0);
  const gridW = Math.max(0, view.w - idWidth);
  const gridH = Math.max(0, view.h - headerH);
  const cw = cellWidth && cellWidth > 0 ? cellWidth : fitCellWidth(gridW, width, 1, 16);
  const ch = ROW_PX;
  const contentW = idWidth + width * cw;
  const contentH = headerH + rows.length * ch;

  // ---- interaction state (refs: a pointer move redraws, it does not re-render)
  const brushRef = useRef<BrushState | null>(null);
  const hoverRef = useRef<PointerCell | null>(null);
  const [tooltip, setTooltip] = useState<PointerCell | null>(null);
  const drawnRef = useRef(false);
  // A new alignment is a new first frame: report it again once drawn.
  useEffect(() => {
    drawnRef.current = false;
  }, [rows]);

  const selectedCols = useMemo(
    () => (selectedRange ? residueRangeToColumnRange(refMap, selectedRange) : null),
    [selectedRange, refMap],
  );
  const highlightCols = useMemo(
    () => (highlight ? residueRangeToColumnRange(refMap, highlight) : null),
    [highlight, refMap],
  );
  const selectedRows = useMemo(
    () => rowIndicesOf(selectedRowKeys, rowIndexById),
    [selectedRowKeys, rowIndexById],
  );
  const highlightRows = useMemo(
    () => rowIndicesOf(highlight?.rowKeys, rowIndexById),
    [highlight, rowIndexById],
  );

  // ---- drawing -------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const el = scrollRef.current;
    if (!canvas || !el || view.w <= 0 || view.h <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, view.h);
    if (!ctx) return;
    const sx = el.scrollLeft;
    const sy = el.scrollTop;
    const [c0, c1] = visibleWindow(sx, gridW, cw, width, 1);
    const [r0, r1] = visibleWindow(sy, gridH, ch, rows.length, 1);
    const colX = (c: number) => idWidth + c * cw - sx;
    const rowY = (r: number) => headerH + r * ch - sy;
    const showLetters = lettersFit(cw, ch);
    const fontPx = Math.max(7, Math.min(12, ch - 3, cw));
    const brush = brushRef.current;
    const hover = hoverRef.current;

    // Column bands shared by the grid and the header.
    const bands: Array<[number, number, string]> = [];
    if (selectedCols) bands.push([selectedCols[0], selectedCols[1], colours.accentFill]);
    if (highlightCols) bands.push([highlightCols[0], highlightCols[1], colours.highlightFill]);
    if (brush && brush.moved) {
      const lo = Math.min(brush.startCol, brush.endCol);
      bands.push([lo, Math.max(brush.startCol, brush.endCol), colours.accentFill]);
    }
    if (hover && hover.col != null && !brush) bands.push([hover.col, hover.col, colours.hoverFill]);

    // Grid area.
    ctx.save();
    ctx.beginPath();
    ctx.rect(idWidth, headerH, gridW, gridH);
    ctx.clip();
    if (cellImage && c1 >= c0 && r1 >= r0) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(
        cellImage,
        c0,
        r0,
        c1 - c0 + 1,
        r1 - r0 + 1,
        colX(c0),
        rowY(r0),
        (c1 - c0 + 1) * cw,
        (r1 - r0 + 1) * ch,
      );
    }
    if (showLetters && r1 >= r0) {
      ctx.font = `${fontPx}px ${colours.monoFont}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (let r = r0; r <= r1; r++) {
        const seq = sequences[r];
        const y = rowY(r) + ch / 2 + 0.5;
        for (let c = c0; c <= c1; c++) {
          const letter = seq[c] ?? '-';
          if (isGap(letter)) {
            ctx.fillStyle = colours.dimmed;
            ctx.fillText('-', colX(c) + cw / 2, y);
            continue;
          }
          const rgb = schemeColour(colourScheme, letter, profiles[c]);
          ctx.fillStyle = rgb ? contrastingText(rgb) : colours.text;
          ctx.fillText(letter, colX(c) + cw / 2, y);
        }
      }
    }
    for (const [a, b, fill] of bands) {
      ctx.fillStyle = fill;
      ctx.fillRect(colX(a), headerH, (b - a + 1) * cw, gridH);
    }
    const ringRow = (r: number, stroke: string) => {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(idWidth + 0.75, rowY(r) + 0.75, Math.min(gridW, width * cw - sx) - 1.5, ch - 1.5);
    };
    for (const r of selectedRows) if (r >= r0 && r <= r1) ringRow(r, colours.accent);
    for (const r of highlightRows) if (r >= r0 && r <= r1) ringRow(r, colours.highlight);
    if (hover && hover.row != null && !brush) {
      ctx.fillStyle = colours.hoverFill;
      ctx.fillRect(idWidth, rowY(hover.row), gridW, ch);
    }
    if (highlightCols) {
      ctx.strokeStyle = colours.highlight;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(colX(highlightCols[0]), headerH, (highlightCols[1] - highlightCols[0] + 1) * cw, gridH);
    }
    ctx.restore();

    // Chain boundaries: a rule down the whole alignment and the chain name
    // at the top of each chain.
    if (chainCols) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(idWidth, 0, gridW, view.h);
      ctx.clip();
      ctx.strokeStyle = colours.dimmed;
      ctx.fillStyle = colours.text;
      ctx.lineWidth = 1;
      ctx.font = `600 10px ${colours.font}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      let prev: string | null = null;
      for (let c = 0; c <= c1; c++) {
        const chainId = chainCols.chain[c];
        if (chainId == null || chainId === prev) continue;
        const boundary = prev !== null;
        prev = chainId;
        if (c < c0 - 1) continue;
        const x = Math.round(colX(c)) + 0.5;
        if (boundary) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, headerH + rows.length * ch - sy);
          ctx.stroke();
        }
        ctx.fillText(chainId, x + 2, 1);
      }
      ctx.restore();
    }

    // Header: ruler, consensus, conservation.
    ctx.save();
    ctx.beginPath();
    ctx.rect(idWidth, 0, gridW, headerH);
    ctx.clip();
    for (const [a, b, fill] of bands) {
      ctx.fillStyle = fill;
      ctx.fillRect(colX(a), 0, (b - a + 1) * cw, headerH);
    }
    const step = rulerStep(cw);
    ctx.font = `10px ${colours.font}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.strokeStyle = colours.dimmed;
    ctx.fillStyle = colours.dimmed;
    ctx.lineWidth = 1;
    for (let c = c0; c <= c1; c++) {
      const res = refMap.colToRes[c];
      if (res < 0) continue;
      const x = Math.round(colX(c) + cw / 2) + 0.5;
      // On a complex the ruler speaks each chain's own numbering.
      const num = chainCols ? chainCols.local[c] : res;
      const first = chainCols ? (chainCols.firstOf.get(chainCols.chain[c] ?? '') ?? 1) : 1;
      if (num % step === 0 || num === first) {
        ctx.beginPath();
        ctx.moveTo(x, RULER_PX - 5);
        ctx.lineTo(x, RULER_PX);
        ctx.stroke();
        ctx.fillText(String(num), x, RULER_PX - 7);
      }
    }
    let y = RULER_PX;
    if (showConsensus) {
      ctx.font = `600 ${fontPx}px ${colours.monoFont}`;
      ctx.textBaseline = 'middle';
      for (let c = c0; c <= c1; c++) {
        const p = profiles[c];
        if (!p?.consensus) continue;
        const rgb = schemeColour(colourScheme, p.consensus, p);
        if (rgb) {
          ctx.fillStyle = rgbCss(rgb, 0.35 + 0.65 * p.consensusFraction);
          ctx.fillRect(colX(c), y + 1, cw, CONSENSUS_PX - 2);
        }
        if (showLetters) {
          ctx.fillStyle = rgb ? contrastingText(rgb) : colours.text;
          ctx.fillText(p.consensus, colX(c) + cw / 2, y + CONSENSUS_PX / 2 + 0.5);
        }
      }
      y += CONSENSUS_PX;
    }
    if (showConservation) {
      ctx.fillStyle = colours.accent;
      const barH = CONSERVATION_PX - 4;
      for (let c = c0; c <= c1; c++) {
        const h = conservation[c] * barH;
        if (h <= 0) continue;
        ctx.fillRect(colX(c) + (cw > 3 ? 0.5 : 0), y + 2 + barH - h, cw > 3 ? cw - 1 : cw, h);
      }
    }
    ctx.restore();

    // Id column.
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, headerH, idWidth, gridH);
    ctx.clip();
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (let r = r0; r <= r1; r++) {
      const ry = rowY(r);
      if (selectedRows.has(r)) {
        ctx.fillStyle = colours.accentFill;
        ctx.fillRect(0, ry, idWidth, ch);
      } else if (hover && hover.row === r) {
        ctx.fillStyle = colours.hoverFill;
        ctx.fillRect(0, ry, idWidth, ch);
      }
      ctx.font = `${r === refIdx ? 600 : 400} 11px ${colours.font}`;
      ctx.fillStyle = highlightRows.has(r) ? colours.highlight : colours.text;
      ctx.fillText(fitText(ctx, rows[r].seqId, idWidth - 10), 4, ry + ch / 2 + 0.5);
    }
    ctx.restore();

    // Header labels (corner) and the dividers.
    ctx.font = `10px ${colours.font}`;
    ctx.fillStyle = colours.dimmed;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('Residue', 4, RULER_PX / 2);
    let ly = RULER_PX;
    if (showConsensus) {
      ctx.fillText('Consensus', 4, ly + CONSENSUS_PX / 2);
      ly += CONSENSUS_PX;
    }
    if (showConservation) ctx.fillText('Conservation', 4, ly + CONSERVATION_PX / 2);
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(idWidth - 0.5, 0);
    ctx.lineTo(idWidth - 0.5, view.h);
    ctx.moveTo(0, headerH - 0.5);
    ctx.lineTo(view.w, headerH - 0.5);
    ctx.stroke();

    if (!drawnRef.current && rows.length > 0) {
      drawnRef.current = true;
      onDrawn?.();
    }
  }, [
    view,
    gridW,
    gridH,
    cw,
    ch,
    width,
    rows,
    sequences,
    idWidth,
    headerH,
    cellImage,
    colourScheme,
    profiles,
    conservation,
    refMap,
    refIdx,
    chainCols,
    colours,
    selectedCols,
    highlightCols,
    selectedRows,
    highlightRows,
    showConsensus,
    showConservation,
    onDrawn,
  ]);

  const requestDraw = useDrawScheduler(draw);

  // ---- follow an incoming selection / highlight ----------------------------
  const followCols = highlightCols ?? selectedCols;
  useEffect(() => {
    const el = scrollRef.current;
    if (!followSelection || !el || !followCols || gridW <= 0) return;
    const next = scrollToReveal(el.scrollLeft, gridW, followCols[0] * cw, (followCols[1] + 1) * cw);
    if (next != null) el.scrollLeft = next;
  }, [followSelection, followCols?.[0], followCols?.[1], cw, gridW]);
  const firstHighlightRow = highlightRows.size ? Math.min(...highlightRows) : null;
  useEffect(() => {
    const el = scrollRef.current;
    if (!followSelection || !el || firstHighlightRow == null || gridH <= 0) return;
    const next = scrollToReveal(el.scrollTop, gridH, firstHighlightRow * ch, (firstHighlightRow + 1) * ch, 0);
    if (next != null) el.scrollTop = next;
  }, [followSelection, firstHighlightRow, ch, gridH]);

  // ---- pointer -------------------------------------------------------------
  const cellAt = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>): PointerCell => {
      const canvas = canvasRef.current;
      const el = scrollRef.current;
      const rect = canvas?.getBoundingClientRect();
      const x = rect ? e.clientX - rect.left : 0;
      const y = rect ? e.clientY - rect.top : 0;
      const sx = el?.scrollLeft ?? 0;
      const sy = el?.scrollTop ?? 0;
      const inGridX = x >= idWidth;
      const inGridY = y >= headerH;
      const colRaw = Math.floor((x - idWidth + sx) / cw);
      const rowRaw = Math.floor((y - headerH + sy) / ch);
      const col = inGridX && colRaw >= 0 && colRaw < width ? colRaw : null;
      const row = inGridY && rowRaw >= 0 && rowRaw < rows.length ? rowRaw : null;
      return { zone: zoneOf(inGridX, inGridY), col, row, x, y };
    },
    [idWidth, headerH, cw, ch, width, rows.length],
  );

  const hoverOf = useCallback(
    (cell: PointerCell): MsaHover | null => {
      if (cell.col == null) return null;
      const seq = cell.row != null ? rows[cell.row] : null;
      return {
        column: cell.col,
        residue: refMap.colToRes[cell.col] >= 0 ? refMap.colToRes[cell.col] : null,
        chain: chainCols ? chainCols.chain[cell.col] : null,
        chainPosition: chainCols && chainCols.local[cell.col] >= 0 ? chainCols.local[cell.col] : null,
        seqId: seq?.seqId ?? null,
        letter: seq ? (seq.sequence[cell.col] ?? '-') : null,
      };
    },
    [rows, refMap, chainCols],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const cell = cellAt(e);
    // A press in the id column or the corner never brushes: `-1` marks it.
    const col = cell.col ?? -1;
    brushRef.current = {
      startCol: col,
      endCol: col,
      x: cell.x,
      y: cell.y,
      moved: false,
      zone: cell.zone,
      row: cell.row,
    };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const cell = cellAt(e);
    const brush = brushRef.current;
    if (brush) {
      const travelled = Math.hypot(cell.x - brush.x, cell.y - brush.y);
      if (!brush.moved && travelled > DRAG_PX && brush.startCol >= 0 && onBrushColumns) {
        brush.moved = true;
      }
      if (brush.moved) {
        const el = scrollRef.current;
        const colRaw = Math.floor((cell.x - idWidth + (el?.scrollLeft ?? 0)) / cw);
        brush.endCol = Math.max(0, Math.min(width - 1, colRaw));
        requestDraw();
        return;
      }
    }
    hoverRef.current = cell;
    setTooltip(cell.col != null || cell.row != null ? cell : null);
    onHoverColumn?.(hoverOf(cell));
    requestDraw();
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const brush = brushRef.current;
    brushRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!brush) return;
    if (brush.moved && onBrushColumns) {
      onBrushColumns(columnRangeToResidueRange(refMap, brush.startCol, brush.endCol));
    } else if ((brush.zone === 'cell' || brush.zone === 'id') && brush.row != null && onClickRow) {
      onClickRow(rows[brush.row].seqId, { shiftKey: e.shiftKey, metaKey: e.metaKey || e.ctrlKey });
    } else if (brush.zone === 'header' && brush.startCol >= 0 && onBrushColumns) {
      const res = refMap.colToRes[brush.startCol];
      const same =
        selectedRange && selectedRange.start === res && (selectedRange.end ?? selectedRange.start) === res;
      onBrushColumns(res < 0 || same ? null : { start: res, end: res });
    } else if (brush.zone === 'corner' && onBrushColumns && selectedRange) {
      onBrushColumns(null);
    }
    requestDraw();
  };

  const onPointerLeave = () => {
    if (brushRef.current) return;
    hoverRef.current = null;
    setTooltip(null);
    onHoverColumn?.(null);
    requestDraw();
  };

  // ---- tooltip -------------------------------------------------------------
  const tip = useMemo(() => {
    if (!tooltip) return null;
    const lines: string[] = [];
    const col = tooltip.col;
    const res = col != null ? refMap.colToRes[col] : -1;
    let where = '';
    if (col != null && res >= 0) {
      where =
        chainCols && chainCols.chain[col] != null
          ? `chain ${chainCols.chain[col]} residue ${chainCols.local[col]}`
          : `reference residue ${res}`;
    }
    if (tooltip.row != null) {
      const row = rows[tooltip.row];
      lines.push(row.seqId + (tooltip.row === refIdx ? ' (reference)' : ''));
      if (col != null) {
        const letter = row.sequence[col] ?? '-';
        lines.push(`${isGap(letter) ? 'gap' : letter} at column ${col + 1}${where ? `, ${where}` : ''}`);
      }
      const identity =
        row.identity ?? (tooltip.row === refIdx ? 1 : percentIdentity(row.sequence, refSeq));
      if (identity != null) lines.push(`Identity ${(identity * 100).toFixed(1)}%`);
      if (row.coverage != null) lines.push(`Coverage ${(row.coverage * 100).toFixed(1)}%`);
    } else if (col != null) {
      const p = profiles[col];
      lines.push(where ? where[0].toUpperCase() + where.slice(1) : `Column ${col + 1} (reference gap)`);
      if (p?.consensus) lines.push(`Consensus ${p.consensus} (${Math.round(p.consensusFraction * 100)}%)`);
      lines.push(`Conservation ${conservation[col].toFixed(2)}`);
    }
    return lines.length ? lines : null;
  }, [tooltip, rows, refIdx, refMap, refSeq, profiles, conservation, chainCols]);

  return (
    <Box
      className="depictio-msa-panel"
      pos="relative"
      style={{ width: '100%', height, minHeight: 0 }}
    >
      <div
        ref={scrollRef}
        onScroll={() => requestDraw()}
        style={{ position: 'absolute', inset: 0, overflow: 'auto' }}
      >
        <div
          style={{
            position: 'relative',
            width: contentW,
            height: contentH,
            minWidth: '100%',
            minHeight: '100%',
          }}
        >
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Sequence alignment, ${rows.length} sequences by ${width} columns`}
            style={{
              position: 'sticky',
              left: 0,
              top: 0,
              display: 'block',
              cursor: onBrushColumns ? 'crosshair' : 'default',
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
            left: Math.min(tooltip.x + 14, Math.max(0, view.w - 200)),
            top: Math.min(tooltip.y + 14, Math.max(0, view.h - 80)),
            maxWidth: 240,
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

export default MsaPanel;
