/**
 * Pure model of the `secondary_structure` tile: the per-residue rows of one
 * protein turned into one state array per prediction source, all aligned on the
 * same ascending positions, and what the tile derives from them (segments,
 * composition, agreement between sources, per-residue confidence, tooltip
 * lines). No DOM, no React, unit-tested in `ssModel.test.ts`.
 *
 * A state is one of the four classes of `SecondaryStructure` (helix, strand,
 * turn, coil), read through `secondaryStructureOf` so DSSP letters (H G I P E
 * B T S C L -) and plain words (Helix, Strand, Coil...) all land in the same
 * place. Agreement is Q3-style: the three states H / E / C, a turn counting as
 * coil, the way a DSSP eight-state call is reduced before it is compared with a
 * three-state predictor such as S4PRED.
 */

import { numberOrNull, rowIndicesWhere, stringOrNull } from '../protein/rendererData';
import type { SecondaryStructure } from '../protein/residueColours';
import { runsOf, secondaryStructureOf, type Run } from '../protein/sequence';
import type { StripResidue } from '../protein/types';

export type SsFrame = Record<string, unknown[]>;

/** The columns the model reads; `null` is a column the tile does not have. */
export interface SsColumns {
  entity: string | null;
  position: string;
  residue: string | null;
  state: string;
  source: string | null;
  pHelix: string | null;
  pStrand: string | null;
  pCoil: string | null;
  confidence: string | null;
}

/** Name of the one source of a table with no source column. */
export const DEFAULT_SOURCE = 'Structure';
/** Name given to rows whose source cell is empty, when a source column is bound. */
export const UNKNOWN_SOURCE = 'unknown';

export interface SsSource {
  name: string;
  /** Class of each residue, aligned on `SsModel.positions`; null where this
   *  source has no row or a state that is not a class. */
  states: (SecondaryStructure | null)[];
  /** The state cell as it was written (`H`, `Helix`...), aligned on positions. */
  codes: (string | null)[];
  pHelix: (number | null)[];
  pStrand: (number | null)[];
  pCoil: (number | null)[];
  /** Confidence 0 to 1: the bound column, else the largest probability, else
   *  null (the residue is drawn opaque). */
  confidence: (number | null)[];
  /** The source carries at least one probability. */
  hasProbabilities: boolean;
  /** The confidence comes from a bound column rather than the probabilities. */
  explicitConfidence: boolean;
}

export interface SsModel {
  /** Every position any source has a row for, ascending. */
  positions: number[];
  /** Position to its index in `positions` and in every source's arrays. */
  index: Map<number, number>;
  /** One-letter residue, aligned on positions (first source that has it). */
  letters: (string | null)[];
  /** Source names in order of first appearance in the table. */
  names: string[];
  /** The sources, the main one (the reference) first. */
  sources: SsSource[];
  /** At least one residue has a state in some source. */
  hasStates: boolean;
}

export const EMPTY_MODEL: SsModel = {
  positions: [],
  index: new Map(),
  letters: [],
  names: [],
  sources: [],
  hasStates: false,
};

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

/**
 * The divisor that brings an explicit confidence column onto 0 to 1: 1 for a
 * column already there, 100 for one that reads like a percentage or a pLDDT
 * (largest value above 1, none above 100). A column with a value past 100 is
 * left as it is and clamped.
 */
export function confidenceScale(values: ReadonlyArray<number | null | undefined>): number {
  let max = -Infinity;
  for (const v of values) {
    if (v != null && Number.isFinite(v) && v > max) max = v;
  }
  return max > 1 && max <= 100 ? 100 : 1;
}

/**
 * Confidence of one residue: the bound column's value (already on 0 to 1), else
 * the largest of the three probabilities, else null.
 */
export function resolveConfidence(
  explicit: number | null,
  pHelix: number | null,
  pStrand: number | null,
  pCoil: number | null,
): number | null {
  if (explicit != null && Number.isFinite(explicit)) return clamp01(explicit);
  let best: number | null = null;
  for (const p of [pHelix, pStrand, pCoil]) {
    if (p != null && Number.isFinite(p) && (best == null || p > best)) best = p;
  }
  return best == null ? null : clamp01(best);
}

/** The source named `reference` (exact, else ignoring case and spacing), or null. */
function findReference(names: readonly string[], reference: string | null | undefined): string | null {
  if (!reference) return null;
  if (names.includes(reference)) return reference;
  const wanted = reference.trim().toLowerCase();
  return names.find((n) => n.trim().toLowerCase() === wanted) ?? null;
}

/**
 * Build the model of one entity from a column-oriented frame.
 *
 * Rows of the frame are grouped by `cols.source` (one source when it is null or
 * missing from the frame), in order of first appearance; the main source, the
 * one the agreement is measured against, is `reference` when the table has it,
 * else the first. Where a source lists a position twice the first row wins.
 * `entity` null keeps every row (the table holds one protein, or the server
 * already scoped it).
 */
export function buildSsModel(
  frame: SsFrame | null | undefined,
  cols: SsColumns,
  entity: string | null,
  reference?: string | null,
): SsModel {
  if (!frame) return EMPTY_MODEL;
  const posCol = frame[cols.position];
  if (!posCol) return EMPTY_MODEL;
  const stateCol = frame[cols.state];
  const sourceCol = cols.source ? frame[cols.source] : undefined;
  const letterCol = cols.residue ? frame[cols.residue] : undefined;
  const pH = cols.pHelix ? frame[cols.pHelix] : undefined;
  const pS = cols.pStrand ? frame[cols.pStrand] : undefined;
  const pC = cols.pCoil ? frame[cols.pCoil] : undefined;
  const confCol = cols.confidence ? frame[cols.confidence] : undefined;

  // source name -> position -> row of the frame
  const bySource = new Map<string, Map<number, number>>();
  for (const row of rowIndicesWhere(frame, cols.entity, entity)) {
    const p = numberOrNull(posCol[row]);
    if (p == null) continue;
    const name = sourceCol ? (stringOrNull(sourceCol[row]) ?? UNKNOWN_SOURCE) : DEFAULT_SOURCE;
    let cells = bySource.get(name);
    if (!cells) {
      cells = new Map();
      bySource.set(name, cells);
    }
    if (!cells.has(p)) cells.set(p, row);
  }
  const names = Array.from(bySource.keys());
  if (names.length === 0) return EMPTY_MODEL;
  const main = findReference(names, reference) ?? names[0];
  const order = [main, ...names.filter((n) => n !== main)];

  const all = new Set<number>();
  for (const cells of bySource.values()) for (const p of cells.keys()) all.add(p);
  const positions = Array.from(all).sort((a, b) => a - b);
  const index = new Map<number, number>();
  positions.forEach((p, i) => index.set(p, i));
  const n = positions.length;
  const letters: (string | null)[] = new Array(n).fill(null);

  let hasStates = false;
  const sources = order.map<SsSource>((name) => {
    const cells = bySource.get(name) as Map<number, number>;
    const states: (SecondaryStructure | null)[] = new Array(n).fill(null);
    const codes: (string | null)[] = new Array(n).fill(null);
    const pHelix: (number | null)[] = new Array(n).fill(null);
    const pStrand: (number | null)[] = new Array(n).fill(null);
    const pCoil: (number | null)[] = new Array(n).fill(null);
    const explicit: (number | null)[] = new Array(n).fill(null);
    for (const [p, row] of cells) {
      const k = index.get(p) as number;
      const code = stateCol ? stringOrNull(stateCol[row]) : null;
      codes[k] = code;
      states[k] = secondaryStructureOf(code);
      if (states[k]) hasStates = true;
      if (pH) pHelix[k] = numberOrNull(pH[row]);
      if (pS) pStrand[k] = numberOrNull(pS[row]);
      if (pC) pCoil[k] = numberOrNull(pC[row]);
      if (confCol) explicit[k] = numberOrNull(confCol[row]);
      if (letterCol && letters[k] == null) letters[k] = stringOrNull(letterCol[row]);
    }
    const scale = confidenceScale(explicit);
    const explicitConfidence = explicit.some((v) => v != null);
    const confidence = positions.map((_, k) =>
      resolveConfidence(
        explicit[k] != null ? (explicit[k] as number) / scale : null,
        pHelix[k],
        pStrand[k],
        pCoil[k],
      ),
    );
    const hasProbabilities = [pHelix, pStrand, pCoil].some((col) => col.some((v) => v != null));
    return {
      name,
      states,
      codes,
      pHelix,
      pStrand,
      pCoil,
      confidence,
      hasProbabilities,
      explicitConfidence,
    };
  });

  return { positions, index, letters, names, sources, hasStates };
}

/** First and last position the axis reaches, starting at residue 1 for a
 *  sequence numbered from there (as the sequence strip does); null when empty. */
export function spanOf(model: SsModel): { min: number; max: number } | null {
  if (model.positions.length === 0) return null;
  return { min: Math.min(model.positions[0], 1), max: model.positions[model.positions.length - 1] };
}

// ---- runs, segments ----------------------------------------------------------

/** The runs of one source's states: consecutive residues sharing a class; a
 *  position the source has no state for ends a run. */
export function runsOfSource(model: SsModel, sourceIndex = 0): Run<SecondaryStructure>[] {
  const source = model.sources[sourceIndex];
  if (!source) return [];
  const residues: StripResidue[] = model.positions.map((position, i) => ({
    position,
    category: source.states[i],
  }));
  return runsOf(residues, (r) => secondaryStructureOf(r.category));
}

const STATE_LABEL: Readonly<Record<SecondaryStructure, string>> = {
  helix: 'Helix',
  strand: 'Strand',
  turn: 'Turn',
  coil: 'Coil',
};

export function stateLabel(state: SecondaryStructure): string {
  return STATE_LABEL[state];
}

/** Probability the source gives to `state` at residue index `i`: helix, strand
 *  and coil have a column, a turn has none. */
function probabilityOf(source: SsSource, i: number, state: SecondaryStructure): number | null {
  switch (state) {
    case 'helix':
      return source.pHelix[i];
    case 'strand':
      return source.pStrand[i];
    case 'coil':
      return source.pCoil[i];
    default:
      return null;
  }
}

export interface SsSegment {
  state: SecondaryStructure;
  /** First and last residue, inclusive. */
  start: number;
  end: number;
  /** Number of residues. */
  length: number;
  /** Mean over the segment of P(state), else of the confidence; null when the
   *  source carries neither. */
  mean: number | null;
  /** What `mean` averages. */
  meanOf: 'probability' | 'confidence' | null;
}

function meanOver(values: ReadonlyArray<number | null | undefined>): number | null {
  let sum = 0;
  let n = 0;
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue;
    sum += v;
    n++;
  }
  return n ? sum / n : null;
}

/** The segments of one source (every run, coil included), in sequence order. */
export function segmentsOf(model: SsModel, sourceIndex = 0): SsSegment[] {
  const source = model.sources[sourceIndex];
  if (!source) return [];
  return runsOfSource(model, sourceIndex).map((run) => {
    const probs: (number | null)[] = [];
    const confs: (number | null)[] = [];
    for (let p = run.start; p <= run.end; p++) {
      const i = model.index.get(p);
      if (i === undefined) continue;
      probs.push(probabilityOf(source, i, run.value));
      confs.push(source.confidence[i]);
    }
    const meanProb = meanOver(probs);
    const meanConf = meanProb == null ? meanOver(confs) : null;
    return {
      state: run.value,
      start: run.start,
      end: run.end,
      length: run.end - run.start + 1,
      mean: meanProb ?? meanConf,
      meanOf: meanProb != null ? 'probability' : meanConf != null ? 'confidence' : null,
    };
  });
}

/** "Helix 12–30 (19 aa, mean P 0.86)"; the mean of a confidence reads "mean confidence". */
export function segmentLabel(seg: SsSegment): string {
  const span = seg.start === seg.end ? `${seg.start}` : `${seg.start}–${seg.end}`;
  const parts = [`${seg.length} aa`];
  if (seg.mean != null) {
    parts.push(`${seg.meanOf === 'confidence' ? 'mean confidence' : 'mean P'} ${seg.mean.toFixed(2)}`);
  }
  return `${stateLabel(seg.state)} ${span} (${parts.join(', ')})`;
}

// ---- composition -------------------------------------------------------------

export interface SsComposition {
  /** Residues of each class. */
  counts: Record<SecondaryStructure, number>;
  /** Residues with a state. */
  total: number;
  /** Share of each class among the residues with a state, 0 to 1 (0 when none). */
  fractions: Record<SecondaryStructure, number>;
}

const STATES: readonly SecondaryStructure[] = ['helix', 'strand', 'turn', 'coil'];

/** How many residues of one source are in each class. */
export function compositionOf(model: SsModel, sourceIndex = 0): SsComposition {
  const counts: Record<SecondaryStructure, number> = { helix: 0, strand: 0, turn: 0, coil: 0 };
  let total = 0;
  for (const s of model.sources[sourceIndex]?.states ?? []) {
    if (!s) continue;
    counts[s]++;
    total++;
  }
  const fractions = { helix: 0, strand: 0, turn: 0, coil: 0 } as Record<SecondaryStructure, number>;
  if (total) for (const s of STATES) fractions[s] = counts[s] / total;
  return { counts, total, fractions };
}

/** `0.314` as `31.4%`. */
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

/** "H 31.4% · E 12.0% · C 56.6%", a turn added only when the source has one. */
export function compositionSummary(c: SsComposition): string {
  const parts = [`H ${formatPercent(c.fractions.helix)}`, `E ${formatPercent(c.fractions.strand)}`];
  if (c.counts.turn > 0) parts.push(`T ${formatPercent(c.fractions.turn)}`);
  parts.push(`C ${formatPercent(c.fractions.coil)}`);
  return parts.join(' · ');
}

// ---- agreement ---------------------------------------------------------------

export type Q3 = 'helix' | 'strand' | 'coil';

/** The H / E / C state of a class: a turn counts as coil. */
export function q3Of(state: SecondaryStructure | null): Q3 | null {
  if (state == null) return null;
  return state === 'turn' ? 'coil' : state;
}

export type AgreementMark = 'agree' | 'disagree' | null;

export interface SsAgreement {
  /** Per residue, aligned on positions: where the main source has a state and
   *  at least one other source has one too, whether every other source gives
   *  the same H / E / C state; null elsewhere. */
  marks: AgreementMark[];
  agree: number;
  /** Residues that could be compared. */
  compared: number;
  /** `agree / compared`, null when nothing could be compared. */
  fraction: number | null;
  /** Each other source against the main one, residue by residue. */
  perSource: { name: string; agree: number; compared: number; fraction: number | null }[];
}

/**
 * How well the other sources agree with the main one (Q3: helix, strand, coil).
 * Null with a single source, where there is nothing to compare. A residue one
 * source does not cover is simply not compared with it.
 */
export function agreementOf(model: SsModel): SsAgreement | null {
  if (model.sources.length < 2) return null;
  const [main, ...others] = model.sources;
  const n = model.positions.length;
  const marks: AgreementMark[] = new Array(n).fill(null);
  let agree = 0;
  let compared = 0;
  const per = others.map((o) => ({ name: o.name, agree: 0, compared: 0 }));
  for (let i = 0; i < n; i++) {
    const ref = q3Of(main.states[i]);
    if (!ref) continue;
    let seen = 0;
    let same = true;
    for (let k = 0; k < others.length; k++) {
      const q = q3Of(others[k].states[i]);
      if (!q) continue;
      seen++;
      per[k].compared++;
      if (q === ref) per[k].agree++;
      else same = false;
    }
    if (seen === 0) continue;
    compared++;
    if (same) {
      agree++;
      marks[i] = 'agree';
    } else {
      marks[i] = 'disagree';
    }
  }
  return {
    marks,
    agree,
    compared,
    fraction: compared ? agree / compared : null,
    perSource: per.map((p) => ({ ...p, fraction: p.compared ? p.agree / p.compared : null })),
  };
}

/** The agree / disagree marks as runs of consecutive residues. */
export function agreementRuns(
  model: SsModel,
  agreement: SsAgreement | null,
): Run<'agree' | 'disagree'>[] {
  if (!agreement) return [];
  const residues: StripResidue[] = model.positions.map((position, i) => ({
    position,
    category: agreement.marks[i],
  }));
  return runsOf(residues, (r) =>
    r.category === 'agree' || r.category === 'disagree' ? r.category : null,
  );
}

// ---- confidence shading --------------------------------------------------------

/** Opacity of the least confident residue: still readable. */
export const MIN_ALPHA = 0.3;

/** Opacity of a residue of confidence `conf` (0 to 1); null is opaque. */
export function confidenceAlpha(conf: number | null | undefined): number {
  if (conf == null || !Number.isFinite(conf)) return 1;
  return MIN_ALPHA + (1 - MIN_ALPHA) * clamp01(conf);
}

/** `alpha` rounded to the nearest of `levels` steps between MIN_ALPHA and 1. */
export function quantiseAlpha(alpha: number, levels = 5): number {
  if (levels <= 1) return 1;
  const t = (Math.max(MIN_ALPHA, Math.min(1, alpha)) - MIN_ALPHA) / (1 - MIN_ALPHA);
  return MIN_ALPHA + ((1 - MIN_ALPHA) * Math.round(t * (levels - 1))) / (levels - 1);
}

export interface AlphaRun<T> extends Run<T> {
  alpha: number;
}

/**
 * Cut runs into pieces of one opacity each, so a glyph can be drawn clipped to
 * each piece at its own alpha. `alphaAt` gives the opacity of a residue.
 * `perResidue` false keeps one piece per run at the run's mean opacity (the
 * residues are too narrow to tell apart); true splits wherever the opacity,
 * quantised to `levels` steps, changes.
 */
export function alphaRuns<T>(
  runs: readonly Run<T>[],
  alphaAt: (position: number) => number,
  opts: { perResidue: boolean; levels?: number },
): AlphaRun<T>[] {
  const levels = opts.levels ?? 5;
  const out: AlphaRun<T>[] = [];
  for (const run of runs) {
    if (!opts.perResidue) {
      let sum = 0;
      for (let p = run.start; p <= run.end; p++) sum += alphaAt(p);
      out.push({ ...run, alpha: quantiseAlpha(sum / (run.end - run.start + 1), levels) });
      continue;
    }
    let cur: AlphaRun<T> | null = null;
    for (let p = run.start; p <= run.end; p++) {
      const a = quantiseAlpha(alphaAt(p), levels);
      if (cur && cur.alpha === a) {
        cur.end = p;
      } else {
        cur = { start: p, end: p, value: run.value, alpha: a };
        out.push(cur);
      }
    }
  }
  return out;
}

// ---- dense arrays for drawing -----------------------------------------------------

/**
 * `values` (aligned on `model.positions`) spread over the axis `[min, min +
 * count)` as a typed array, NaN where the model has no residue: the panel reads
 * it by `position - min`, with no map lookup in its draw loop.
 */
export function denseByPosition(
  model: SsModel,
  values: ReadonlyArray<number | null | undefined>,
  min: number,
  count: number,
): Float32Array {
  const out = new Float32Array(Math.max(0, count)).fill(NaN);
  model.positions.forEach((p, i) => {
    const k = p - min;
    const v = values[i];
    if (k >= 0 && k < out.length && v != null && Number.isFinite(v)) out[k] = v;
  });
  return out;
}

/** Mean of the finite entries of `values[from..to]` (inclusive), null when none. */
export function meanFinite(values: ArrayLike<number>, from: number, to: number): number | null {
  let sum = 0;
  let n = 0;
  const hi = Math.min(to, values.length - 1);
  for (let i = Math.max(0, from); i <= hi; i++) {
    const v = values[i];
    if (Number.isFinite(v)) {
      sum += v;
      n++;
    }
  }
  return n ? sum / n : null;
}

// ---- tooltip -----------------------------------------------------------------------

function fixed(v: number | null): string {
  return v == null ? '-' : v.toFixed(2);
}

/** The lines of the hover tooltip for one position: residue, the state each
 *  source gives it with its probabilities, and whether the sources agree. */
export function tooltipLines(
  model: SsModel,
  position: number,
  agreement: SsAgreement | null = null,
): string[] {
  const i = model.index.get(position);
  const letter = i === undefined ? null : model.letters[i];
  const lines = [`${letter ? `${letter} ` : ''}${position}`];
  if (i === undefined) return lines;
  const several = model.sources.length > 1;
  for (const source of model.sources) {
    const state = source.states[i];
    const code = source.codes[i];
    const call = state ? stateLabel(state) : code ? code : 'no data';
    lines.push(several ? `${source.name}: ${call}` : call);
    if (source.pHelix[i] != null || source.pStrand[i] != null || source.pCoil[i] != null) {
      lines.push(
        `P  H ${fixed(source.pHelix[i])}  E ${fixed(source.pStrand[i])}  C ${fixed(source.pCoil[i])}`,
      );
    }
    if (source.explicitConfidence && source.confidence[i] != null) {
      lines.push(`Confidence ${fixed(source.confidence[i])}`);
    }
  }
  const mark = agreement?.marks[i];
  if (several && mark) {
    lines.push(mark === 'agree' ? `Agrees with ${model.sources[0].name}` : `Differs from ${model.sources[0].name}`);
  }
  return lines;
}
