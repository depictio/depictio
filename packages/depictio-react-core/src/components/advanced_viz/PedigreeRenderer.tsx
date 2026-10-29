import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Group, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersExcludingOwn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForPx } from './contentDemand';
import { VizSwitch } from './controls/VizControls';
import {
  buildPedigree,
  DEFAULT_LAYOUT,
  layoutPedigree,
  type AffectedStatus,
  type PlacedPerson,
  type Sex,
} from './pedigree/pedigreeLayout';
import { packFamilies } from './pedigree/pedigreeRows';
import { probandKeyOf, romanNumeral } from './pedigree/probands';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `PedigreeConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface PedigreeConfig {
  individual_col: string;
  father_col: string;
  mother_col: string;
  sex_col: string;
  status_col: string;
  family_col?: string | null;
  label_col?: string | null;
  deceased_col?: string | null;
  proband_col?: string | null;
  show_labels?: boolean;
  max_individuals?: number;
  max_families?: number;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PedigreeConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// A pedigree is a graph held in rows: the server never samples this kind
// (`KIND_SAMPLING_POLICY["pedigree"] == "none"`), because a sampled frame drops
// a parent and the child under it would be drawn as a founder.
const PEDIGREE_VIZ_KIND: AdvancedVizKind = 'pedigree';

const DEFAULT_MAX_INDIVIDUALS = 300;
const DEFAULT_MAX_FAMILIES = 12;
/** Drawing units (the SVG viewBox): room left of the trees for the generation
 *  numerals, around them, and under the last row for the labels. */
const GUTTER = 34;
const PAD_X = 14;
const PAD_BOTTOM = 40;
/** Text is sized in screen px, so it reads at any fit scale. */
const LABEL_PX = 13;
const DIM_OPACITY = 0.3;
const MAX_FONT_UNITS = 17;
const MIN_FONT_UNITS = 8;
const LINE_WIDTH = 1.6;

const STATUS_WORD: Record<AffectedStatus, string> = {
  affected: 'affected',
  unaffected: 'unaffected',
  unknown: 'status unknown',
};
const SEX_WORD: Record<Sex, string> = { male: 'male', female: 'female', unknown: 'sex unknown' };

function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text;
}

interface SymbolPaint {
  /** Outline and lines. */
  ink: string;
  /** Fill of an unaffected symbol. */
  body: string;
  /** Fill of an affected symbol: the theme's danger colour. */
  affected: string;
  hatch: string;
  /** The picked outline and the proband arrow: the theme's primary colour. */
  ring: string;
}

/** The arrow that points at the proband, from the lower left. Centred on the
 *  symbol's centre, `half` its half edge. */
const ProbandArrow: React.FC<{ half: number; paint: SymbolPaint }> = ({ half, paint }) => {
  // From the lower left, flatter than the deceased slash and above the label.
  const tipX = -half - 4;
  const tipY = half - 3;
  const tailX = tipX - 19;
  const tailY = tipY + 9;
  // Arrow head: two short strokes at the tip, along the shaft's angle.
  const angle = Math.atan2(tipY - tailY, tipX - tailX);
  const head = (da: number) => {
    const a = angle + Math.PI + da;
    return `${tipX + 8 * Math.cos(a)},${tipY + 8 * Math.sin(a)}`;
  };
  return (
    <g stroke={paint.ring} strokeWidth={2.2} strokeLinecap="round" fill={paint.ring}>
      <line x1={tailX} y1={tailY} x2={tipX} y2={tipY} />
      <polygon points={`${tipX},${tipY} ${head(0.45)} ${head(-0.45)}`} strokeWidth={1} />
    </g>
  );
};

/** One pedigree symbol, centred on (0, 0): square male, circle female, diamond
 *  unknown; filled affected, open unaffected, hatched unknown; slashed when
 *  deceased; an arrow when proband. Shared by the tree and the legend so the
 *  two cannot disagree. */
const PedigreeSymbol: React.FC<{
  sex: Sex;
  status: AffectedStatus;
  deceased: boolean;
  size: number;
  paint: SymbolPaint;
  hatchId: string;
  dashed?: boolean;
  picked?: boolean;
  hovered?: boolean;
  proband?: boolean;
}> = ({ sex, status, deceased, size, paint, hatchId, dashed, picked, hovered, proband }) => {
  const half = size / 2;
  const fill =
    status === 'affected' ? paint.affected : status === 'unknown' ? `url(#${hatchId})` : paint.body;
  const common = {
    fill,
    stroke: paint.ink,
    strokeWidth: hovered ? 2.4 : 1.8,
    strokeDasharray: dashed ? '3 2' : undefined,
  };
  const ringPad = 4;
  const diamond = (r: number) => `0,${-r} ${r},0 0,${r} ${-r},0`;
  const diamondRadius = half * 1.2;
  const halo = { fill: paint.ring, fillOpacity: 0.2, stroke: 'none' };
  const haloPad = 8;
  return (
    <>
      {hovered ? (
        sex === 'female' ? (
          <circle r={half + haloPad} {...halo} />
        ) : sex === 'male' ? (
          <rect
            x={-half - haloPad}
            y={-half - haloPad}
            width={size + 2 * haloPad}
            height={size + 2 * haloPad}
            rx={4}
            {...halo}
          />
        ) : (
          <polygon points={diamond(diamondRadius + haloPad * 1.3)} {...halo} />
        )
      ) : null}
      {picked ? (
        sex === 'female' ? (
          <circle r={half + ringPad} fill="none" stroke={paint.ring} strokeWidth={3} />
        ) : sex === 'male' ? (
          <rect
            x={-half - ringPad}
            y={-half - ringPad}
            width={size + 2 * ringPad}
            height={size + 2 * ringPad}
            fill="none"
            stroke={paint.ring}
            strokeWidth={3}
          />
        ) : (
          <polygon
            points={diamond(diamondRadius + ringPad * 1.4)}
            fill="none"
            stroke={paint.ring}
            strokeWidth={3}
          />
        )
      ) : null}
      {sex === 'female' ? (
        <circle r={half} {...common} />
      ) : sex === 'male' ? (
        <rect x={-half} y={-half} width={size} height={size} {...common} />
      ) : (
        <polygon points={diamond(diamondRadius)} {...common} />
      )}
      {deceased ? (
        <line
          x1={-half - 5}
          y1={half + 5}
          x2={half + 5}
          y2={-half - 5}
          stroke={paint.ink}
          strokeWidth={1.8}
        />
      ) : null}
      {proband ? <ProbandArrow half={half} paint={paint} /> : null}
    </>
  );
};

const HatchDefs: React.FC<{ id: string; paint: SymbolPaint }> = ({ id, paint }) => (
  <defs>
    <pattern id={id} width={5} height={5} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width={5} height={5} fill={paint.body} />
      <line x1={0} y1={0} x2={0} y2={5} stroke={paint.hatch} strokeWidth={2} />
    </pattern>
  </defs>
);

interface Hover {
  person: PlacedPerson;
  x: number;
  y: number;
}

/**
 * Family tree from a PED-like table.
 *
 * Plain SVG with every coordinate from `pedigree/pedigreeLayout.ts`; this
 * component resolves the theme, draws the standard symbols and wires the hover
 * and the pick. A click on a symbol emits the dashboard's selection filter on
 * the individual column (or `selection_column`), the way the other selecting
 * kinds do, and the picked symbols are read back from the filter list so a
 * Reset from the tile chrome clears the outline.
 */
const PedigreeRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as PedigreeConfig;
  const hatchId = `ped-hatch-${useId().replace(/:/g, '')}`;

  const [showLabels, setShowLabels] = usePersistedVizControl<boolean>(metadata, 'show_labels', true);

  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const requiredCols = useMemo(() => {
    const cols: string[] = [];
    for (const c of [
      config.individual_col,
      config.father_col,
      config.mother_col,
      config.sex_col,
      config.status_col,
      config.family_col,
      config.label_col,
      config.deceased_col,
      config.proband_col,
      selectionColumn,
    ]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [
    config.individual_col,
    config.father_col,
    config.mother_col,
    config.sex_col,
    config.status_col,
    config.family_col,
    config.label_col,
    config.deceased_col,
    config.proband_col,
    selectionColumn,
  ]);

  // The tree never narrows itself by its own pick: filtering to one individual
  // would leave a child without the parents the symbols hang from.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    if (
      !metadata.wf_id ||
      !metadata.dc_id ||
      !config.individual_col ||
      !config.father_col ||
      !config.mother_col
    ) {
      setError('Pedigree: missing data binding');
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
      vizKind: PEDIGREE_VIZ_KIND,
      roles: {
        individual: config.individual_col,
        father: config.father_col,
        mother: config.mother_col,
        sex: config.sex_col,
        status: config.status_col,
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

  const input = useMemo(
    () =>
      rows
        ? buildPedigree(
            rows,
            {
              individual: config.individual_col,
              father: config.father_col,
              mother: config.mother_col,
              sex: config.sex_col,
              status: config.status_col,
              family: config.family_col,
              label: config.label_col,
              deceased: config.deceased_col,
            },
            {
              maxIndividuals: config.max_individuals ?? DEFAULT_MAX_INDIVIDUALS,
              maxFamilies: config.max_families ?? DEFAULT_MAX_FAMILIES,
            },
          )
        : null,
    [
      rows,
      config.individual_col,
      config.father_col,
      config.mother_col,
      config.sex_col,
      config.status_col,
      config.family_col,
      config.label_col,
      config.deceased_col,
      config.max_individuals,
      config.max_families,
    ],
  );

  const layout = useMemo(
    () =>
      input
        ? layoutPedigree(input, { labelSpace: showLabels ? DEFAULT_LAYOUT.labelSpace : 0 })
        : null,
    [input, showLabels],
  );

  // ---- What is picked, read back out of the filter list ------------------
  const own = useMemo(
    () =>
      filters.find(
        (f) =>
          f.index === metadata.index &&
          f.source === 'scatter_selection' &&
          Array.isArray(f.value) &&
          f.value.length > 0,
      ),
    [filters, metadata.index],
  );
  const picked = useMemo(
    () =>
      own && own.column_name === selectionColumn
        ? new Set((own.value as unknown[]).map(String))
        : new Set<string>(),
    [own, selectionColumn],
  );
  const selectValueOf = useCallback(
    (person: PlacedPerson['person']): string | null => {
      if (!selectionColumn || person.placeholder) return null;
      const raw = person.row[selectionColumn];
      return raw === null || raw === undefined || raw === '' ? null : String(raw);
    },
    [selectionColumn],
  );

  const pick = useCallback(
    (person: PlacedPerson['person']) => {
      const value = selectValueOf(person);
      if (!selectionEnabled || !selectionColumn || !onFilterChange || value === null) return;
      const next = new Set(picked);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, [...next]));
    },
    [selectValueOf, selectionEnabled, selectionColumn, onFilterChange, picked, metadata],
  );
  const clear = useCallback(() => {
    if (selectionEnabled && selectionColumn && onFilterChange && picked.size > 0) {
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, []));
    }
  }, [selectionEnabled, selectionColumn, onFilterChange, picked, metadata]);

  // ---- Theme ---------------------------------------------------------------
  const paint: SymbolPaint = useMemo(
    () => ({
      ink: isDark ? theme.colors.gray[3] : theme.colors.dark[7],
      body: isDark ? theme.colors.dark[7] : theme.white,
      affected: theme.colors.red[isDark ? 5 : 6],
      hatch: isDark ? theme.colors.gray[6] : theme.colors.gray[5],
      ring: theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? theme.colors.blue[6],
    }),
    [isDark, theme],
  );
  const lineColour = paint.ink;
  const mutedText = isDark ? theme.colors.gray[5] : theme.colors.gray[7];

  // ---- Probands --------------------------------------------------------------
  const probands = useMemo(() => {
    const out = new Set<string>();
    if (!input) return out;
    for (const family of input.families) {
      const key = probandKeyOf(family.people, config.proband_col);
      if (key) out.add(key);
    }
    return out;
  }, [input, config.proband_col]);

  // ---- Geometry ------------------------------------------------------------
  // The drawing is in layout units and the SVG's viewBox fits it to the tile,
  // centred both ways, symbols growing up to a sensible maximum; a tree too
  // big to read at the smallest scale scrolls instead.
  // The box is only in the DOM once the rows are in (the frame shows a skeleton
  // before), so it is tracked through a callback ref: an effect that read a ref
  // at mount would find nothing and never measure.
  const viewRef = useRef<HTMLDivElement | null>(null);
  const [viewEl, setViewEl] = useState<HTMLDivElement | null>(null);
  const setView = useCallback((el: HTMLDivElement | null) => {
    viewRef.current = el;
    setViewEl(el);
  }, []);
  const [view, setViewSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!viewEl) return undefined;
    const measure = () =>
      setViewSize((prev) =>
        prev.w === viewEl.clientWidth && prev.h === viewEl.clientHeight
          ? prev
          : { w: viewEl.clientWidth, h: viewEl.clientHeight },
      );
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(viewEl);
    return () => ro.disconnect();
  }, [viewEl]);
  const symbol = DEFAULT_LAYOUT.symbol;
  // Families wrap into rows when that lets the symbols grow: a few small
  // families side by side are a strip, and wrapped they fill a taller tile.
  const packing = useMemo(
    () =>
      input
        ? packFamilies(input.families, {
            labelSpace: showLabels ? DEFAULT_LAYOUT.labelSpace : 0,
            availW: view.w - 16,
            availH: view.h - 12,
            gutter: GUTTER,
            padX: PAD_X,
            padBottom: PAD_BOTTOM,
          })
        : null,
    [input, showLabels, view.w, view.h],
  );
  const contentW = packing?.contentW ?? 0;
  const contentH = packing?.contentH ?? 0;
  const scale = packing?.scale ?? 1;
  const svgWidth = contentW * scale;
  const svgHeight = contentH * scale;
  const fontUnits = Math.min(MAX_FONT_UNITS, Math.max(MIN_FONT_UNITS, LABEL_PX / scale));
  const labelChars = Math.max(4, Math.floor((DEFAULT_LAYOUT.slot * 0.94) / (fontUnits * 0.56)));
  // Generation numerals, one set per row of families (y in the whole drawing).
  const generationRows = useMemo(
    () =>
      (packing?.rows ?? []).map((row) => {
        const ys = new Map<number, number>();
        for (const family of row.layout.families) {
          for (const placed of family.people) ys.set(placed.generation, row.y + placed.y);
        }
        return [...ys.entries()].sort((a, b) => a[0] - b[0]);
      }),
    [packing],
  );
  const contentDemand = useMemo(
    () => (layout && layout.families.length > 0 ? demandForPx(contentH + 36) : undefined),
    [layout, contentH],
  );

  // ---- Counts and echo -----------------------------------------------------
  const counts = useMemo(() => {
    if (!input || !layout || layout.families.length === 0) return undefined;
    const people = layout.families.flatMap((f) => f.people).filter((p) => !p.person.placeholder);
    const out: Record<string, number> = {
      individuals: people.length,
      affected: people.filter((p) => p.person.status === 'affected').length,
    };
    if (input.families.length > 1) out.families = input.families.length;
    if (input.hiddenFamilies > 0) out['families hidden'] = input.hiddenFamilies;
    if (input.duplicates > 0) out['duplicates dropped'] = input.duplicates;
    return out;
  }, [input, layout]);
  const echo =
    picked.size > 0
      ? `picked ${[...picked].slice(0, 3).join(', ')}${picked.size > 3 ? ` +${picked.size - 3}` : ''}`
      : undefined;

  const controls = (
    <VizSwitch
      checked={showLabels}
      onChange={(e) => setShowLabels(e.currentTarget.checked)}
      label="Labels under symbols"
    />
  );

  // ---- Tooltip ---------------------------------------------------------------
  const hoverLines = useMemo(() => {
    if (!hover) return [];
    const { person } = hover.person;
    if (person.placeholder) return [`${person.id}`, 'named as a parent, not in the table'];
    const lines = Object.entries(person.row).map(([col, v]) => `${col}: ${v === null || v === undefined || v === '' ? '–' : String(v)}`);
    lines.push(`${SEX_WORD[person.sex]}, ${STATUS_WORD[person.status]}${person.deceased ? ', deceased' : ''}`);
    return lines;
  }, [hover]);

  const onEnter = (placed: PlacedPerson) => (e: React.MouseEvent) => {
    const box = viewRef.current?.getBoundingClientRect();
    setHover({
      person: placed,
      x: e.clientX - (box?.left ?? 0) + (viewRef.current?.scrollLeft ?? 0),
      y: e.clientY - (box?.top ?? 0) + (viewRef.current?.scrollTop ?? 0),
    });
  };

  const anyPick = picked.size > 0;
  const legendId = `${hatchId}-legend`;
  const legendItem = (
    text: string,
    sex: Sex,
    status: AffectedStatus,
    options: { deceased?: boolean; proband?: boolean } = {},
  ) => (
    <Group key={text} gap={3} wrap="nowrap" style={{ flex: '0 0 auto' }}>
      <svg
        width={options.proband ? 31 : 18}
        height={18}
        aria-hidden="true"
        style={{ overflow: 'visible' }}
      >
        <g transform={`translate(${options.proband ? 26 : 9} ${options.proband ? 7 : 9})`}>
          <PedigreeSymbol
            sex={sex}
            status={status}
            deceased={Boolean(options.deceased)}
            proband={options.proband}
            size={10}
            paint={paint}
            hatchId={legendId}
          />
        </g>
      </svg>
      <Text c="dimmed" style={{ fontSize: 11, lineHeight: 1 }}>
        {text}
      </Text>
    </Group>
  );
  const present = useMemo(() => {
    const people = (layout?.families ?? []).flatMap((f) => f.people).filter((p) => !p.person.placeholder);
    return {
      sexUnknown: people.some((p) => p.person.sex === 'unknown'),
      statusUnknown: people.some((p) => p.person.status === 'unknown'),
      deceased: people.some((p) => p.person.deceased),
    };
  }, [layout]);

  const emptyMessage = rows && layout && layout.families.length === 0 ? 'No individuals' : undefined;
  const hoveredKey = hover?.person.person.key ?? null;

  const svg =
    layout && layout.families.length > 0 ? (
      <svg
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${contentW} ${contentH}`}
        role="img"
        aria-label={`Pedigree of ${counts?.individuals ?? 0} individuals`}
        // `margin: auto` centres it both ways when the tile is larger, and
        // still scrolls from the top left when it is not.
        style={{ display: 'block', margin: 'auto', flex: '0 0 auto' }}
        onClick={clear}
        onMouseLeave={() => setHover(null)}
      >
        <HatchDefs id={hatchId} paint={paint} />
        {generationRows.map((ys, rowIndex) =>
          ys.map(([generation, y]) => (
            <text
              key={`generation-${rowIndex}-${generation}`}
              x={GUTTER / 2 + 2}
              y={y}
              fontSize={fontUnits * 1.05}
              fontWeight={600}
              fill={mutedText}
              textAnchor="middle"
              dominantBaseline="central"
              pointerEvents="none"
            >
              {romanNumeral(generation + 1)}
            </text>
          )),
        )}
        {(packing?.rows ?? []).map((row, rowIndex) => (
        <g key={`row-${rowIndex}`} transform={`translate(${GUTTER + PAD_X} ${row.y})`}>
          {row.layout.families.map((family) => {
            const showCaption = Boolean(config.family_col);
            return (
              <g key={`family-${family.id}`}>
                {showCaption ? (
                  <text
                    x={family.x + family.width / 2}
                    y={fontUnits + 2}
                    fontSize={fontUnits}
                    fontWeight={700}
                    fill={mutedText}
                    textAnchor="middle"
                  >
                    {family.id || 'family'}
                  </text>
                ) : null}
                {family.lines.map((l, i) => (
                  <line
                    key={`${l.kind}-${i}`}
                    x1={l.x1}
                    y1={l.y1}
                    x2={l.x2}
                    y2={l.y2}
                    stroke={lineColour}
                    strokeWidth={LINE_WIDTH}
                    strokeLinecap="square"
                  />
                ))}
                {family.people.map((placed) => {
                  const { person } = placed;
                  const value = selectValueOf(person);
                  const isPicked = value !== null && picked.has(value);
                  const dim = anyPick && !isPicked;
                  const isHovered = hoveredKey === person.key;
                  return (
                    <g
                      key={person.key}
                      transform={`translate(${placed.x} ${placed.y})`}
                      opacity={dim ? DIM_OPACITY : 1}
                      style={{ cursor: selectionEnabled && value !== null ? 'pointer' : 'default' }}
                      onMouseEnter={onEnter(placed)}
                      onMouseMove={onEnter(placed)}
                      onClick={(e) => {
                        e.stopPropagation();
                        pick(person);
                      }}
                    >
                      <PedigreeSymbol
                        sex={person.sex}
                        status={person.status}
                        deceased={person.deceased}
                        size={symbol}
                        paint={paint}
                        hatchId={hatchId}
                        dashed={person.placeholder}
                        picked={isPicked}
                        hovered={isHovered}
                        proband={probands.has(person.key)}
                      />
                      {showLabels && !person.placeholder ? (
                        <text
                          y={symbol / 2 + fontUnits + 7}
                          fontSize={fontUnits}
                          fill={paint.ink}
                          fontWeight={isPicked || isHovered ? 700 : 500}
                          textAnchor="middle"
                          pointerEvents="none"
                        >
                          {shorten(person.label, labelChars)}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            );
          })}
        </g>
        ))}
      </svg>
    ) : null;

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Pedigree'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      counts={counts}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
        <div
          ref={setView}
          style={{
            flex: '1 1 auto',
            minHeight: 0,
            overflow: 'auto',
            position: 'relative',
            display: 'flex',
          }}
        >
          {svg}
          {hover && hoverLines.length > 0 ? (
            <Paper
              withBorder
              shadow="sm"
              p={6}
              radius="sm"
              style={{
                position: 'absolute',
                left: Math.min(hover.x + 12, Math.max(0, (view.w || 0) - 240)),
                top: hover.y + 14,
                maxWidth: 240,
                pointerEvents: 'none',
                zIndex: 2,
              }}
            >
              {hoverLines.map((line, i) => (
                <Text key={`${i}-${line}`} size="xs" fw={i === 0 ? 600 : 400}>
                  {line}
                </Text>
              ))}
            </Paper>
          ) : null}
        </div>
        {layout && layout.families.length > 0 ? (
          <Group gap={10} wrap="wrap" justify="center" style={{ flex: '0 0 auto', paddingTop: 2 }}>
            <svg width={0} height={0} aria-hidden="true" style={{ position: 'absolute' }}>
              <HatchDefs id={legendId} paint={paint} />
            </svg>
            {legendItem('Male', 'male', 'unaffected')}
            {legendItem('Female', 'female', 'unaffected')}
            {present.sexUnknown ? legendItem('Sex unknown', 'unknown', 'unaffected') : null}
            {legendItem('Affected', 'female', 'affected')}
            {legendItem('Unaffected', 'female', 'unaffected')}
            {present.statusUnknown ? legendItem('Status unknown', 'female', 'unknown') : null}
            {present.deceased ? legendItem('Deceased', 'female', 'unaffected', { deceased: true }) : null}
            {probands.size > 0 ? legendItem('Proband', 'female', 'unaffected', { proband: true }) : null}
          </Group>
        ) : null}
      </div>
    </AdvancedVizFrame>
  );
};

export default PedigreeRenderer;
