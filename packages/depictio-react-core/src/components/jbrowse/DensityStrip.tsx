import React, { useEffect, useMemo, useRef, useState } from 'react';
import { SegmentedControl, Text, Tooltip, UnstyledButton, useMantineTheme } from '@mantine/core';

import type { JBrowseCallDensity } from '../../api';
import { paletteHex } from '../../paletteColor';
import {
  availableGroups,
  binAt,
  binOpacity,
  chromLabel,
  chromLocus,
  densityRegions,
  densityRows,
  layoutSlots,
  locusString,
  pixelRuns,
  rowHeightFor,
  rowTops,
  viewMarkers,
  type DensityGroup,
  type DensityRegion,
  type PixelRun,
  type VisibleRegion,
} from './densityBins';
import type { NamedLocusSource } from './locusSources';

interface DensityStripProps {
  data: JBrowseCallDensity | null;
  /** The tile's sources: their colour paints the rows, their columns decide the groupings. */
  sources: NamedLocusSource[];
  /** The regions on screen, to mark the view window. */
  visible: VisibleRegion[];
  /** Pixel width of the whole strip (gutter included). */
  width: number;
  group: DensityGroup;
  onGroupChange: (group: DensityGroup) => void;
  /** `chr:start-end` of the clicked bin (or chromosome). */
  onNavigate: (locus: string) => void;
  /** The assembly's regions, for exact contig lengths (else rebuilt from the bins). */
  regions?: DensityRegion[];
  /** No gutter, header or grouping control: just the heatmap. */
  compact?: boolean;
}

const GUTTER = 84;
const HEADER_HEIGHT = 11;
const SEPARATOR = 1;

const GROUP_LABELS: Record<DensityGroup, string> = {
  source: 'Source',
  sample: 'Sample',
  run: 'Run',
};

interface Hover {
  x: number;
  row: number;
  locus: string;
  count: number;
}

/**
 * A genome-wide density heatmap: chromosomes side by side, one row per source,
 * sample or run, each bin shaded by how many regions fall in it. Click a bin
 * to go there. A single canvas holds the cells (up to 64 rows of a couple of
 * thousand bins); the view window, labels and hover sit on top of it.
 */
const DensityStrip: React.FC<DensityStripProps> = ({
  data,
  sources,
  visible,
  width,
  group,
  onGroupChange,
  onNavigate,
  regions,
  compact,
}) => {
  const theme = useMantineTheme();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const tracks = data?.tracks ?? [];
  const rows = useMemo(() => densityRows(tracks), [tracks]);
  const rowH = rowHeightFor(rows.length);
  const { tops, height: plotH } = useMemo(() => rowTops(rows, rowH), [rows, rowH]);

  const groups = useMemo(() => availableGroups(sources), [sources]);
  const showGroups = !compact && groups.length > 1;
  const truncated = data?.truncated ?? 0;
  const showGutter = !compact && width >= 360;
  const gutter = showGutter ? GUTTER : 0;
  const plotW = Math.max(0, width - gutter);

  const slots = useMemo(
    () => (data ? layoutSlots(densityRegions(data, regions), plotW, SEPARATOR) : []),
    [data, regions, plotW],
  );
  const markers = useMemo(() => viewMarkers(slots, visible), [slots, visible]);
  const headerLabels = useMemo(
    () => (compact ? [] : slots.map((s) => ({ slot: s, label: chromLabel(s) }))),
    [slots, compact],
  );
  const headerH = headerLabels.some((h) => h.label) ? HEADER_HEIGHT : 0;

  const primary = theme.colors[theme.primaryColor]?.[6];
  const colors = useMemo(
    () =>
      rows.map((r) => {
        const name = sources.find((s) => s.name === r.track.source)?.color;
        return paletteHex(theme, name) || primary || 'currentColor';
      }),
    [rows, sources, theme, primary],
  );

  // counts and pixel runs per row and slot, computed once per layout
  const drawn = useMemo(() => {
    if (!data) return [];
    return rows.map((r) => {
      const byChrom = new Map(r.track.chroms.map((c) => [c.refName, c.counts]));
      return slots.map((s) => {
        const counts = byChrom.get(s.refName);
        return { counts, runs: counts ? pixelRuns(counts, s, data.bin_size) : ([] as PixelRun[]) };
      });
    });
  }, [data, rows, slots]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || !data) return;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    canvas.width = Math.round(plotW * dpr);
    canvas.height = Math.round(plotH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, plotW, plotH);
    const h = rowH >= 6 ? rowH - 1 : rowH;
    rows.forEach((_, i) => {
      ctx.fillStyle = colors[i];
      drawn[i].forEach(({ runs }) => {
        for (const run of runs) {
          ctx.globalAlpha = binOpacity(run.count, data.max);
          ctx.fillRect(run.x0, tops[i], run.x1 - run.x0, h);
        }
      });
    });
    ctx.globalAlpha = 1;
  }, [data, drawn, rows, colors, tops, rowH, plotW, plotH]);

  if (!data || !rows.length || !slots.length || width <= 0) {
    return null;
  }

  // Rows between two run separators share one background block per contig.
  const blocks: { top: number; height: number }[] = [];
  rows.forEach((r, i) => {
    const last = blocks[blocks.length - 1];
    if (!r.separatorBefore && last) last.height = tops[i] + rowH - last.top;
    else blocks.push({ top: tops[i], height: rowH });
  });

  const rowAt = (y: number): number => {
    let found = 0;
    for (let i = 0; i < tops.length; i++) if (tops[i] <= y) found = i;
    return found;
  };

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - box.left;
    const hit = binAt(slots, x, data.bin_size);
    if (!hit) {
      setHover(null);
      return;
    }
    const row = rowAt(e.clientY - box.top);
    const counts = drawn[row]?.[slots.indexOf(hit.slot)]?.counts;
    setHover({ x, row, locus: `${hit.refName}:${hit.start}-${hit.end}`, count: counts?.[hit.bin] ?? 0 });
  };

  const onClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const hit = binAt(slots, e.clientX - box.left, data.bin_size);
    if (hit) onNavigate(locusString(hit));
  };

  const hoverRow = hover ? rows[hover.row] : null;
  const label = hoverRow && hover && (
    <div style={{ lineHeight: 1.35 }}>
      <Text size="xs" fw={600}>
        {hoverRow.track.label}
      </Text>
      {hoverRow.track.run && (
        <Text size="xs" c="dimmed">
          Run {hoverRow.track.run}
        </Text>
      )}
      <Text size="xs">{hover.locus}</Text>
      <Text size="xs">
        {hover.count.toLocaleString()} {hover.count === 1 ? 'region' : 'regions'}
      </Text>
    </div>
  );

  // Too many rows for a label each: name the run groups, else just count the tracks.
  const rowLabels = rowH >= 7;
  const runLabels: { name: string; top: number; height: number }[] = [];
  if (showGutter && !rowLabels) {
    rows.forEach((r, i) => {
      const run = r.track.run;
      if (!run) return;
      const last = runLabels[runLabels.length - 1];
      if (last && last.name === run && !r.separatorBefore) last.height = tops[i] + rowH - last.top;
      else runLabels.push({ name: run, top: tops[i], height: rowH });
    });
  }

  return (
    <div
      data-testid="jbrowse-density-strip"
      style={{ width, display: 'flex', flexDirection: 'column', gap: 2, userSelect: 'none' }}
    >
      {(showGroups || truncated > 0) && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          {showGroups ? (
            <SegmentedControl
              size="xs"
              value={group}
              onChange={(v) => onGroupChange(v as DensityGroup)}
              data={groups.map((g) => ({ value: g, label: GROUP_LABELS[g] }))}
              data-testid="jbrowse-density-group"
            />
          ) : (
            <span />
          )}
          {truncated > 0 && (
            <Text size="xs" c="dimmed" title="Tracks past the cap are not drawn" data-testid="jbrowse-density-more">
              +{truncated} more
            </Text>
          )}
        </div>
      )}
      <div style={{ display: 'flex', width }}>
        {showGutter && (
          <div
            style={{
              width: gutter,
              flex: 'none',
              position: 'relative',
              height: headerH + plotH,
              paddingRight: 4,
              boxSizing: 'border-box',
            }}
          >
            {rowLabels &&
              rows.map((r, i) => (
                <div
                  key={i}
                  title={r.track.label}
                  style={{
                    position: 'absolute',
                    top: headerH + tops[i],
                    height: rowH,
                    left: 0,
                    right: 4,
                    fontSize: Math.min(10, rowH + 1),
                    lineHeight: `${rowH}px`,
                    textAlign: 'right',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    color: 'var(--mantine-color-dimmed)',
                  }}
                >
                  {r.track.label}
                </div>
              ))}
            {!rowLabels &&
              (runLabels.length > 0 ? (
                runLabels.map((l) => (
                  <div
                    key={`${l.name}-${l.top}`}
                    title={`Run ${l.name}`}
                    style={{
                      position: 'absolute',
                      top: headerH + l.top,
                      height: l.height,
                      left: 0,
                      right: 4,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      fontSize: 9,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      color: 'var(--mantine-color-dimmed)',
                    }}
                  >
                    {l.height >= 9 ? l.name : ''}
                  </div>
                ))
              ) : (
                <div
                  style={{
                    position: 'absolute',
                    top: headerH,
                    height: plotH,
                    left: 0,
                    right: 4,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    fontSize: 9,
                    color: 'var(--mantine-color-dimmed)',
                  }}
                >
                  {rows.length} tracks
                </div>
              ))}
          </div>
        )}
        <div style={{ width: plotW, flex: 'none' }}>
          {headerH > 0 && (
            <div style={{ position: 'relative', height: headerH, width: plotW }}>
              {headerLabels.map(
                ({ slot, label: name }) =>
                  name && (
                    <UnstyledButton
                      key={slot.refName}
                      title={`${slot.refName}: whole chromosome`}
                      onClick={() => onNavigate(locusString(chromLocus(slot)))}
                      data-testid={`jbrowse-density-chrom-${slot.refName}`}
                      style={{
                        position: 'absolute',
                        left: slot.x,
                        width: slot.width,
                        height: headerH,
                        lineHeight: `${headerH}px`,
                        fontSize: 9,
                        textAlign: 'center',
                        overflow: 'hidden',
                        whiteSpace: 'nowrap',
                        color: 'var(--mantine-color-dimmed)',
                      }}
                    >
                      {name}
                    </UnstyledButton>
                  ),
              )}
            </div>
          )}
          <div style={{ position: 'relative', width: plotW, height: plotH }}>
            <svg
              width={plotW}
              height={plotH}
              style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
              aria-hidden
            >
              {blocks.flatMap((b) =>
                slots.map((s) => (
                  <rect
                    key={`${b.top}-${s.refName}`}
                    x={s.x}
                    y={b.top}
                    width={s.width}
                    height={b.height}
                    style={{ fill: 'var(--mantine-color-default-hover)' }}
                  />
                )),
              )}
            </svg>
            <canvas
              ref={canvasRef}
              style={{ position: 'absolute', inset: 0, width: plotW, height: plotH }}
            />
            <svg
              width={plotW}
              height={plotH}
              style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
              aria-hidden
            >
              {markers.map((m, i) => (
                <rect
                  key={i}
                  x={m.x}
                  y={0.5}
                  width={m.width}
                  height={Math.max(0, plotH - 1)}
                  data-testid="jbrowse-density-view"
                  style={{
                    fill: 'var(--mantine-primary-color-filled)',
                    fillOpacity: 0.15,
                    stroke: 'var(--mantine-primary-color-filled)',
                    strokeWidth: 1,
                  }}
                />
              ))}
            </svg>
            <Tooltip.Floating label={label} disabled={!hover} offset={12} multiline>
              <div
                data-testid="jbrowse-density-plot"
                onMouseMove={onMove}
                onMouseLeave={() => setHover(null)}
                onClick={onClick}
                style={{
                  position: 'absolute',
                  inset: 0,
                  cursor: hover ? 'pointer' : 'default',
                }}
              />
            </Tooltip.Floating>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DensityStrip;
