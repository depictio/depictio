/**
 * Pure logic of the molecule_3d tile: which entity to show, which rows mark
 * which residues, the numbering check of the variant marks, and the per-residue
 * colouring with its legend. No 3Dmol, no React, so vitest covers it in node.
 */

import type { InteractiveFilter } from '../../../api';
import { stableColorMap } from '../../../colors';
import { sampleColorscale } from '../../../utils/colorScale';
import { filtersExcludingOwnResidue } from '../../../selection';
import { residueKey, toOneLetter, type StructureResidue } from './structureText';
import { entitiesByRowCount } from '../protein/rendererData';
import {
  hydrophobicityColour,
  KYTE_DOOLITTLE,
  PLDDT_BANDS,
  plddtColour,
  plddtIsFractional,
  rgbCss,
  SECONDARY_STRUCTURE_COLOURS,
} from '../protein/residueColours';

// ---------------------------------------------------------------------------
// Bound rows
// ---------------------------------------------------------------------------

/** Column names of the bound residue / variant table, from the config. */
export interface ResidueColumns {
  entity?: string | null;
  chain?: string | null;
  position?: string | null;
  value?: string | null;
  category?: string | null;
  refAa?: string | null;
  altAa?: string | null;
  label?: string | null;
  uniprot?: string | null;
  gene?: string | null;
  sequence?: string | null;
}

export interface ResidueRow {
  /** Row index in the fetched frame. */
  row: number;
  entity: string | null;
  chain: string | null;
  position: number | null;
  value: number | null;
  category: string | null;
  refAa: string | null;
  altAa: string | null;
  label: string | null;
  uniprot: string | null;
  gene: string | null;
  sequence: string | null;
}

function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === '' || s === 'null' || s === 'NaN' ? null : s;
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** The columns to fetch: every bound role, once. */
export function columnsToFetch(cols: ResidueColumns): string[] {
  const out: string[] = [];
  for (const c of Object.values(cols)) {
    if (typeof c === 'string' && c && !out.includes(c)) out.push(c);
  }
  return out;
}

/** Column-oriented frame to typed rows. Columns the frame lacks read as null. */
export function parseResidueRows(
  rows: Record<string, unknown[]> | null | undefined,
  cols: ResidueColumns,
): ResidueRow[] {
  if (!rows) return [];
  const pick = (name: string | null | undefined) => (name ? rows[name] : undefined);
  const lengths = Object.values(rows).map((a) => (Array.isArray(a) ? a.length : 0));
  const n = lengths.length ? Math.max(...lengths) : 0;
  const entity = pick(cols.entity);
  const chain = pick(cols.chain);
  const position = pick(cols.position);
  const value = pick(cols.value);
  const category = pick(cols.category);
  const refAa = pick(cols.refAa);
  const altAa = pick(cols.altAa);
  const label = pick(cols.label);
  const uniprot = pick(cols.uniprot);
  const gene = pick(cols.gene);
  const sequence = pick(cols.sequence);
  const out: ResidueRow[] = new Array(n);
  for (let i = 0; i < n; i += 1) {
    const p = num(position?.[i]);
    out[i] = {
      row: i,
      entity: str(entity?.[i]),
      chain: str(chain?.[i]),
      position: p === null ? null : Math.round(p),
      value: num(value?.[i]),
      category: str(category?.[i]),
      refAa: str(refAa?.[i]),
      altAa: str(altAa?.[i]),
      label: str(label?.[i]),
      uniprot: str(uniprot?.[i]),
      gene: str(gene?.[i]),
      sequence: str(sequence?.[i]),
    };
  }
  return out;
}

/**
 * Distinct entities of the rows, the one with the most rows first (ties keep
 * their first-appearance order). On a variant table that is the protein with
 * the most variants, the one a lollipop sorted by variant count opens on, so
 * the two tiles start on the same protein.
 */
export function distinctEntities(rows: readonly ResidueRow[]): string[] {
  return entitiesByRowCount(rows.map((r) => r.entity));
}

/**
 * The entity the tile shows.
 *
 * In order: the one entity the dashboard filters name on the entity column
 * (another tile's pick, a sidebar selector), the one the reader picked in the
 * tile, the dashboard's agreed `opening` entity (see
 * `highlight/openingEntity.ts`), the entity of the fetched rows with the most
 * rows that has a structure (`distinctEntities` order), the first entity with
 * a structure. `available`
 * is the universe of entities that can be drawn (the indexed_file samples in
 * file mode, the row entities in resolve mode); an entity outside it is never
 * returned.
 */
export function chooseEntity(args: {
  fromFilters: string | null;
  picked: string | null;
  rowEntities: readonly string[];
  available: readonly string[];
  opening?: string | null;
}): string | null {
  const { fromFilters, picked, rowEntities, available, opening = null } = args;
  const has = (e: string | null): e is string => e !== null && available.includes(e);
  if (has(fromFilters)) return fromFilters;
  if (has(picked)) return picked;
  if (has(opening)) return opening;
  for (const e of rowEntities) if (has(e)) return e;
  return available[0] ?? null;
}

/** The rows of one entity; every row when the table has no entity column. */
export function rowsForEntity(
  rows: readonly ResidueRow[],
  entity: string | null,
  hasEntityColumn: boolean,
): ResidueRow[] {
  if (!hasEntityColumn || entity === null) return rows.slice();
  return rows.filter((r) => r.entity === entity);
}

/** What to ask the structure resolver for, from the first row that names
 *  something: UniProt accession, then gene, then sequence. */
export function resolverQuery(
  rows: readonly ResidueRow[],
): { uniprot: string | null; gene: string | null; sequence: string | null } | null {
  let uniprot: string | null = null;
  let gene: string | null = null;
  let sequence: string | null = null;
  for (const r of rows) {
    uniprot = uniprot ?? r.uniprot;
    gene = gene ?? r.gene;
    sequence = sequence ?? r.sequence;
    if (uniprot && gene && sequence) break;
  }
  return uniprot || gene || sequence ? { uniprot, gene, sequence } : null;
}

// ---------------------------------------------------------------------------
// Fetch filters
// ---------------------------------------------------------------------------

/**
 * The filters the bound table is fetched with.
 *
 * - Both halves of this tile's own residue_selection go (it rings its pick
 *   rather than hiding the rest of the protein).
 * - The position half of any other tile's residue_selection goes too: a range
 *   picked in the MSA or the sequence track is a place to look, so the tile
 *   zooms to it and keeps colouring the whole chain. The entity half stays, so
 *   the tile follows the entity another tile picked.
 * - Row selections (table / lasso) on this tile's own position or label column
 *   are emphasised on the marks rather than used to drop the other marks.
 */
export function filtersForMoleculeFetch(
  filters: InteractiveFilter[],
  componentIndex: string,
  emphasisColumns: readonly string[],
): InteractiveFilter[] {
  return filtersExcludingOwnResidue(filters, componentIndex).filter((f) => {
    if (f.source === 'residue_selection' && f.interactive_component_type === 'RangeSlider') {
      return false;
    }
    if (
      (f.source === 'table_selection' || f.source === 'scatter_selection') &&
      emphasisColumns.includes(f.column_name ?? f.metadata?.column_name ?? '')
    ) {
      return false;
    }
    return true;
  });
}

/** Values selected elsewhere on each of `columns` (table or lasso selections). */
export function selectedValuesByColumn(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
  columns: readonly string[],
): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const f of filters) {
    if (f.index === componentIndex) continue;
    if (f.source !== 'table_selection' && f.source !== 'scatter_selection') continue;
    const column = f.column_name ?? f.metadata?.column_name ?? '';
    if (!columns.includes(column) || !Array.isArray(f.value) || f.value.length === 0) continue;
    const set = out.get(column) ?? new Set<string>();
    for (const v of f.value) set.add(String(v));
    out.set(column, set);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Variant marks and the numbering check
// ---------------------------------------------------------------------------

export interface VariantMark {
  row: number;
  chain: string;
  position: number;
  refAa: string | null;
  altAa: string | null;
  category: string | null;
  value: number | null;
  label: string;
  /** Residue name in the structure at this position. */
  structureAa: string;
}

export interface VariantCheck {
  /** Marks whose position exists in the structure and whose reference
   *  residue (when given) matches it. */
  drawn: VariantMark[];
  /** Reference residue differs from the structure's: the table and the model
   *  do not share a numbering, so drawing the mark would point at the wrong
   *  residue. Listed, never drawn. */
  mismatched: VariantMark[];
  /** Position absent from the structure (a truncated model, a construct). */
  outside: VariantMark[];
}

/** HGVS-style protein change: `p.R175H`, `p.R175` when there is no alternate. */
export function proteinChange(
  refAa: string | null,
  position: number,
  altAa: string | null,
): string {
  return `p.${refAa ?? ''}${position}${altAa ?? ''}`;
}

/**
 * The rows that become marks.
 *
 * A row with an alternate residue is a variant. When no alternate column is
 * bound, a row with a category is a mark (a curated site, a domain boundary),
 * unless the category is already what colours the chain, or it is present on
 * most residues: a per-residue annotation such as secondary structure is a
 * colouring, and a sphere on every residue would hide the fold.
 */
export function markRows(
  rows: readonly ResidueRow[],
  opts: { hasAltColumn: boolean; colourMode: ColourMode; residueCount: number },
): ResidueRow[] {
  const positioned = rows.filter((r) => r.position !== null);
  if (opts.hasAltColumn) return positioned.filter((r) => r.altAa !== null);
  if (opts.colourMode === 'category') return [];
  const withCategory = positioned.filter((r) => r.category !== null);
  if (opts.residueCount > 0 && withCategory.length > opts.residueCount / 2) return [];
  return withCategory;
}

function normaliseAa(aa: string | null): string | null {
  if (!aa) return null;
  const t = aa.trim();
  if (!t) return null;
  // `Arg`, `ARG` and `R` are the same residue.
  return t.length === 3 ? toOneLetter(t) : t.toUpperCase();
}

/** Index of the structure residues by chain + position. */
export function indexResidues(residues: readonly StructureResidue[]): {
  byKey: Map<string, StructureResidue>;
  primaryChain: string;
} {
  const byKey = new Map<string, StructureResidue>();
  for (const r of residues) {
    const k = residueKey(r.chain, r.position);
    if (!byKey.has(k)) byKey.set(k, r);
  }
  return { byKey, primaryChain: residues[0]?.chain ?? '' };
}

/** The structure residue a table row points at: its own chain when it names
 *  one, else the structure's first chain, else any chain carrying that number. */
function residueForRow(
  index: ReturnType<typeof indexResidues>,
  residues: readonly StructureResidue[],
  chain: string | null,
  position: number,
): StructureResidue | null {
  if (chain !== null) return index.byKey.get(residueKey(chain, position)) ?? null;
  const primary = index.byKey.get(residueKey(index.primaryChain, position));
  if (primary) return primary;
  return residues.find((r) => r.position === position) ?? null;
}

export function checkVariants(
  rows: readonly ResidueRow[],
  residues: readonly StructureResidue[],
): VariantCheck {
  const index = indexResidues(residues);
  const out: VariantCheck = { drawn: [], mismatched: [], outside: [] };
  for (const r of rows) {
    if (r.position === null) continue;
    const ref = normaliseAa(r.refAa);
    const alt = normaliseAa(r.altAa);
    const residue = residueForRow(index, residues, r.chain, r.position);
    const mark: VariantMark = {
      row: r.row,
      chain: residue?.chain ?? r.chain ?? index.primaryChain,
      position: r.position,
      refAa: ref,
      altAa: alt,
      category: r.category,
      value: r.value,
      label: r.label ?? proteinChange(ref ?? residue?.aa ?? null, r.position, alt),
      structureAa: residue?.aa ?? '',
    };
    if (!residue) out.outside.push(mark);
    else if (ref !== null && ref !== residue.aa) out.mismatched.push(mark);
    else out.drawn.push(mark);
  }
  return out;
}

/** Sphere radius of a mark in Angstrom, scaled by its value when the marks
 *  carry one (VAF, a score), else a fixed size. */
export function markRadius(value: number | null, min: number, max: number): number {
  const BASE = 1.4;
  if (value === null || !Number.isFinite(min) || !Number.isFinite(max) || max <= min) return BASE;
  const t = (value - min) / (max - min);
  return 0.9 + 1.6 * Math.max(0, Math.min(1, t));
}

// ---------------------------------------------------------------------------
// Selection gestures
// ---------------------------------------------------------------------------

/** The range a click makes: a single residue, or with shift the span from the
 *  current anchor to the clicked residue. */
export function clickRange(
  anchor: number | null,
  clicked: number,
  extend: boolean,
): { start: number; end: number } {
  if (extend && anchor !== null) {
    return { start: Math.min(anchor, clicked), end: Math.max(anchor, clicked) };
  }
  return { start: clicked, end: clicked };
}

// ---------------------------------------------------------------------------
// Colouring
// ---------------------------------------------------------------------------

export type ColourMode =
  | 'plddt'
  | 'chain'
  | 'spectrum'
  | 'value'
  | 'category'
  | 'uniform'
  | 'secondary_structure'
  | 'residue_type'
  | 'hydrophobicity';

export type LegendSpec =
  | { kind: 'swatches'; title: string; items: { label: string; colour: string }[]; more?: number }
  | { kind: 'gradient'; title: string; min: string; max: string; stops: string[] }
  | null;

export interface Colouring {
  /** `ss` is the secondary structure 3Dmol assigned the residue (`h`, `s`,
   *  null for coil); only `secondary_structure` reads it. */
  colourOf(chain: string, position: number, bfactor: number | null, ss?: string | null): string;
  legend: LegendSpec;
  /** A 3Dmol built-in colour scheme that paints the model instead of
   *  `colourOf` (`residue_type`: the `amino` table). */
  scheme?: string;
}

/** 3Dmol's residue-type table, the RasMol `amino` colours. */
export const RESIDUE_TYPE_SCHEME = 'amino';

/** Kyte-Doolittle bounds: arginine -4.5, isoleucine 4.5. */
const KD_MIN = KYTE_DOOLITTLE.R;
const KD_MAX = KYTE_DOOLITTLE.I;

const MAX_LEGEND_ITEMS = 8;
/** Where a gradient legend samples its scale. */
const GRADIENT_STOPS = [0, 0.25, 0.5, 0.75, 1];
/** Continuous scale of `value` mode when the config names none. */
const DEFAULT_VALUE_SCALE = 'Viridis';

/** A swatch legend of a categorical colour map, capped at `MAX_LEGEND_ITEMS`. */
function swatchLegend(title: string, map: ReturnType<typeof stableColorMap>): LegendSpec {
  return {
    kind: 'swatches',
    title,
    items: map.universe.slice(0, MAX_LEGEND_ITEMS).map((v) => ({ label: v, colour: map.get(v) })),
    more: Math.max(0, map.universe.length - MAX_LEGEND_ITEMS) || undefined,
  };
}

/** N-to-C rainbow (blue to red), the conventional chain-tracing ramp. Hues are
 *  computed, not picked: a position along the chain maps to one hue. */
export function spectrumColour(t: number): string {
  // HSL (hue 240 to 0, s 0.75, l 0.5) written as hex: 3Dmol parses hex and
  // rgb() strings only.
  const h = (240 * (1 - Math.max(0, Math.min(1, t)))) / 360;
  const s = 0.75;
  const l = 0.5;
  const channel = (n: number) => {
    const k = (n + h * 12) % 12;
    const c = l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${channel(0)}${channel(8)}${channel(4)}`;
}

function formatValue(v: number): string {
  if (Number.isInteger(v)) return String(v);
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return v.toFixed(1);
  return String(Number(v.toPrecision(2)));
}

/** Per-residue lookup of a row field: by chain + position when the row names a
 *  chain, else by position alone. */
function perResidue<T>(
  rows: readonly ResidueRow[],
  pick: (r: ResidueRow) => T | null,
  merge: (prev: T, next: T) => T,
): (chain: string, position: number) => T | null {
  const byKey = new Map<string, T>();
  for (const r of rows) {
    if (r.position === null) continue;
    const v = pick(r);
    if (v === null) continue;
    const k = residueKey(r.chain, r.position);
    const prev = byKey.get(k);
    byKey.set(k, prev === undefined ? v : merge(prev, v));
  }
  return (chain, position) =>
    byKey.get(residueKey(chain, position)) ?? byKey.get(residueKey(null, position)) ?? null;
}

export function buildColouring(
  mode: ColourMode,
  args: {
    residues: readonly StructureResidue[];
    rows: readonly ResidueRow[];
    palette: readonly string[];
    /** Colour of a residue the mode has nothing to say about. */
    neutral: string;
    /** Colour of `uniform` mode. */
    uniform: string;
    valueLabel?: string | null;
    categoryLabel?: string | null;
    /** Continuous scale of `value` mode (a `COLOUR_SCALES` name); Viridis by default. */
    valueScale?: string | null;
  },
): Colouring {
  const { residues, rows, palette, neutral, uniform } = args;
  const valueScale = args.valueScale || DEFAULT_VALUE_SCALE;
  switch (mode) {
    case 'plddt': {
      // The pLDDT scale (0-100 or 0-1) is decided once per structure.
      const fractional = plddtIsFractional(residues.map((r) => r.bfactor));
      return {
        colourOf: (_c, _p, b) => (b === null ? neutral : plddtColour(b, fractional)),
        legend: {
          kind: 'swatches',
          title: 'pLDDT',
          items: PLDDT_BANDS.map((band) => ({ label: band.label, colour: rgbCss(band.rgb) })),
        },
      };
    }
    case 'chain': {
      const chains = Array.from(new Set(residues.map((r) => r.chain || '-')));
      const map = stableColorMap(chains, palette);
      return {
        colourOf: (c) => map.get(c || '-'),
        legend: chains.length > 1 ? swatchLegend('Chain', map) : null,
      };
    }
    case 'spectrum': {
      const order = new Map<string, number>();
      residues.forEach((r, i) => order.set(residueKey(r.chain, r.position), i));
      const span = Math.max(1, residues.length - 1);
      return {
        colourOf: (c, p) => {
          const i = order.get(residueKey(c, p));
          return i === undefined ? neutral : spectrumColour(i / span);
        },
        legend: {
          kind: 'gradient',
          title: 'Sequence',
          min: 'N',
          max: 'C',
          stops: GRADIENT_STOPS.map(spectrumColour),
        },
      };
    }
    case 'value': {
      const lookup = perResidue(rows, (r) => r.value, Math.max);
      const values = rows.map((r) => r.value).filter((v): v is number => v !== null);
      if (values.length === 0) {
        return { colourOf: () => neutral, legend: null };
      }
      let min = Infinity;
      let max = -Infinity;
      for (const v of values) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
      const span = max - min || 1;
      return {
        colourOf: (c, p) => {
          const v = lookup(c, p);
          return v === null ? neutral : rgbCss(sampleColorscale(valueScale, (v - min) / span));
        },
        legend: {
          kind: 'gradient',
          title: args.valueLabel || 'Value',
          min: formatValue(min),
          max: formatValue(max),
          stops: GRADIENT_STOPS.map((t) => rgbCss(sampleColorscale(valueScale, t))),
        },
      };
    }
    case 'category': {
      const lookup = perResidue(rows, (r) => r.category, (a) => a);
      const map = stableColorMap(
        rows.map((r) => r.category),
        palette,
      );
      return {
        colourOf: (c, p) => {
          const v = lookup(c, p);
          return v === null ? neutral : map.get(v);
        },
        legend: map.universe.length ? swatchLegend(args.categoryLabel || 'Category', map) : null,
      };
    }
    case 'secondary_structure': {
      // The RasMol structure colours the sequence track's glyphs use too.
      const helix = rgbCss(SECONDARY_STRUCTURE_COLOURS.helix);
      const strand = rgbCss(SECONDARY_STRUCTURE_COLOURS.strand);
      return {
        colourOf: (_c, _p, _b, ss) => (ss === 'h' ? helix : ss === 's' ? strand : neutral),
        legend: {
          kind: 'swatches',
          title: 'Secondary structure',
          items: [
            { label: 'Helix', colour: helix },
            { label: 'Strand', colour: strand },
            { label: 'Coil', colour: neutral },
          ],
        },
      };
    }
    case 'residue_type':
      // Twenty colours make no legend worth its room; the tooltip names the residue.
      return { colourOf: () => neutral, legend: null, scheme: RESIDUE_TYPE_SCHEME };
    case 'hydrophobicity': {
      // Kyte-Doolittle per residue on the ramp the alignment's hydrophobicity
      // scheme uses, so a residue has one colour in both tiles.
      const aaOf = new Map<string, string>();
      for (const r of residues) aaOf.set(residueKey(r.chain, r.position), r.aa);
      const colourOfAa = (aa: string | undefined) => {
        const rgb = aa ? hydrophobicityColour(aa) : null;
        return rgb ? rgbCss(rgb) : neutral;
      };
      return {
        colourOf: (c, p) => colourOfAa(aaOf.get(residueKey(c, p))),
        legend: {
          kind: 'gradient',
          title: 'Hydrophobicity (Kyte-Doolittle)',
          min: formatValue(KD_MIN),
          max: formatValue(KD_MAX),
          // The ramp is linear between its two ends, as a CSS gradient is.
          stops: [colourOfAa('R'), colourOfAa('I')],
        },
      };
    }
    case 'uniform':
    default:
      return { colourOf: () => uniform, legend: null };
  }
}
