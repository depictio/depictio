/**
 * Analysis mode groups, as a MultiQC tile reads them.
 *
 * A MultiQC tile is drawn by the server from a report, so a group cannot
 * recolour its marks in the browser the way an advanced viz does. What it can
 * do is narrow the report to a group's samples, which is a sample filter the
 * render route already resolves (`_resolve_multiqc_sample_filter`, also across
 * a declared link and, for the "Other" panel, as a complement). So:
 *
 *  - Split: one panel per group, each the tile built from that group's
 *    samples (the same path as the "What's new" split).
 *  - Overlay on General Stats: one table, its rows banded by group. Which row
 *    belongs to which group is read off the same per-group render, so the
 *    banding and the Split can never disagree about a sample.
 *  - Overlay on a plot: the same per-group renders say which of the plot's
 *    samples each group holds, and the plot is drawn whole with the groups on
 *    top: a line per sample takes its group's colour, a bar per sample gets
 *    a strip of its group's colour beside its label. A plot with no mark
 *    per sample (a heatmap) is drawn as it was and says so.
 *
 * Everything here is pure, so the decisions are testable without a render.
 */

import type { InteractiveFilter } from '../../api';
import { MAX_PANELS, panelsForGrouping } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import type { GroupRenderState } from '../../selectionGroups';
import { isRunGroup } from '../advanced_viz/groupsForDc';
import { GROUP_UNREACHABLE_REASON } from '../../groupStatus';
import { sampleIdsForTrace } from '../../annotations/multiqc';
import { OTHER_COLOR } from '../../splitPanels';

/** Why a MultiQC tile was drawn whole although groups are on. */
export type MultiQCGroupDecline = 'too_many' | 'overlay_plot' | 'unreachable';

export type MultiQCGroupPlan =
  /** Nothing to do: no groups, or groups of runs (the "What's new" split owns those). */
  | { kind: 'none' }
  /** One panel per group. */
  | { kind: 'split'; panels: PanelSpec[] }
  /** A single panel: the tile narrowed to it, as a lone "New only" side is. */
  | { kind: 'filter'; panel: PanelSpec }
  /** General Stats only: one table, its rows banded by these panels. */
  | { kind: 'bands'; panels: PanelSpec[]; showOther: boolean }
  /** A plot: drawn whole, the groups drawn on top of its marks. */
  | { kind: 'overlay'; panels: PanelSpec[]; showOther: boolean }
  /** Groups are on and this tile cannot honour them. */
  | { kind: 'declined'; reason: MultiQCGroupDecline; panelCount?: number };

/** An "Other" panel: the samples in none of the groups. */
export function isOtherPanel(panel: PanelSpec): boolean {
  return panel.constraints.some(
    (c) =>
      Boolean((c.metadata as { exclude?: unknown } | undefined)?.exclude) ||
      Boolean((c as { exclude?: unknown }).exclude),
  );
}

function groupsAreOn(groupRender: GroupRenderState | undefined): groupRender is GroupRenderState {
  if (!groupRender) return false;
  const groups = groupRender.groups ?? [];
  // The groups of "What's new" are the news split's business, not Analysis mode's.
  if (groups.length > 0 && groups.every(isRunGroup)) return false;
  if (groupRender.colorByGroup) return groups.length > 0;
  return Boolean(groupRender.colorByColumn);
}

/**
 * What Analysis mode asks of one MultiQC tile.
 *
 * `groupRender` is the dashboard's resolved state (already translated to the
 * tile's collection where the project's links allow it). `isGeneralStats`
 * picks the Overlay behaviour: banded rows for the table, declined for a plot.
 */
export function planMultiQCGroups(
  groupRender: GroupRenderState | undefined,
  filters: readonly InteractiveFilter[],
  isGeneralStats: boolean,
): MultiQCGroupPlan {
  if (!groupsAreOn(groupRender)) return { kind: 'none' };

  if (groupRender.display === 'facet') {
    const panels = panelsForGrouping(groupRender, filters);
    if (panels.length === 0) return { kind: 'none' };
    if (panels.length === 1) return { kind: 'filter', panel: panels[0] };
    if (panels.length > MAX_PANELS) {
      return { kind: 'declined', reason: 'too_many', panelCount: panels.length };
    }
    return { kind: 'split', panels };
  }

  // Overlay.
  // The bands are the groups' own panels; "Other" is whatever no band claims,
  // so an "Other" panel from the split is not asked for here.
  const panels = panelsForGrouping({ ...groupRender, display: 'facet', showOverall: false }, filters).filter(
    (p) => !isOtherPanel(p),
  );
  if (panels.length === 0) return { kind: 'none' };
  if (panels.length > MAX_PANELS) {
    return { kind: 'declined', reason: 'too_many', panelCount: panels.length };
  }
  const showOther = groupRender.showOther !== false;
  return isGeneralStats ? { kind: 'bands', panels, showOther } : { kind: 'overlay', panels, showOther };
}

/** The badge label of a tile drawn whole although groups are on. */
export const MULTIQC_NOT_GROUPED_LABEL = 'not grouped';

function sentence(reason: string): string {
  return `${reason.charAt(0).toUpperCase()}${reason.slice(1)}.`;
}

/** Hover lines for the "not grouped" badge of a MultiQC tile. */
export function multiqcDeclineReasons(reason: MultiQCGroupDecline, panelCount?: number): string[] {
  switch (reason) {
    case 'too_many':
      return [
        sentence(
          `the groups would make ${panelCount ?? 'too many'} panels, and at most ${MAX_PANELS} stay readable, so this tile is drawn whole`,
        ),
      ];
    case 'overlay_plot':
      return [
        sentence(
          'this plot draws no mark per sample to colour (a heatmap of the samples, say), so it is drawn whole; Split shows one plot per group',
        ),
      ];
    case 'unreachable':
      return [sentence(GROUP_UNREACHABLE_REASON.replace('this one', "this report's samples"))];
  }
}

/**
 * A cheap fingerprint of a rendered figure, enough to tell "this panel was
 * narrowed" from "every panel got the whole report". Each trace contributes its
 * name, type, length and end points, so a panel with fewer samples differs
 * from one with all of them.
 */
export function figureSignature(data: unknown[] | undefined | null): string {
  if (!data) return '';
  return data
    .map((raw) => {
      const t = (raw ?? {}) as Record<string, unknown>;
      const part = (axis: unknown): string => {
        if (!Array.isArray(axis)) return '-';
        const n = axis.length;
        return n === 0 ? '0' : `${n}:${String(axis[0])}:${String(axis[n - 1])}`;
      };
      // A line plot narrowed by a sample filter keeps every trace and hides the
      // others (`visible: false`): what is hidden is part of what was drawn.
      return [t.type, t.name, t.visible === false ? 'hidden' : '', part(t.x), part(t.y), part(t.z)].join('|');
    })
    .join('~');
}

/** Whether every entry is present and the same: all panels drew one picture. */
export function allIdentical(signatures: ReadonlyArray<string | null | undefined>): boolean {
  if (signatures.length < 2) return false;
  if (signatures.some((s) => s == null)) return false;
  return signatures.every((s) => s === signatures[0]);
}

export interface BandedRow<T> {
  row: T;
  /** Index into the bands, or `bands.length` for "Other". */
  band: number;
}

/**
 * Order rows by group and say which group each belongs to.
 *
 * `members[i]` is the sample set of band `i`. A row in several bands takes the
 * first (the server's rule for a sample in two groups). Rows keep their given
 * order within a band, so a column sort applies inside each group. Rows in no
 * band are "Other", last, and dropped when `showOther` is false.
 */
export function bandRows<T>(
  rows: readonly T[],
  sampleOf: (row: T) => string | null,
  members: ReadonlyArray<ReadonlySet<string>>,
  showOther: boolean,
): BandedRow<T>[] {
  const buckets: T[][] = Array.from({ length: members.length + 1 }, () => []);
  for (const row of rows) {
    const sample = sampleOf(row);
    let band = members.length;
    if (sample != null) {
      const hit = members.findIndex((set) => set.has(sample));
      if (hit >= 0) band = hit;
    }
    buckets[band].push(row);
  }
  const out: BandedRow<T>[] = [];
  buckets.forEach((bucket, band) => {
    if (band === members.length && !showOther) return;
    for (const row of bucket) out.push({ row, band });
  });
  return out;
}

/**
 * Did the groups reach this table? Not when no sample of it landed in a band,
 * nor (with two bands or more) when every band holds every sample: the group
 * constraints then narrowed nothing, as when no declared link reaches the
 * report's samples, and a banding would be a fiction.
 */
export function bandsReach(samples: readonly string[], members: ReadonlyArray<ReadonlySet<string>>): boolean {
  if (samples.length === 0 || members.length === 0) return false;
  const counts = members.map((set) => samples.filter((s) => set.has(s)).length);
  if (counts.every((n) => n === 0)) return false;
  if (members.length >= 2 && counts.every((n) => n === samples.length)) return false;
  return true;
}

/** The samples a rendered MultiQC figure draws, in the plot's own naming. */
export function figureSamples(data: readonly unknown[] | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const raw of data ?? []) {
    const ids = sampleIdsForTrace(raw as Record<string, unknown> | null);
    for (const id of ids ?? []) if (id != null) out.add(String(id));
  }
  return out;
}

export interface FigureOverlayGroup {
  name: string;
  color?: string;
  /** The group's samples as this plot names them (`figureSamples` of its render). */
  members: ReadonlySet<string>;
}

export type FigureOverlay =
  | { data: unknown[]; layout: Record<string, unknown> }
  /** `unreachable`: no drawn sample is in a group; `unsupported`: no mark per sample. */
  | { failed: 'unreachable' | 'unsupported' };

const LINE_TYPES = new Set(['scatter', 'scattergl', 'box', 'violin']);
/** The group strip beside a bar's label, and its gap to the axis, in px. */
const STRIP_PX = 6;
const STRIP_GAP_PX = 3;
/** Legend entries the overlay adds, one per group: never samples themselves. */
export const GROUP_LEGEND_GROUP = 'depictio-analysis-groups';

function axisKey(ref: unknown, letter: 'x' | 'y'): string {
  const r = typeof ref === 'string' && ref.startsWith(letter) ? ref.slice(1) : '';
  return `${letter}axis${r}`;
}

/**
 * The plot drawn whole, with the analysis groups on top of its marks.
 *
 * A trace per sample (a FastQC line, a box) takes its group's colour; one in
 * no group is grey ("Other"), or hidden when Other is off. A bar per sample
 * (MultiQC's bar graphs, samples on the category axis) keeps its category
 * colours, which are the plot's own meaning: its group is a strip of a few
 * pixels between its label and the axis, as a heatmap annotates its rows, and
 * the labels step aside for it. Either way a legend entry per group says what
 * the colours are.
 */
export function overlayGroupsOnFigure(
  data: readonly unknown[],
  layout: Record<string, unknown>,
  groups: readonly FigureOverlayGroup[],
  showOther: boolean,
): FigureOverlay {
  const groupOf = (sample: unknown): number =>
    sample == null ? -1 : groups.findIndex((g) => g.members.has(String(sample)));
  let perSample = false;
  let matched = false;
  const shapes: Record<string, unknown>[] = [];
  const outLayout: Record<string, unknown> = { ...layout };
  const banded = new Set<string>();

  const outData = data.map((raw) => {
    const t = raw as Record<string, unknown> | null;
    if (!t || typeof t !== 'object') return raw;
    const type = typeof t.type === 'string' ? t.type : 'scatter';
    const ids = sampleIdsForTrace(t);
    if (!ids) return raw;
    if (type === 'bar') {
      const horizontal = t.orientation === 'h';
      const catAxis = axisKey(horizontal ? t.yaxis : t.xaxis, horizontal ? 'y' : 'x');
      if (banded.has(catAxis)) return raw;
      banded.add(catAxis);
      perSample = true;
      const catRef = catAxis.replace('axis', '');
      const axis = (layout[catAxis] ?? {}) as Record<string, unknown>;
      // Room for the strip between the labels and the axis.
      outLayout[catAxis] = { ...axis, ticklabelstandoff: STRIP_GAP_PX + STRIP_PX + 4 };
      const declared = Array.isArray(axis.categoryarray) ? (axis.categoryarray as unknown[]) : null;
      const order = (declared ?? ids).map((v) => String(v));
      order.forEach((sample, pos) => {
        const g = groupOf(sample);
        if (g < 0) return;
        matched = true;
        const color = groups[g].color ?? OTHER_COLOR;
        // Pixel-sized against the axis, so the strip keeps its width whatever
        // the tile's; a hair narrower than the bar, so neighbours stay apart.
        const strip = horizontal
          ? { yref: catRef, y0: pos - 0.42, y1: pos + 0.42, xref: 'paper', xsizemode: 'pixel', xanchor: 0, x0: -(STRIP_GAP_PX + STRIP_PX), x1: -STRIP_GAP_PX }
          : { xref: catRef, x0: pos - 0.42, x1: pos + 0.42, yref: 'paper', ysizemode: 'pixel', yanchor: 0, y0: -(STRIP_GAP_PX + STRIP_PX), y1: -STRIP_GAP_PX };
        shapes.push({ type: 'rect', layer: 'above', line: { width: 0 }, fillcolor: color, ...strip });
      });
      return raw;
    }
    if (!LINE_TYPES.has(type)) return raw;
    perSample = true;
    const g = groupOf(t.name);
    if (g >= 0) matched = true;
    if (g < 0 && !showOther) return { ...t, visible: false, showlegend: false };
    const color = g >= 0 ? (groups[g].color ?? OTHER_COLOR) : OTHER_COLOR;
    return {
      ...t,
      line: { ...((t.line as Record<string, unknown>) ?? {}), color },
      marker: { ...((t.marker as Record<string, unknown>) ?? {}), color },
      ...(g < 0 ? { opacity: 0.45 } : {}),
      showlegend: false,
    };
  });

  if (!perSample) return { failed: 'unsupported' };
  if (!matched) return { failed: 'unreachable' };

  const legend = groups.map((g) => ({
    type: 'scatter',
    mode: 'markers',
    x: [null],
    y: [null],
    name: g.name,
    marker: { color: g.color ?? OTHER_COLOR, symbol: 'square', size: 10 },
    legendgroup: GROUP_LEGEND_GROUP,
    showlegend: true,
    hoverinfo: 'skip',
  }));
  if (shapes.length > 0) {
    const existing = Array.isArray(layout.shapes) ? (layout.shapes as unknown[]) : [];
    outLayout.shapes = [...existing, ...shapes];
  }
  outLayout.showlegend = true;
  return { data: [...outData, ...legend], layout: outLayout };
}
