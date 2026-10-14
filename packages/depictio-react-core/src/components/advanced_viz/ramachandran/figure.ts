/**
 * The Plotly figure of a Ramachandran plot, built from plain data.
 *
 * Pure: the points, the colour mode and a bag of theme tokens go in, `data` and
 * `layout` come out. The renderer owns the Mantine theme (it turns it into the
 * tokens) and runs the shared Plotly theme pass over the result. SVG `scatter`
 * only: a plot of a few thousand residues does not need WebGL, and a tile that
 * took a GL slot would compete with the dashboard's other plots for one.
 *
 * Points are grouped by what the colour mode says about them (a pLDDT band, a
 * residue class, a chain, ...), one trace per group, and each point carries the
 * marker symbol of its residue class (glycine, proline and pre-proline are not
 * circles). In the `residue_class` mode the two coincide: a trace per class.
 */

import { stableColorMap } from '../../../colors';
import {
  PLDDT_BANDS,
  plddtBand,
  rgbCss,
  SECONDARY_STRUCTURE_COLOURS,
  type SecondaryStructure,
} from '../protein/residueColours';
import { looksLikeSecondaryStructure, secondaryStructureOf } from '../protein/sequence';
import {
  labelAnchor,
  polygonPath,
  REGION_LABELS,
  REGION_NOTE,
  REGION_SET_LABELS,
  regionAt,
  regionSet,
  regionSetOfClass,
  type RegionName,
  type RegionSetName,
} from './regions';
import {
  CLASS_LABELS,
  positionLabel,
  RESIDUE_CLASSES,
  type AnnotatedPoint,
  type ResidueClass,
} from './torsions';

export type ColourMode =
  | 'plddt'
  | 'residue_class'
  | 'secondary_structure'
  | 'value'
  | 'category'
  | 'chain';

export const COLOUR_MODES: readonly { value: ColourMode; label: string }[] = [
  { value: 'plddt', label: 'pLDDT' },
  { value: 'residue_class', label: 'Residue class' },
  { value: 'secondary_structure', label: 'Secondary structure' },
  { value: 'value', label: 'Value' },
  { value: 'category', label: 'Category' },
  { value: 'chain', label: 'Chain' },
];

/** Marker symbol per residue class: glycine, proline and pre-proline each get
 *  their own, as in the MolProbity plots. */
export const CLASS_SYMBOLS: Readonly<Record<ResidueClass, string>> = {
  general: 'circle',
  glycine: 'triangle-up',
  proline: 'square',
  pre_proline: 'diamond',
};

/** The tick every 60 degrees, the window the angles live in. */
export const TICKS: readonly number[] = [-180, -120, -60, 0, 60, 120, 180];
export const ANGLE_RANGE: readonly [number, number] = [-180, 180];

/** Most legend entries a categorical mode draws before folding the smallest
 *  groups into one "Other" entry. */
export const MAX_LEGEND_GROUPS = 12;

/** The colours and fonts the figure needs, already resolved from the theme. */
export interface FigureTheme {
  text: string;
  dimmed: string;
  grid: string;
  zeroLine: string;
  accent: string;
  /** Translucent fill of the favoured regions. */
  accentFill: string;
  /** The ring of a hovered residue. */
  highlight: string;
  /** Points a mode has nothing to say about (no B-factor, no category). */
  neutral: string;
  /** Categorical palette, in order. */
  categorical: readonly string[];
  /** Plotly colour scale name of the `value` mode. */
  valueScale?: string;
}

/** A residue range to emphasise; `chain` null means any chain. */
export interface HighlightRange {
  start: number;
  end: number;
  chain: string | null;
}

export interface FigureArgs {
  points: readonly AnnotatedPoint[];
  mode: ColourMode;
  markerSize: number;
  showRegions: boolean;
  regionSet: RegionSetName;
  theme: FigureTheme;
  /** The structure's B-factors are pLDDT on a 0-1 scale (decided once per structure). */
  plddtFractional: boolean;
  /** What the B-factor column is called in the tooltip. */
  bfactorLabel: 'pLDDT' | 'B-factor';
  valueLabel?: string | null;
  categoryLabel?: string | null;
  /** Every category the colours are keyed on, so a category keeps its colour
   *  when the entity changes. Defaults to the categories of `points`. */
  categoryUniverse?: readonly string[];
  /** Residues to emphasise: Plotly selects them and dims the rest. */
  highlight?: HighlightRange | null;
  dragmode: 'select' | 'zoom';
  /** Zoom and pan persist while this stays the same. */
  uirevision: string;
  /** Plotly's own selection persists while this stays the same; changing it
   *  makes the `selectedpoints` below win over what the reader drew. */
  selectionrevision: string;
}

type Trace = Record<string, unknown>;

export interface BuiltFigure {
  data: Trace[];
  layout: Record<string, unknown>;
  legendTitle: string;
  /** Where `secondary_structure` mode read its states from; null in other modes. */
  ssSource: 'category' | 'torsion' | null;
  /** Per trace of `data`, the indices into `points` of its members, in the
   *  order the trace lists them. `customdata` holds the same indices. */
  members: number[][];
  /** Points inside `highlight`. */
  highlighted: number;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

/** Text from the data goes into Plotly's HTML-ish labels, so it is escaped. */
function esc(value: string): string {
  return value.replace(/[&<>]/g, (c) => ESCAPES[c]);
}

function formatNumber(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 10 ? 1 : 2);
}

const degrees = (v: number): string => `${v.toFixed(1)}°`;

const CLASS_RANK: Record<ResidueClass, number> = Object.fromEntries(
  RESIDUE_CLASSES.map((c, i) => [c, i]),
) as Record<ResidueClass, number>;

function inRange(p: { position: number; chain: string }, h: HighlightRange): boolean {
  return p.position >= h.start && p.position <= h.end && (h.chain === null || p.chain === h.chain);
}

// ---------------------------------------------------------------------------
// Grouping by colour
// ---------------------------------------------------------------------------

interface Group {
  key: string;
  label: string;
  colour: string;
  members: number[];
}

interface Grouping {
  groups: Group[];
  legendTitle: string;
  ssSource: 'category' | 'torsion' | null;
}

function bucket(points: readonly AnnotatedPoint[], keyOf: (p: AnnotatedPoint) => string | null) {
  const buckets = new Map<string, number[]>();
  points.forEach((p, i) => {
    const key = keyOf(p);
    if (key === null) return;
    const list = buckets.get(key);
    if (list) list.push(i);
    else buckets.set(key, [i]);
  });
  return buckets;
}

/** Fold the smallest groups beyond `max` into one neutral "Other" group, keeping
 *  the rest in their order. */
function capGroups(groups: Group[], max: number, neutral: string): Group[] {
  if (groups.length <= max) return groups;
  const bySize = [...groups].sort((a, b) => b.members.length - a.members.length);
  const keep = new Set(bySize.slice(0, max - 1).map((g) => g.key));
  const kept = groups.filter((g) => keep.has(g.key));
  const rest = groups.filter((g) => !keep.has(g.key));
  kept.push({
    key: '\u0000other',
    label: `Other (${rest.length})`,
    colour: neutral,
    members: rest.flatMap((g) => g.members),
  });
  return kept;
}

const SS_LABELS_FROM_COLUMN: Record<SecondaryStructure, string> = {
  helix: 'Helix',
  strand: 'Strand',
  turn: 'Turn',
  coil: 'Coil',
};

const SS_LABELS_FROM_TORSIONS: Record<SecondaryStructure, string> = {
  helix: 'Helix (αR region)',
  strand: 'Strand (β region)',
  turn: 'Left-handed (αL region)',
  coil: 'Other (outside the regions)',
};

const REGION_TO_SS: Record<RegionName, SecondaryStructure> = {
  alpha_r: 'helix',
  beta: 'strand',
  alpha_l: 'turn',
};

const SS_ORDER: readonly SecondaryStructure[] = ['helix', 'strand', 'turn', 'coil'];

function ssColour(ss: SecondaryStructure, theme: FigureTheme): string {
  return ss === 'coil' ? theme.neutral : rgbCss(SECONDARY_STRUCTURE_COLOURS[ss]);
}

function groupPoints(args: FigureArgs): Grouping {
  const { points, mode, theme } = args;
  switch (mode) {
    case 'plddt': {
      const buckets = bucket(points, (p) =>
        p.bfactor === null ? 'none' : plddtBand(p.bfactor, args.plddtFractional).key,
      );
      const groups: Group[] = [];
      for (const band of PLDDT_BANDS) {
        const members = buckets.get(band.key);
        if (members) {
          groups.push({ key: band.key, label: band.label, colour: rgbCss(band.rgb), members });
        }
      }
      const none = buckets.get('none');
      if (none) groups.push({ key: 'none', label: 'No B-factor', colour: theme.neutral, members: none });
      return { groups, legendTitle: 'pLDDT', ssSource: null };
    }
    case 'residue_class': {
      const buckets = bucket(points, (p) => p.cls);
      const groups: Group[] = [];
      RESIDUE_CLASSES.forEach((cls, i) => {
        const members = buckets.get(cls);
        if (members) {
          groups.push({
            key: cls,
            label: CLASS_LABELS[cls],
            colour: theme.categorical[i % theme.categorical.length],
            members,
          });
        }
      });
      return { groups, legendTitle: 'Residue class', ssSource: null };
    }
    case 'secondary_structure': {
      const fromColumn = looksLikeSecondaryStructure(points.map((p) => p.category));
      const labels = fromColumn ? SS_LABELS_FROM_COLUMN : SS_LABELS_FROM_TORSIONS;
      const stateOf = (p: AnnotatedPoint): SecondaryStructure | null => {
        if (fromColumn) return secondaryStructureOf(p.category);
        const region = regionAt(p.phi, p.psi, regionSetOfClass(p.cls));
        return region ? REGION_TO_SS[region] : 'coil';
      };
      const buckets = bucket(points, (p) => stateOf(p) ?? 'none');
      const groups: Group[] = [];
      for (const ss of SS_ORDER) {
        const members = buckets.get(ss);
        if (members) {
          groups.push({ key: ss, label: labels[ss], colour: ssColour(ss, theme), members });
        }
      }
      const none = buckets.get('none');
      if (none) {
        groups.push({ key: 'none', label: 'No annotation', colour: theme.neutral, members: none });
      }
      return {
        groups,
        legendTitle: fromColumn
          ? `Secondary structure<br>(from ${esc(args.categoryLabel || 'the bound column')})`
          : 'Secondary structure<br>(from φ/ψ regions, approximate)',
        ssSource: fromColumn ? 'category' : 'torsion',
      };
    }
    case 'category': {
      const universe =
        args.categoryUniverse ?? points.map((p) => p.category).filter((c): c is string => c !== null);
      const colours = stableColorMap(universe, theme.categorical);
      const buckets = bucket(points, (p) => p.category ?? 'none');
      const groups: Group[] = [];
      for (const label of colours.universe) {
        const members = buckets.get(label);
        if (members) groups.push({ key: label, label, colour: colours.get(label), members });
      }
      // A category absent from the universe still gets a (hashed) colour.
      for (const [label, members] of buckets) {
        if (label === 'none' || colours.universe.includes(label)) continue;
        groups.push({ key: label, label, colour: colours.get(label), members });
      }
      const capped = capGroups(groups, MAX_LEGEND_GROUPS, theme.neutral);
      const none = buckets.get('none');
      if (none) {
        capped.push({ key: '\u0000none', label: 'No annotation', colour: theme.neutral, members: none });
      }
      return { groups: capped, legendTitle: args.categoryLabel || 'Category', ssSource: null };
    }
    case 'chain': {
      const chains = Array.from(new Set(points.map((p) => p.chain || '-')));
      const colours = stableColorMap(chains, theme.categorical);
      const buckets = bucket(points, (p) => p.chain || '-');
      const groups: Group[] = [];
      for (const label of colours.universe) {
        const members = buckets.get(label);
        if (members) groups.push({ key: label, label, colour: colours.get(label), members });
      }
      return {
        groups: capGroups(groups, MAX_LEGEND_GROUPS, theme.neutral),
        legendTitle: 'Chain',
        ssSource: null,
      };
    }
    default:
      return { groups: [], legendTitle: '', ssSource: null };
  }
}

// ---------------------------------------------------------------------------
// Traces
// ---------------------------------------------------------------------------

/** The tooltip of one residue. Lines the point has nothing for are left out. */
export function hoverText(
  p: AnnotatedPoint,
  opts: {
    bfactorLabel: 'pLDDT' | 'B-factor';
    plddtFractional: boolean;
    valueLabel?: string | null;
    categoryLabel?: string | null;
  },
): string {
  const lines = [`<b>${esc(p.resName)} ${esc(positionLabel(p))}</b>`];
  if (p.chain) lines.push(`Chain ${esc(p.chain)}`);
  lines.push(`φ ${degrees(p.phi)}, ψ ${degrees(p.psi)}`);
  lines.push(CLASS_LABELS[p.cls]);
  if (p.bfactor !== null) {
    // Some predictors write pLDDT as 0-1; show it on the usual 0-100 scale.
    const shown =
      opts.bfactorLabel === 'pLDDT' && opts.plddtFractional ? p.bfactor * 100 : p.bfactor;
    lines.push(`${opts.bfactorLabel} ${formatNumber(shown)}`);
  }
  if (p.value !== null) lines.push(`${esc(opts.valueLabel || 'Value')}: ${formatNumber(p.value)}`);
  if (p.category !== null) {
    lines.push(`${esc(opts.categoryLabel || 'Category')}: ${esc(p.category)}`);
  }
  return lines.join('<br>');
}

/** Members in drawing order: general residues first, so glycine, proline and
 *  pre-proline are drawn on top, and a group's first point (which the legend
 *  swatch copies) is its most ordinary residue. */
function drawingOrder(points: readonly AnnotatedPoint[], members: readonly number[]): number[] {
  return [...members].sort((a, b) => CLASS_RANK[points[a].cls] - CLASS_RANK[points[b].cls] || a - b);
}

function selectionStyle(args: FigureArgs, order: readonly number[]): Trace {
  const { highlight, points } = args;
  if (!highlight) return {};
  const selected: number[] = [];
  order.forEach((idx, j) => {
    if (inRange(points[idx], highlight)) selected.push(j);
  });
  return {
    selectedpoints: selected,
    selected: { marker: { opacity: 1 } },
    unselected: { marker: { opacity: 0.18 } },
  };
}

function baseTrace(args: FigureArgs, order: readonly number[]): Trace {
  const { points } = args;
  const hoverOpts = {
    bfactorLabel: args.bfactorLabel,
    plddtFractional: args.plddtFractional,
    valueLabel: args.valueLabel,
    categoryLabel: args.categoryLabel,
  };
  return {
    type: 'scatter',
    mode: 'markers',
    x: order.map((i) => points[i].phi),
    y: order.map((i) => points[i].psi),
    // Index into `points`: the handlers find the residue from it.
    customdata: [...order],
    text: order.map((i) => hoverText(points[i], hoverOpts)),
    hovertemplate: '%{text}<extra></extra>',
    ...selectionStyle(args, order),
  };
}

function markerOf(args: FigureArgs, order: readonly number[], colour: unknown): Trace {
  return {
    color: colour,
    size: args.markerSize,
    symbol: order.map((i) => CLASS_SYMBOLS[args.points[i].cls]),
    opacity: 0.85,
    line: { width: 0 },
  };
}

function groupTrace(args: FigureArgs, group: Group): { trace: Trace; order: number[] } {
  const order = drawingOrder(args.points, group.members);
  return {
    order,
    trace: {
      ...baseTrace(args, order),
      // Plotly reads legend text as HTML-ish markup: a category called `<b>`
      // must stay a label.
      name: esc(group.label),
      legendgroup: group.key,
      showlegend: true,
      marker: markerOf(args, order, group.colour),
    },
  };
}

/** One trace coloured along a continuous scale, plus a neutral one for the
 *  residues without a value. */
function valueTraces(args: FigureArgs): { traces: Trace[]; orders: number[][]; legendTitle: string } {
  const { points, theme } = args;
  const withValue: number[] = [];
  const without: number[] = [];
  points.forEach((p, i) => (p.value === null ? without : withValue).push(i));
  const title = args.valueLabel || 'Value';
  const traces: Trace[] = [];
  const orders: number[][] = [];
  if (withValue.length) {
    const order = drawingOrder(points, withValue);
    const values = order.map((i) => points[i].value as number);
    let cmin = Infinity;
    let cmax = -Infinity;
    for (const v of values) {
      if (v < cmin) cmin = v;
      if (v > cmax) cmax = v;
    }
    if (cmax <= cmin) cmax = cmin + 1;
    traces.push({
      ...baseTrace(args, order),
      name: title,
      showlegend: false,
      marker: {
        ...markerOf(args, order, values),
        colorscale: theme.valueScale ?? 'Viridis',
        cmin,
        cmax,
        showscale: true,
        colorbar: {
          title: { text: esc(title) },
          thickness: 12,
          len: 0.55,
          y: 1,
          yanchor: 'top',
        },
      },
    });
    orders.push(order);
  }
  if (without.length) {
    const group: Group = {
      key: '\u0000none',
      label: 'No value',
      colour: theme.neutral,
      members: without,
    };
    const { trace, order } = groupTrace(args, group);
    traces.push(trace);
    orders.push(order);
  }
  return { traces, orders, legendTitle: title };
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

function regionShapes(args: FigureArgs): { shapes: Trace[]; annotations: Trace[] } {
  const { theme } = args;
  const set = regionSet(args.regionSet);
  const name = `Favoured regions (${REGION_SET_LABELS[args.regionSet]}):<br>${REGION_NOTE.replace(', ', ',<br>')}`;
  const annotations: Trace[] = [];
  for (const region of set) {
    if (!region.labelled) continue;
    const [x, y] = labelAnchor(region.polygon);
    annotations.push({
      x,
      y,
      xref: 'x',
      yref: 'y',
      text: REGION_LABELS[region.name],
      showarrow: false,
      font: { size: 11, color: theme.dimmed },
    });
  }
  // One shape for the whole set (a path of one closed sub-path per polygon), so
  // its single legend entry shows and hides every polygon together. The
  // polygons of a set do not overlap, so the fill rule is immaterial.
  const shape: Trace = {
    type: 'path',
    path: set.map((region) => polygonPath(region.polygon)).join(''),
    xref: 'x',
    yref: 'y',
    layer: 'below',
    fillcolor: theme.accentFill,
    fillrule: 'nonzero',
    line: { color: theme.accent, width: 0.8, dash: 'dot' },
    legendgroup: 'regions',
    showlegend: true,
    name,
  };
  return { shapes: [shape], annotations };
}

function axis(title: string, theme: FigureTheme): Trace {
  return {
    title: { text: title, standoff: 6 },
    range: [...ANGLE_RANGE],
    tickmode: 'array',
    tickvals: [...TICKS],
    ticksuffix: '°',
    showgrid: true,
    gridcolor: theme.grid,
    // The axes cross at the origin: the lines through (0, 0) split the four
    // quadrants a Ramachandran plot is read in.
    zeroline: true,
    zerolinecolor: theme.zeroLine,
    zerolinewidth: 1.2,
    showline: true,
    linecolor: theme.grid,
    mirror: true,
    constrain: 'domain',
    automargin: true,
  };
}

/** The figure of a Ramachandran plot. */
export function buildFigure(args: FigureArgs): BuiltFigure {
  const { points, theme } = args;
  const data: Trace[] = [];
  const members: number[][] = [];
  let legendTitle: string;
  let ssSource: BuiltFigure['ssSource'] = null;
  let continuous = false;

  if (args.mode === 'value') {
    const built = valueTraces(args);
    data.push(...built.traces);
    members.push(...built.orders);
    legendTitle = built.legendTitle;
    continuous = built.traces.some((t) => (t.marker as Trace).showscale === true);
  } else {
    const grouping = groupPoints(args);
    legendTitle = grouping.legendTitle;
    ssSource = grouping.ssSource;
    for (const group of grouping.groups) {
      const { trace, order } = groupTrace(args, group);
      data.push(trace);
      members.push(order);
    }
  }

  const { shapes, annotations } = args.showRegions
    ? regionShapes(args)
    : { shapes: [], annotations: [] };

  const highlighted = args.highlight
    ? points.reduce((n, p) => n + (inRange(p, args.highlight as HighlightRange) ? 1 : 0), 0)
    : 0;

  const layout: Record<string, unknown> = {
    // The top margin keeps the legend clear of the modebar that appears on hover.
    margin: { l: 56, r: 12, t: 30, b: 48 },
    xaxis: axis('φ (degrees)', theme),
    yaxis: { ...axis('ψ (degrees)', theme), scaleanchor: 'x', scaleratio: 1 },
    shapes,
    annotations,
    showlegend: true,
    legend: {
      // In `value` mode the colour bar carries the title; a legend heading over
      // the regions entry alone would only repeat it.
      title: { text: args.mode === 'value' ? '' : legendTitle },
      x: 1.02,
      xanchor: 'left',
      // A colour bar owns the top of the right margin in `value` mode.
      y: continuous ? 0.4 : 1,
      yanchor: 'top',
      font: { size: 10 },
      itemsizing: 'constant',
    },
    hovermode: 'closest',
    dragmode: args.dragmode,
    uirevision: args.uirevision,
    selectionrevision: args.selectionrevision,
    autosize: true,
  };

  return { data, layout, legendTitle, ssSource, members, highlighted };
}

/**
 * A ring around the residues in `target`, drawn over the finished figure.
 *
 * Kept apart from `buildFigure` so a hover from another tile (dozens of events
 * a second) only appends or replaces this one small trace and never rebuilds
 * the thousands of points under it.
 */
export function residueRing(
  points: readonly Pick<AnnotatedPoint, 'chain' | 'position' | 'phi' | 'psi'>[],
  target: HighlightRange | null,
  highlightColour: string,
  markerSize: number,
): Trace | null {
  if (!target) return null;
  const hit = points.filter((p) => inRange(p, target));
  if (hit.length === 0) return null;
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'highlight',
    x: hit.map((p) => p.phi),
    y: hit.map((p) => p.psi),
    hoverinfo: 'skip',
    showlegend: false,
    // A box or lasso over the plot must not dim the ring with the points it
    // is not part of.
    selected: { marker: { opacity: 1 } },
    unselected: { marker: { opacity: 1 } },
    marker: {
      symbol: 'circle-open',
      size: markerSize + 8,
      color: highlightColour,
      line: { width: 2, color: highlightColour },
    },
  };
}

/** The line under the title: what is plotted and how much of it sits inside the
 *  approximate favoured regions. */
export function summaryLine(args: {
  entity: string | null;
  plotted: number;
  withoutTorsions: number;
  /** Inside / outside the approximate regions; null when they are not shown. */
  favoured: { inside: number; outside: number } | null;
  selection: { start: number; end: number } | null;
}): string {
  const parts: string[] = [];
  if (args.entity) parts.push(args.entity);
  parts.push(`${args.plotted} residues`);
  if (args.withoutTorsions > 0) parts.push(`${args.withoutTorsions} without φ/ψ`);
  if (args.favoured && args.plotted > 0) {
    parts.push(
      `${args.favoured.inside} inside / ${args.favoured.outside} outside the approximate favoured regions`,
    );
  }
  if (args.selection) {
    parts.push(
      args.selection.start === args.selection.end
        ? `residue ${args.selection.start}`
        : `residues ${args.selection.start}-${args.selection.end}`,
    );
  }
  return parts.join(' · ');
}
