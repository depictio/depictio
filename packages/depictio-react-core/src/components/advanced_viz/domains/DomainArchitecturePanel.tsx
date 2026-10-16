import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { contrastingText } from '../../../utils/colorScale';
import {
  fitText,
  prepareCanvas,
  roundRectPath,
  rulerStep,
  scrollToReveal,
} from '../protein/canvas';
import { useDrawScheduler, useViewSize } from '../protein/canvasHooks';
import { cssToRgb, panelColours, type PanelColours } from '../protein/panelTheme';
import type { ZoomSyncHandle } from '../../../highlight/zoomSync';
import { useModifierWheelZoom } from '../protein/useWheelZoom';
import { uniformAxis } from '../protein/zoomAxis';
import {
  domainAt,
  domainTooltip,
  clampLabelWidth,
  labelColumnPx,
  lengthGutter,
  lengthLabel,
  LENGTH_LABEL_GAP_PX,
  partialEdges,
  pxPerResidue as scalePxPerResidue,
  residueAt,
  residueX,
  RESIDUE_WIDTH_MAX_PX,
  rowAt,
  rowHeight,
  rowOffsets,
  rowWindow,
  trackLayout,
  visibleResidues,
  type ArchitectureGroup,
  type DomainHit,
  type PanelRow,
  type ProteinArch,
  type RowGeometry,
} from './architecture';
import { domainShapePath, outlineDash } from './shapes';

/** Vertical padding of a row, one domain lane, a note row; CSS px. */
const GEOMETRY: RowGeometry = { padPx: 5, lanePx: 16, notePx: 22 };
const DOMAIN_PX = 12;
const BACKBONE_PX = 3;
const AXIS_PX = 20;
const INDENT_PX = 14;
const CHEVRON_PX = 16;
const RIGHT_PAD_PX = 8;
/** Narrowest domain that carries its label. */
const LABEL_MIN_DOMAIN_PX = 26;

export interface DomainHoverInfo {
  protein: ProteinArch;
  hit: DomainHit;
}

/** A residue span on one protein (a pick, or a hover from another tile). */
export interface EntitySpan {
  entity: string;
  start: number;
  end: number;
}

export interface DomainArchitecturePanelProps {
  rows: PanelRow[];
  scale: 'shared' | 'per_protein';
  /** Pixels per residue of the longest protein; 0 fits the tracks to the tile.
   *  Wider than the tile, the tracks scroll sideways under a fixed label column. */
  residueWidth?: number;
  /** Receives a whole-pixel width from Ctrl / Cmd + wheel. Omit to disable the zoom. */
  onResidueWidthChange?: (px: number) => void;
  /** Zoom sync with the view's other residue tiles (on the shared scale only). */
  zoomSync?: ZoomSyncHandle | null;
  partialCoverage: number;
  colourOf: (hit: DomainHit) => string;
  /** Column of the E-value, to name it in the tooltip. */
  evalueColumn?: string | null;
  /** Entities a selection names (picked here or elsewhere): their rows are ringed. */
  pickedEntities: ReadonlySet<string>;
  /** Group rows this tile selected as a whole. */
  selectedGroups: ReadonlySet<string>;
  /** The residue range in force, shaded on its protein's row. */
  pickedRange: EntitySpan | null;
  /** The domain this tile picked, outlined. */
  pickedDomain: EntitySpan | null;
  /** A hover from another tile: its row ringed, its residues shaded. */
  highlight: EntitySpan | null;
  /** Row key to bring into view (a pick made elsewhere). */
  revealKey: string | null;
  onHoverDomain?: (hover: DomainHoverInfo | null) => void;
  onClickDomain?: (protein: ProteinArch, hit: DomainHit) => void;
  onClickProtein?: (protein: ProteinArch) => void;
  onClickGroup?: (group: ArchitectureGroup) => void;
  onToggleGroup: (key: string) => void;
  onDrawn?: () => void;
}

type Zone = 'header' | 'label' | 'chevron' | 'track' | 'none';

interface PointerHit {
  x: number;
  y: number;
  row: number;
  zone: Zone;
  /** Index into the drawn protein's domains, or -1. */
  domain: number;
  residue: number | null;
}

/** The protein a row draws: its own, or its group's representative. */
function drawnProtein(row: PanelRow | undefined): ProteinArch | null {
  if (!row) return null;
  if (row.kind === 'protein') return row.protein;
  if (row.kind === 'group') return row.group.representative;
  return null;
}

function laneCentre(rowTop: number, lane: number): number {
  return rowTop + GEOMETRY.padPx + lane * GEOMETRY.lanePx + GEOMETRY.lanePx / 2;
}

/** Collapsed (pointing right) or expanded (pointing down) disclosure triangle. */
function drawChevron(
  ctx: CanvasRenderingContext2D,
  x: number,
  cy: number,
  open: boolean,
  fill: string,
) {
  ctx.fillStyle = fill;
  ctx.beginPath();
  if (open) {
    ctx.moveTo(x, cy - 2.5);
    ctx.lineTo(x + 8, cy - 2.5);
    ctx.lineTo(x + 4, cy + 2.5);
  } else {
    ctx.moveTo(x + 1.5, cy - 4);
    ctx.lineTo(x + 6.5, cy);
    ctx.lineTo(x + 1.5, cy + 4);
  }
  ctx.closePath();
  ctx.fill();
}

/**
 * Protein domain architectures on one 2D canvas: one row per protein (or per
 * architecture group, drawn with its representative), a backbone of the
 * protein's length, the domains as rounded shapes with a zigzag edge where the
 * HMM match is partial, overlapping domains in sub-lanes.
 *
 * Rows are virtualised (a sticky canvas in a scroll spacer; only the rows in
 * view plus an overscan are drawn, found by binary search on their offsets),
 * so thousands of proteins scroll smoothly. Controlled: the caller resolves
 * picks and hovers and passes them back in.
 */
const DomainArchitecturePanel: React.FC<DomainArchitecturePanelProps> = ({
  rows,
  scale,
  residueWidth = 0,
  onResidueWidthChange,
  zoomSync = null,
  partialCoverage,
  colourOf,
  evalueColumn,
  pickedEntities,
  selectedGroups,
  pickedRange,
  pickedDomain,
  highlight,
  revealKey,
  onHoverDomain,
  onClickDomain,
  onClickProtein,
  onClickGroup,
  onToggleGroup,
  onDrawn,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const colours: PanelColours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const view = useViewSize(scrollRef);

  // ---- layout ------------------------------------------------------------
  const heights = useMemo(() => rows.map((r) => rowHeight(r, GEOMETRY)), [rows]);
  const offsets = useMemo(() => rowOffsets(heights), [heights]);
  const contentH = AXIS_PX + offsets[offsets.length - 1];
  const sharedLength = useMemo(
    () => rows.reduce((m, r) => Math.max(m, drawnProtein(r)?.length ?? 0), 1),
    [rows],
  );
  const widestLabel = useMemo(() => {
    if (typeof document === 'undefined') return Infinity;
    const ctx = document.createElement('canvas').getContext('2d');
    if (!ctx) return Infinity;
    let widest = 0;
    // Measuring every label of a proteome is cheap, but not free: the first
    // few thousand rows decide the column as well as all of them would.
    for (const r of rows.slice(0, 5000)) {
      if (r.kind === 'protein') {
        ctx.font = `11px ${colours.font}`;
        widest = Math.max(
          widest,
          ctx.measureText(r.protein.entity).width + (r.indent ? INDENT_PX : 0),
        );
      } else if (r.kind === 'group') {
        ctx.font = `600 10px ${colours.font}`;
        const pill = ctx.measureText(r.group.members.length.toLocaleString()).width + 10;
        ctx.font = `10px ${colours.font}`;
        widest = Math.max(
          widest,
          CHEVRON_PX + pill + 6 + ctx.measureText(r.group.representative.entity).width,
        );
      }
    }
    return widest;
  }, [rows, colours.font]);
  // Capped to a share of the tile, so one long identifier leaves the tracks room.
  const autoLabelWidth = useMemo(() => labelColumnPx(widestLabel, view.w), [widestLabel, view.w]);
  // A width dragged by hand replaces the automatic one for the session; the
  // divider's double click gives the automatic one back.
  const [labelOverride, setLabelOverride] = useState<number | null>(null);
  const labelWidth =
    labelOverride == null ? autoLabelWidth : clampLabelWidth(labelOverride, view.w);
  // The longest backbone ends at the track's end (every one does on the
  // per-protein scale), so its length label needs a gutter of its own: the
  // widest label's text, measured as it is drawn.
  const gutterPx = useMemo(() => {
    const text = lengthLabel(sharedLength);
    let width = text.length * 6;
    if (typeof document !== 'undefined') {
      const ctx = document.createElement('canvas').getContext('2d');
      if (ctx) {
        ctx.font = `10px ${colours.font}`;
        width = ctx.measureText(text).width;
      }
    }
    return lengthGutter(width);
  }, [sharedLength, colours.font]);
  const track = useMemo(
    () =>
      trackLayout(view.w, labelWidth, {
        rightPadPx: RIGHT_PAD_PX,
        gutterPx,
        residueWidth,
        sharedLength,
      }),
    [view.w, labelWidth, gutterPx, residueWidth, sharedLength],
  );
  const trackX = track.x;
  const trackW = track.w;
  // The width the longest protein is drawn at, whether fitted or chosen.
  const renderedPpr = scalePxPerResidue(trackW, 'shared', sharedLength, sharedLength);
  // The fitted track, for zoom sync: its width per residue, and the px at its
  // right (length labels, pad) that show no residue.
  const fitted = useMemo(
    () =>
      trackLayout(view.w, labelWidth, {
        rightPadPx: RIGHT_PAD_PX,
        gutterPx,
        residueWidth: 0,
        sharedLength,
      }),
    [view.w, labelWidth, gutterPx, sharedLength],
  );
  useModifierWheelZoom(scrollRef, {
    value: renderedPpr,
    setValue: onResidueWidthChange,
    min: 1,
    max: RESIDUE_WIDTH_MAX_PX,
    gutter: trackX,
    // On the per-protein scale a residue sits somewhere else on every row.
    sync:
      zoomSync && scale === 'shared'
        ? {
            ...zoomSync,
            // Residue coordinate 0 here is the start of residue 1.
            axis: uniformAxis(1, renderedPpr),
            fit: scalePxPerResidue(fitted.w, 'shared', sharedLength, sharedLength),
            requested: residueWidth > 0 ? residueWidth : 0,
            ready: sharedLength > 0 && view.w > 0,
            trailing: Math.max(0, view.w - fitted.x - fitted.w),
          }
        : null,
  });
  const gridH = Math.max(0, view.h - AXIS_PX);
  const pxPerResidue = useCallback(
    (p: ProteinArch) => scalePxPerResidue(trackW, scale, p.length, sharedLength),
    [trackW, scale, sharedLength],
  );

  // Rows ringed by a pick (accent) or a hover from elsewhere (highlight). A
  // group row stands for its members.
  const ringed = useMemo(() => {
    const picked = new Set<number>();
    const hovered = new Set<number>();
    const pickedEntity = pickedRange?.entity ?? null;
    rows.forEach((r, i) => {
      if (r.kind === 'protein') {
        const e = r.protein.entity;
        if (pickedEntities.has(e) || pickedEntity === e) picked.add(i);
        if (highlight?.entity === e) hovered.add(i);
      } else if (r.kind === 'group') {
        if (selectedGroups.has(r.key)) picked.add(i);
        for (const m of r.group.members) {
          if (pickedEntities.has(m.entity) || pickedEntity === m.entity) picked.add(i);
          if (highlight?.entity === m.entity) hovered.add(i);
        }
      }
    });
    return { picked, hovered };
  }, [rows, pickedEntities, selectedGroups, pickedRange, highlight]);

  // ---- interaction state (refs: a pointer move redraws, it does not re-render)
  const hoverRef = useRef<PointerHit | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  const lastHoverKey = useRef<string | null>(null);
  const drawnRef = useRef(false);
  useEffect(() => {
    drawnRef.current = false;
  }, [rows]);

  // ---- drawing -----------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const el = scrollRef.current;
    if (!canvas || !el || view.w <= 0 || view.h <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, view.h);
    if (!ctx) return;
    const sy = el.scrollTop;
    // Residue 0 of every track, scrolled; the label column stays put.
    const originX = trackX - el.scrollLeft;
    const [r0, r1] = rowWindow(offsets, sy, gridH, 2);
    const hover = hoverRef.current;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, AXIS_PX, view.w, gridH);
    ctx.clip();
    for (let r = r0; r <= r1; r++) {
      const row = rows[r];
      const top = AXIS_PX + offsets[r] - sy;
      const h = heights[r];
      const isHovered = hover?.row === r;

      if (row.kind === 'note') {
        ctx.font = `italic 11px ${colours.font}`;
        ctx.fillStyle = colours.dimmed;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(fitText(ctx, row.text, view.w - 16), 8, top + h / 2 + 0.5);
        continue;
      }
      const protein = drawnProtein(row)!;
      const isPicked = ringed.picked.has(r);
      const isLit = ringed.hovered.has(r);

      // Label column.
      if (isPicked) {
        ctx.fillStyle = colours.accentFill;
        ctx.fillRect(0, top, labelWidth, h);
      } else if (isHovered && hover?.zone !== 'track') {
        ctx.fillStyle = colours.hoverFill;
        ctx.fillRect(0, top, labelWidth, h);
      }
      const cy = laneCentre(top, 0);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      if (row.kind === 'group') {
        drawChevron(ctx, 4, cy, row.expanded, colours.dimmed);
        const count = row.group.members.length.toLocaleString();
        ctx.font = `600 10px ${colours.font}`;
        const pillW = ctx.measureText(count).width + 10;
        roundRectPath(ctx, CHEVRON_PX, cy - 7, pillW, 14, 7);
        ctx.fillStyle = colours.accentFill;
        ctx.fill();
        ctx.fillStyle = colours.accent;
        ctx.textAlign = 'center';
        ctx.fillText(count, CHEVRON_PX + pillW / 2, cy + 0.5);
        ctx.textAlign = 'left';
        ctx.font = `10px ${colours.font}`;
        ctx.fillStyle = colours.dimmed;
        const x = CHEVRON_PX + pillW + 6;
        ctx.fillText(fitText(ctx, protein.entity, labelWidth - x - 4), x, cy + 0.5);
      } else {
        const x = 4 + (row.indent ? INDENT_PX : 0);
        ctx.font = `${isPicked ? 600 : 400} 11px ${colours.font}`;
        ctx.fillStyle = isLit ? colours.highlight : colours.text;
        ctx.fillText(fitText(ctx, protein.entity, labelWidth - x - 4), x, cy + 0.5);
      }

      // Track: shading, backbone, domains. Clipped to the right of the label
      // column, which a scrolled track passes under.
      ctx.save();
      ctx.beginPath();
      ctx.rect(labelWidth, top, Math.max(0, view.w - labelWidth), h);
      ctx.clip();
      const ppr = pxPerResidue(protein);
      const X = (pos: number) => residueX(originX, ppr, pos);
      const shade = (span: EntitySpan | null, fill: string) => {
        if (!span || span.entity !== protein.entity) return;
        const a = Math.max(0, Math.min(span.start, span.end) - 1);
        const b = Math.min(protein.length, Math.max(span.start, span.end));
        if (b <= a) return;
        ctx.fillStyle = fill;
        ctx.fillRect(X(a), top + 1, Math.max(1.5, X(b) - X(a)), h - 2);
      };
      shade(pickedRange, colours.accentFill);
      shade(highlight, colours.highlightFill);

      for (let lane = 1; lane < protein.laneCount; lane++) {
        const ly = Math.round(laneCentre(top, lane)) + 0.5;
        ctx.strokeStyle = colours.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(X(0), ly);
        ctx.lineTo(X(protein.length), ly);
        ctx.stroke();
      }
      roundRectPath(
        ctx,
        X(0),
        cy - BACKBONE_PX / 2,
        Math.max(1, X(protein.length) - X(0)),
        BACKBONE_PX,
        BACKBONE_PX / 2,
      );
      ctx.fillStyle = colours.dimmed;
      ctx.fill();

      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const hoveredDomain = isHovered && hover?.zone === 'track' ? hover.domain : -1;
      protein.domains.forEach((d, i) => {
        const lane = protein.lanes[i];
        const dy = laneCentre(top, lane) - DOMAIN_PX / 2;
        const x0 = X(d.start - 1);
        const w = Math.max(2, X(d.end) - x0);
        const edges = partialEdges(d, partialCoverage);
        const fill = colourOf(d);
        domainShapePath(ctx, {
          x: x0,
          y: dy,
          w,
          h: DOMAIN_PX,
          radius: 4,
          left: edges.left,
          right: edges.right,
        });
        ctx.fillStyle = fill;
        ctx.fill();
        const picked =
          pickedDomain != null &&
          pickedDomain.entity === protein.entity &&
          pickedDomain.start === d.start &&
          pickedDomain.end === d.end;
        if (edges.unknown || picked || i === hoveredDomain) {
          ctx.setLineDash(picked || i === hoveredDomain ? [] : outlineDash(edges.unknown));
          ctx.strokeStyle = picked ? colours.accent : colours.text;
          ctx.lineWidth = picked ? 2 : 1;
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (w >= LABEL_MIN_DOMAIN_PX) {
          const text = fitText(ctx, d.label, w - 8);
          if (text) {
            ctx.fillStyle = contrastingText(cssToRgb(fill));
            ctx.fillText(text, x0 + w / 2, dy + DOMAIN_PX / 2 + 0.5);
          }
        }
      });

      // The length past the end of a backbone, in the gutter the track leaves.
      ctx.font = `10px ${colours.font}`;
      ctx.textAlign = 'left';
      const lengthText = lengthLabel(protein.length);
      const endX = X(protein.length) + LENGTH_LABEL_GAP_PX;
      if (endX + ctx.measureText(lengthText).width <= view.w - 2) {
        ctx.fillStyle = colours.dimmed;
        ctx.fillText(lengthText, endX, cy + 0.5);
      }
      ctx.restore();

      if (isPicked || isLit) {
        ctx.strokeStyle = isLit ? colours.highlight : colours.accent;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(0.75, top + 0.75, view.w - 1.5, h - 1.5);
      }
    }
    ctx.restore();

    // Axis header, over the rows.
    ctx.clearRect(0, 0, view.w, AXIS_PX);
    ctx.font = `10px ${colours.font}`;
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = colours.dimmed;
    ctx.textAlign = 'left';
    ctx.fillText(scale === 'shared' ? 'Residue' : 'Protein', 4, AXIS_PX - 6);
    if (scale === 'shared') {
      const ppr = scalePxPerResidue(trackW, 'shared', sharedLength, sharedLength);
      const step = rulerStep(ppr, 56);
      ctx.strokeStyle = colours.dimmed;
      ctx.lineWidth = 1;
      ctx.textAlign = 'center';
      // Only the ticks in view: a wide track holds far more than the tile shows.
      const [seen0, seen1] = visibleResidues(originX, ppr, labelWidth, view.w, sharedLength);
      ctx.save();
      ctx.beginPath();
      ctx.rect(labelWidth, 0, Math.max(0, view.w - labelWidth), AXIS_PX);
      ctx.clip();
      for (let t = Math.max(1, Math.floor(seen0 / step)) * step; t <= seen1 + step; t += step) {
        if (t > sharedLength) break;
        const x = Math.round(residueX(originX, ppr, t - 0.5)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, AXIS_PX - 4);
        ctx.lineTo(x, AXIS_PX);
        ctx.stroke();
        ctx.fillText(t.toLocaleString(), x, AXIS_PX - 6);
      }
      ctx.restore();
    } else {
      ctx.fillText('Each protein drawn to its own length', trackX, AXIS_PX - 6);
    }
    ctx.strokeStyle = colours.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, AXIS_PX - 0.5);
    ctx.lineTo(view.w, AXIS_PX - 0.5);
    ctx.moveTo(labelWidth - 0.5, AXIS_PX);
    ctx.lineTo(labelWidth - 0.5, Math.min(view.h, contentH - sy));
    ctx.stroke();

    if (!drawnRef.current && rows.length > 0) {
      drawnRef.current = true;
      onDrawn?.();
    }
  }, [
    view,
    offsets,
    heights,
    gridH,
    rows,
    ringed,
    colours,
    labelWidth,
    trackX,
    trackW,
    pxPerResidue,
    pickedRange,
    highlight,
    pickedDomain,
    partialCoverage,
    colourOf,
    scale,
    sharedLength,
    contentH,
    onDrawn,
  ]);

  const requestDraw = useDrawScheduler(draw);

  // ---- follow a pick made elsewhere ----------------------------------------
  const lastRevealed = useRef<string | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!revealKey) {
      lastRevealed.current = null;
      return;
    }
    if (!el || gridH <= 0 || lastRevealed.current === revealKey) return;
    const i = rows.findIndex((r) => r.key === revealKey);
    if (i < 0) return;
    lastRevealed.current = revealKey;
    const next = scrollToReveal(el.scrollTop, gridH, offsets[i], offsets[i + 1], 0);
    if (next != null) el.scrollTop = next;
  }, [revealKey, rows, offsets, gridH]);

  // ---- pointer -------------------------------------------------------------
  const hitAt = useCallback(
    (
      e: React.PointerEvent<HTMLCanvasElement> | React.MouseEvent<HTMLCanvasElement>,
    ): PointerHit => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const x = rect ? e.clientX - rect.left : 0;
      const y = rect ? e.clientY - rect.top : 0;
      const none: PointerHit = { x, y, row: -1, zone: 'none', domain: -1, residue: null };
      if (y < AXIS_PX) return { ...none, zone: 'header' };
      const sy = scrollRef.current?.scrollTop ?? 0;
      const r = rowAt(offsets, y - AXIS_PX + sy);
      if (r < 0) return none;
      const row = rows[r];
      const protein = drawnProtein(row);
      if (!protein) return { ...none, row: r };
      if (x < labelWidth) {
        return {
          ...none,
          row: r,
          zone: row.kind === 'group' && x < CHEVRON_PX ? 'chevron' : 'label',
        };
      }
      const ppr = pxPerResidue(protein);
      const pos = residueAt(trackX - (scrollRef.current?.scrollLeft ?? 0), ppr, x);
      const yIn = y - AXIS_PX + sy - offsets[r] - GEOMETRY.padPx;
      const lane = Math.floor(yIn / GEOMETRY.lanePx);
      const domain =
        lane >= 0 && lane < protein.laneCount ? domainAt(protein, lane, pos, 2 / ppr) : -1;
      const residue = pos >= 0 && pos <= protein.length ? Math.max(1, Math.ceil(pos)) : null;
      return { x, y, row: r, zone: 'track', domain, residue };
    },
    [offsets, rows, labelWidth, pxPerResidue, trackX],
  );

  const tooltipLines = useCallback(
    (hit: PointerHit): string[] | null => {
      const row = rows[hit.row];
      const protein = drawnProtein(row);
      if (!row || !protein) return null;
      if (hit.zone === 'track' && hit.domain >= 0) {
        const d = protein.domains[hit.domain];
        const lines = domainTooltip(d, partialEdges(d, partialCoverage), { evalueColumn });
        lines.splice(1, 0, `Protein ${protein.entity} (${protein.length.toLocaleString()} aa)`);
        if (row.kind === 'group')
          lines.push(
            `On the representative of ${row.group.members.length.toLocaleString()} proteins`,
          );
        return lines;
      }
      if (row.kind === 'group') {
        const n = row.group.members.length;
        return [
          row.group.architecture || '(no domain)',
          `${n.toLocaleString()} protein${n === 1 ? '' : 's'}`,
          `Representative ${protein.entity} (${protein.length.toLocaleString()} aa, median length)`,
          hit.zone === 'chevron' || !onClickGroup
            ? row.expanded
              ? 'Click to hide the proteins'
              : 'Click to list the proteins'
            : 'Click to select these proteins',
        ];
      }
      const lines = [
        protein.entity,
        `${protein.length.toLocaleString()} aa${protein.lengthKnown ? '' : ' (to the last domain end)'}`,
        `${protein.domains.length} domain${protein.domains.length === 1 ? '' : 's'}: ${protein.architecture}`,
      ];
      if (hit.zone === 'track' && hit.residue != null) lines.splice(1, 0, `Residue ${hit.residue}`);
      if (hit.zone === 'label' && onClickProtein) lines.push('Click to pick the whole protein');
      return lines;
    },
    [rows, partialCoverage, evalueColumn, onClickGroup, onClickProtein],
  );

  const clickable = useCallback(
    (hit: PointerHit): boolean => {
      const row = rows[hit.row];
      if (!row || row.kind === 'note') return false;
      if (row.kind === 'group') return hit.zone !== 'header' && hit.zone !== 'none';
      if (hit.zone === 'label') return Boolean(onClickProtein);
      return hit.zone === 'track' && hit.domain >= 0 && Boolean(onClickDomain);
    },
    [rows, onClickProtein, onClickDomain],
  );

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const hit = hitAt(e);
    hoverRef.current = hit;
    const lines = hit.row >= 0 ? tooltipLines(hit) : null;
    setTooltip(lines ? { x: hit.x, y: hit.y, lines } : null);
    e.currentTarget.style.cursor = clickable(hit) ? 'pointer' : 'default';
    const protein = drawnProtein(rows[hit.row]);
    const domain =
      protein && hit.zone === 'track' && hit.domain >= 0 ? protein.domains[hit.domain] : null;
    const key = domain && protein ? `${protein.entity}|${hit.domain}` : null;
    if (key !== lastHoverKey.current) {
      lastHoverKey.current = key;
      onHoverDomain?.(domain && protein ? { protein, hit: domain } : null);
    }
    requestDraw();
  };

  // Leaving the canvas, or scrolling under a still pointer: what was under it
  // is gone.
  const clearHover = () => {
    hoverRef.current = null;
    setTooltip(null);
    if (lastHoverKey.current !== null) {
      lastHoverKey.current = null;
      onHoverDomain?.(null);
    }
    requestDraw();
  };

  // A new width moves every domain under a still pointer: forget the hover
  // (and its tooltip) until the next move.
  const lastWidth = useRef(residueWidth);
  useEffect(() => {
    if (lastWidth.current === residueWidth) return;
    lastWidth.current = residueWidth;
    clearHover();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [residueWidth]);

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const hit = hitAt(e);
    const row = rows[hit.row];
    if (!row || row.kind === 'note') return;
    // The tooltip described the state before the click; the next move redraws it.
    setTooltip(null);
    if (row.kind === 'group') {
      if (hit.zone === 'chevron' || !onClickGroup) onToggleGroup(row.key);
      else onClickGroup(row.group);
    } else if (hit.zone === 'label') {
      onClickProtein?.(row.protein);
    } else if (hit.zone === 'track' && hit.domain >= 0) {
      onClickDomain?.(row.protein, row.protein.domains[hit.domain]);
    }
    requestDraw();
  };

  const dragLabel = useRef<{ x0: number; w0: number } | null>(null);
  const onDividerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragLabel.current = { x0: e.clientX, w0: labelWidth };
    clearHover();
  };
  const onDividerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = dragLabel.current;
    if (d) setLabelOverride(clampLabelWidth(d.w0 + e.clientX - d.x0, view.w));
  };
  const onDividerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragLabel.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return (
    <Box
      className="depictio-domain-architecture-panel"
      pos="relative"
      style={{ width: '100%', height: '100%', minHeight: 0 }}
    >
      <div
        ref={scrollRef}
        onScroll={() => (hoverRef.current ? clearHover() : requestDraw())}
        style={{ position: 'absolute', inset: 0, overflowX: 'auto', overflowY: 'auto' }}
      >
        <div
          style={{
            position: 'relative',
            width: track.scrolls ? track.contentW : '100%',
            height: contentH,
            minHeight: '100%',
          }}
        >
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Domain architectures, ${rows.length} rows`}
            style={{ position: 'sticky', left: 0, top: 0, display: 'block', touchAction: 'pan-x pan-y' }}
            onPointerMove={onPointerMove}
            onPointerLeave={clearHover}
            onClick={onClick}
          />
        </div>
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the label column (double click to reset)"
        title="Drag to resize the labels, double click to reset"
        onPointerDown={onDividerDown}
        onPointerMove={onDividerMove}
        onPointerUp={onDividerUp}
        onPointerCancel={onDividerUp}
        onDoubleClick={() => setLabelOverride(null)}
        style={{
          position: 'absolute',
          top: AXIS_PX,
          bottom: 0,
          left: labelWidth - 3,
          width: 6,
          cursor: 'col-resize',
          touchAction: 'none',
          zIndex: 1,
        }}
      />
      {tooltip ? (
        <Paper
          withBorder
          shadow="sm"
          p={6}
          style={{
            position: 'absolute',
            pointerEvents: 'none',
            zIndex: 2,
            left: Math.min(tooltip.x + 14, Math.max(0, view.w - 280)),
            top: Math.min(tooltip.y + 14, Math.max(0, view.h - 24 - tooltip.lines.length * 18)),
            maxWidth: 280,
          }}
        >
          {tooltip.lines.map((line, i) => (
            <Text key={i} size="xs" fw={i === 0 ? 600 : 400} lineClamp={i === 0 ? 1 : 2}>
              {line}
            </Text>
          ))}
        </Paper>
      ) : null}
    </Box>
  );
};

export default DomainArchitecturePanel;
