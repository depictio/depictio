import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Group,
  Paper,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import {
  VizControlGroup,
  VizNumberInput,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { mantineCategoricalPalette, resolveCategoricalPalette, stableColorMap } from '../../colors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersExcludingOwn,
  hasOwnSelection,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  angleAt,
  arcPath,
  ASSEMBLY_NAMES,
  buildRing,
  chordPath,
  chordStrokeWidth,
  chromSizesFor,
  formatBp,
  linkSummary,
  parseChordRows,
  polarPoint,
  prepareLinks,
  ticksFor,
  tickStepFor,
  type ChordLink,
} from './genome_chord/chordLayout';
import { plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `GenomeChordConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface GenomeChordConfig {
  chrom_a_col: string;
  pos_a_col: string;
  chrom_b_col: string;
  pos_b_col: string;
  label_col?: string | null;
  weight_col?: string | null;
  category_col?: string | null;
  sample_col?: string | null;
  assembly?: string | null;
  max_links?: number;
  min_weight?: number | null;
  colour_by?: 'category' | 'chrom_a' | 'none';
  show_labels?: boolean;
  intra_chromosomal?: boolean;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GenomeChordConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// One row is one link and `max_links` below is this renderer's own guard on how
// many it draws, so the server sends the frame whole
// (`KIND_SAMPLING_POLICY["genome_chord"] == "none"`). A random subset of
// breakpoint pairs would silently drop exactly the rare translocations the
// picture exists to show.
const GENOME_CHORD_VIZ_KIND: AdvancedVizKind = 'genome_chord';

// A fixed drawing box scaled by `preserveAspectRatio`, so the ring keeps its
// proportions in any tile without the renderer measuring its own container.
const VIEW = 1000;
const CENTRE = VIEW / 2;
const R_BAND_OUTER = 362;
const R_BAND_INNER = 348;
// Ticks sit outside the band, where nothing else is drawn: inside they would lie
// across the chords, which start at the band's inner edge.
const R_TICK_OUTER = 369;
const R_CHORD = 348;
const R_TICK_LABEL = 332;
const R_LABEL = 380;

const CHORD_MIN_WIDTH = 1.2;
const CHORD_MAX_WIDTH = 9;
const CHORD_OPACITY = 0.55;
const CHORD_DIM_OPACITY = 0.12;
// Below this angular width a chromosome band has no room for its position ticks
// to be read, so it gets the marks without the numbers. An eighth of the circle
// is what it takes: a whole human genome puts no chromosome above it and the ring
// stays clean, while a handful of contigs each get their scale written out.
const TICK_LABEL_MIN_SPAN = 0.8;

const DEFAULT_MAX_LINKS = 500;
const ASSEMBLY_AUTO = 'auto';
const MAX_LEGEND_ENTRIES = 12;

const SVG_STYLE: React.CSSProperties = { width: '100%', height: '100%', display: 'block' };

/** Degrees for an SVG `rotate()`, from the module's clockwise-from-noon angle. */
const degrees = (angle: number): number => (angle * 180) / Math.PI;

/**
 * Chromosomes on a ring, one chord per link between two loci: gene fusions,
 * structural-variant breakends, translocations.
 *
 * Drawn as plain SVG React elements rather than through a chart library. Plotly
 * has no chord trace and d3 is not a dependency of any package here, while the
 * layout itself is a ring of proportional arcs plus one quadratic Bezier per
 * link, which is a hundred lines of maths (`genome_chord/chordLayout.ts`) rather
 * than a new dependency. Drawing it directly is also what lets a chord be an
 * ordinary DOM node: it carries a title, a hover handler, and a click that emits
 * a dashboard filter.
 */
const GenomeChordRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as GenomeChordConfig;
  const isDark = colorScheme === 'dark';
  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));

  // Tier-2 controls. Defaults agree with GenomeChordConfig's own, so an
  // unconfigured component and a configured one draw the same ring.
  const [assembly, setAssembly] = usePersistedVizControl<string | null>(metadata, 'assembly', null);
  const [colourBy, setColourBy] = usePersistedVizControl<'category' | 'chrom_a' | 'none'>(
    metadata,
    'colour_by',
    'category',
  );
  const [showLabels, setShowLabels] = usePersistedVizControl<boolean>(metadata, 'show_labels', true);
  const [intraChrom, setIntraChrom] = usePersistedVizControl<boolean>(
    metadata,
    'intra_chromosomal',
    true,
  );
  const [maxLinks, setMaxLinks] = usePersistedVizControl<number>(
    metadata,
    'max_links',
    DEFAULT_MAX_LINKS,
  );
  const [minWeight, setMinWeight] = usePersistedVizControl<number | null>(
    metadata,
    'min_weight',
    null,
  );

  // ---- Selection as a cross-filter ---------------------------------------
  // Resolved through selection.ts (named column, else the label column), so the
  // chrome's capability marker and this gate cannot disagree. A host with no
  // onFilterChange is read-only and advertises nothing.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const requiredCols = useMemo(() => {
    const cols = [
      config.chrom_a_col,
      config.pos_a_col,
      config.chrom_b_col,
      config.pos_b_col,
    ].filter(Boolean) as string[];
    for (const c of [
      config.label_col,
      config.weight_col,
      config.category_col,
      config.sample_col,
      selectionColumn,
    ]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [
    config.chrom_a_col,
    config.pos_a_col,
    config.chrom_b_col,
    config.pos_b_col,
    config.label_col,
    config.weight_col,
    config.category_col,
    config.sample_col,
    selectionColumn,
  ]);

  // This component must not narrow itself by its own selection: clicking a chord
  // would redraw the ring as that one chord and the user could never widen it
  // again. Every other component still narrows.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);
  const [hovered, setHovered] = useState<ChordLink | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  // The chords are highlighted from local state, so a clear from outside the
  // ring (the tile's clear-selection action, the filter summary) has to reach
  // it here: once the dashboard no longer holds this tile's selection, nothing
  // is selected.
  const ownSelectionActive = hasOwnSelection(filters, metadata.index, 'scatter_selection');
  useEffect(() => {
    if (!ownSelectionActive) setSelected([]);
  }, [ownSelectionActive]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Genome chord: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters: filtersForFetch,
      vizKind: GENOME_CHORD_VIZ_KIND,
      roles: {
        chrom_a: config.chrom_a_col,
        pos_a: config.pos_a_col,
        chrom_b: config.chrom_b_col,
        pos_b: config.pos_b_col,
      },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    refreshTick,
  ]);

  const allLinks = useMemo<ChordLink[]>(() => {
    if (!rows) return [];
    return parseChordRows(rows, {
      chromA: config.chrom_a_col,
      posA: config.pos_a_col,
      chromB: config.chrom_b_col,
      posB: config.pos_b_col,
      label: config.label_col,
      weight: config.weight_col,
      category: config.category_col,
      sample: config.sample_col,
    });
  }, [
    rows,
    config.chrom_a_col,
    config.pos_a_col,
    config.chrom_b_col,
    config.pos_b_col,
    config.label_col,
    config.weight_col,
    config.category_col,
    config.sample_col,
  ]);

  const prepared = useMemo(
    () =>
      prepareLinks(allLinks, {
        maxLinks: maxLinks || DEFAULT_MAX_LINKS,
        intraChromosomal: intraChrom,
        minWeight,
      }),
    [allLinks, maxLinks, intraChrom, minWeight],
  );

  const ring = useMemo(
    () => buildRing(chromSizesFor(prepared.kept, assembly)),
    [prepared.kept, assembly],
  );

  // The colour universe is the whole fetched frame, not the drawn subset, so a
  // class keeps its hue when a guard or a dashboard filter removes its last link.
  const colourMap = useMemo(() => {
    const values =
      colourBy === 'category'
        ? allLinks.map((l) => l.category)
        : colourBy === 'chrom_a'
          ? allLinks.map((l) => l.chromA)
          : [];
    return stableColorMap(values, palette);
  }, [allLinks, colourBy, palette]);

  const neutralChordColour = isDark ? theme.colors.gray[5] : theme.colors.gray[6];
  const colourOf = useCallback(
    (link: ChordLink): string => {
      if (colourBy === 'none') return neutralChordColour;
      const value = colourBy === 'category' ? link.category : link.chromA;
      return value ? colourMap.get(value) : neutralChordColour;
    },
    [colourBy, colourMap, neutralChordColour],
  );

  const tickStep = useMemo(
    () => tickStepFor(ring.arcs.reduce((acc, a) => Math.max(acc, a.size), 0)),
    [ring.arcs],
  );

  const bandColours = [
    isDark ? theme.colors.dark[3] : theme.colors.gray[4],
    isDark ? theme.colors.dark[2] : theme.colors.gray[5],
  ];

  // Only the label and the sample columns are fetched, so a chord can only stand
  // for one of the two. Which it is follows the resolved selection column.
  const selectionValueOf = useCallback(
    (link: ChordLink): string | null =>
      (selectionColumn && selectionColumn === config.sample_col ? link.sample : link.label) ?? null,
    [selectionColumn, config.sample_col],
  );

  const emitSelection = useCallback(
    (values: string[]) => {
      if (!onFilterChange || !selectionColumn) return;
      setSelected(values);
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
    },
    [onFilterChange, selectionColumn, metadata],
  );

  const toggleLink = useCallback(
    (link: ChordLink) => {
      if (!selectionEnabled) return;
      const value = selectionValueOf(link);
      if (!value) return;
      emitSelection(
        selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value],
      );
    },
    [selectionEnabled, selectionValueOf, selected, emitSelection],
  );

  const chords = useMemo(() => {
    if (ring.arcs.length === 0) return [];
    return prepared.kept
      .map((link) => {
        const a0 = angleAt(ring, link.chromA, link.posA);
        const a1 = angleAt(ring, link.chromB, link.posB);
        if (a0 === null || a1 === null) return null;
        return {
          link,
          d: chordPath(CENTRE, CENTRE, R_CHORD, a0, a1),
          width: chordStrokeWidth(
            link.weight,
            prepared.minWeight,
            prepared.maxWeight,
            CHORD_MIN_WIDTH,
            CHORD_MAX_WIDTH,
          ),
          colour: colourOf(link),
        };
      })
      .filter((c): c is NonNullable<typeof c> => c !== null);
  }, [prepared, ring, colourOf]);

  const legendEntries = useMemo(() => {
    if (colourBy === 'none') return [];
    return colourMap.universe
      .slice(0, MAX_LEGEND_ENTRIES)
      .map((value) => ({ value, colour: colourMap.get(value) }));
  }, [colourBy, colourMap]);

  const counts = useMemo(() => {
    const out: Record<string, number> = { links: chords.length };
    if (prepared.dropped > 0) out.filtered = prepared.dropped;
    return out;
  }, [chords.length, prepared.dropped]);

  const hoverText = hovered
    ? linkSummary(
        hovered,
        hovered.weight !== null ? `weight ${hovered.weight.toLocaleString()}` : null,
      ).join('  ·  ')
    : null;

  // Encoding tier: the ideogram the ring is built on and what the link colour
  // means. How many links are drawn, the weight floor and the labels are the
  // second tier.
  const primaryControls = (
    <>
      <VizSelect
        label="Assembly"
        value={assembly ?? ASSEMBLY_AUTO}
        onChange={(v) => setAssembly(v && v !== ASSEMBLY_AUTO ? v : null)}
        data={[
          { value: ASSEMBLY_AUTO, label: 'From the data' },
          ...ASSEMBLY_NAMES.map((name) => ({ value: name, label: name })),
        ]}
        allowDeselect={false}
      />
      <VizSelect
        label="Colour by"
        value={colourBy}
        onChange={(v) => setColourBy((v as 'category' | 'chrom_a' | 'none') || 'category')}
        data={[
          { value: 'category', label: 'Link class' },
          { value: 'chrom_a', label: 'First chromosome' },
          { value: 'none', label: 'Nothing' },
        ]}
        allowDeselect={false}
      />
    </>
  );

  const controls = (
    <>
      <VizControlGroup title="Links">
        <VizSlider
          label={`Max links: ${maxLinks}`}
          aria-label="Links drawn (at most)"
          min={10}
          max={2000}
          step={10}
          value={maxLinks}
          onChange={setMaxLinks}
          thumbLabel={(v) => String(v)}
        />
        {config.weight_col ? (
          <VizNumberInput
            label="Minimum weight"
            placeholder="no threshold"
            min={0}
            value={minWeight ?? ''}
            onChange={(v) => setMinWeight(v === '' || v === null ? null : Number(v))}
          />
        ) : null}
        <VizSwitch
          checked={intraChrom}
          onChange={(e) => setIntraChrom(e.currentTarget.checked)}
          label="Intra-chromosomal links"
        />
      </VizControlGroup>
      <VizControlGroup title="Labels">
        <VizSwitch
          checked={showLabels}
          onChange={(e) => setShowLabels(e.currentTarget.checked)}
          label="Chromosome labels"
        />
      </VizControlGroup>
    </>
  );

  let emptyMessage: string | undefined;
  if (rows && chords.length === 0) {
    emptyMessage = allLinks.length === 0 ? 'No links' : 'No links left after the current guards';
  }

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Genome chord'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      counts={chords.length > 0 ? counts : undefined}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {chords.length > 0 ? (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
            <svg
              viewBox={`0 0 ${VIEW} ${VIEW}`}
              preserveAspectRatio="xMidYMid meet"
              style={SVG_STYLE}
              role="img"
              aria-label={`${chords.length} links across ${ring.arcs.length} chromosomes`}
              onClick={() => {
                // A click that misses every chord clears the selection, the way
                // a Plotly deselect does on the scatter renderers.
                if (selectionEnabled) emitSelection([]);
              }}
            >
              <g>
                {ring.arcs.map((arc, i) => (
                  <path
                    key={`band-${arc.name}`}
                    d={arcPath(CENTRE, CENTRE, R_BAND_INNER, R_BAND_OUTER, arc.start, arc.end)}
                    fill={bandColours[i % bandColours.length]}
                  >
                    <title>{`${arc.name}  ${formatBp(arc.size)}`}</title>
                  </path>
                ))}
              </g>
              <g stroke={themeColors.textColor} strokeOpacity={0.45} strokeWidth={1}>
                {ring.arcs.flatMap((arc) =>
                  ticksFor(arc.size, tickStep).map((pos) => {
                    const angle = angleAt(ring, arc.name, pos);
                    if (angle === null) return null;
                    const p0 = polarPoint(CENTRE, CENTRE, R_BAND_OUTER, angle);
                    const p1 = polarPoint(CENTRE, CENTRE, R_TICK_OUTER, angle);
                    return (
                      <line
                        key={`tick-${arc.name}-${pos}`}
                        x1={p0.x}
                        y1={p0.y}
                        x2={p1.x}
                        y2={p1.y}
                      />
                    );
                  }),
                )}
              </g>
              {showLabels ? (
                <g fill={themeColors.textColor} stroke="none">
                  {ring.arcs.flatMap((arc) => {
                    // On the left half the outward direction points backwards, so
                    // the label is rotated the other way and anchored at its end
                    // to stay right-reading.
                    const flip = Math.sin(arc.mid) < 0;
                    const at = polarPoint(CENTRE, CENTRE, R_LABEL, arc.mid);
                    const rotation = flip ? degrees(arc.mid) + 90 : degrees(arc.mid) - 90;
                    const nodes: React.ReactNode[] = [
                      <text
                        key={`label-${arc.name}`}
                        x={at.x}
                        y={at.y}
                        fontSize={15}
                        dominantBaseline="middle"
                        textAnchor={flip ? 'end' : 'start'}
                        transform={`rotate(${rotation.toFixed(2)} ${at.x.toFixed(2)} ${at.y.toFixed(2)})`}
                      >
                        {arc.name}
                      </text>,
                    ];
                    if (arc.end - arc.start >= TICK_LABEL_MIN_SPAN) {
                      for (const pos of ticksFor(arc.size, tickStep)) {
                        const angle = angleAt(ring, arc.name, pos);
                        if (angle === null) continue;
                        const tp = polarPoint(CENTRE, CENTRE, R_TICK_LABEL, angle);
                        nodes.push(
                          <text
                            key={`ticklabel-${arc.name}-${pos}`}
                            x={tp.x}
                            y={tp.y}
                            fontSize={10}
                            fillOpacity={0.65}
                            dominantBaseline="middle"
                            textAnchor="middle"
                          >
                            {formatBp(pos)}
                          </text>,
                        );
                      }
                    }
                    return nodes;
                  })}
                </g>
              ) : null}
              <g fill="none" strokeLinecap="round">
                {chords.map(({ link, d, width, colour }) => {
                  const value = selectionValueOf(link);
                  const isSelected = value !== null && selected.includes(value);
                  const dimmed =
                    (hovered !== null && hovered.row !== link.row) ||
                    (selected.length > 0 && !isSelected);
                  return (
                    <path
                      key={`chord-${link.row}`}
                      d={d}
                      stroke={colour}
                      strokeWidth={hovered?.row === link.row ? width + 2 : width}
                      strokeOpacity={dimmed ? CHORD_DIM_OPACITY : CHORD_OPACITY}
                      style={{ cursor: selectionEnabled ? 'pointer' : 'default' }}
                      onMouseEnter={() => setHovered(link)}
                      onMouseLeave={() => setHovered(null)}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleLink(link);
                      }}
                    >
                      <title>
                        {linkSummary(
                          link,
                          link.weight !== null ? `weight ${link.weight}` : null,
                        ).join('\n')}
                      </title>
                    </path>
                  );
                })}
              </g>
            </svg>
            {hoverText ? (
              <Paper
                withBorder
                shadow="sm"
                p={6}
                radius="sm"
                style={{ position: 'absolute', left: 4, bottom: 4, maxWidth: '85%' }}
              >
                <Text size="xs" lineClamp={2}>
                  {hoverText}
                </Text>
              </Paper>
            ) : null}
          </div>
          {legendEntries.length > 0 ? (
            <Group gap={10} mt={4} wrap="wrap" justify="center">
              {legendEntries.map(({ value, colour }) => (
                <Group key={value} gap={4} wrap="nowrap">
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      backgroundColor: colour,
                      display: 'inline-block',
                    }}
                  />
                  <Text size="xs" c="dimmed">
                    {value}
                  </Text>
                </Group>
              ))}
            </Group>
          ) : null}
        </div>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default GenomeChordRenderer;
