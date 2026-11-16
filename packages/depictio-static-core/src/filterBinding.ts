/**
 * Viewer filter payloads → engine BoundFilters, the offline twin of the
 * server's `clean_filter_payload` + `process_metadata_and_filter` + `add_filter`
 * (depictio/api/v1/deltatables_utils.py).
 *
 * Pure: no bundle, no React. The static runtime wraps it (liveData.ts
 * `toBoundFilters`) with the bundle's filter_expr companion map. Every branch
 * is pinned against the server's own functions by the engine fixture
 * (scripts/generate_fixture.py → `binding` cases, test/engine/binding.test.ts).
 *
 *   clean_filter_payload — an entry without a column, or with value in
 *     (None, [], ""), is dropped whole (its filter_expr too). Type/column come
 *     from the top level first, then `metadata`.
 *   Select/MultiSelect/SegmentedControl — `in`; a `genome_selection` source
 *     widens the chromosome names to their chr/no-chr spellings
 *     (`chrom_name_variants`).
 *   TextInput — `text_filter_pattern`: trimmed, ≤ 512 chars, CASE-INSENSITIVE
 *     regex by default, `match_mode: contains` = literal text, `case_sensitive`
 *     opt-in; a pattern the regex engine rejects means "no filter". Non-string
 *     columns are matched on their text form (the server's cast to Utf8).
 *   Slider — `_slider_predicate`: `>=` unless `slider_mode` (gte/gt/lte/lt/eq/ne)
 *     says otherwise; a list value is no filter.
 *   RangeSlider — inclusive both ends. DateRangePicker/Timeline — the `__ts__`
 *     companion in epoch-µs, wall-clock.
 *   filter_expr — ANDed after the entry's own predicate, through the
 *     `__fe__<sha8>` boolean companion the producer evaluated with the
 *     server's `build_filter_expr` (RFC §5). A filter_expr with no companion
 *     (a `.over()` window, or a column this DC lacks) is skipped.
 */

import type { BoundFilter, SliderOp } from './engine/filters';

import { GENOME_SELECTION_SOURCE, LINK_NO_MATCH } from './links';
export const RESIDUE_SELECTION_SOURCE = 'residue_selection';

/** The loose shape of a viewer `InteractiveFilter` the binder reads. */
export interface FilterLike {
  index?: unknown;
  value?: unknown;
  column_name?: string | null;
  interactive_component_type?: string | null;
  filter_expr?: string | null;
  source?: string | null;
  slider_mode?: string | null;
  case_sensitive?: unknown;
  match_mode?: unknown;
  paired_with?: string | null;
  metadata?: {
    column_name?: string | null;
    interactive_component_type?: string | null;
    filter_expr?: string | null;
    source?: string | null;
    slider_mode?: string | null;
    case_sensitive?: unknown;
    match_mode?: unknown;
    paired_with?: string | null;
    dc_id?: string | null;
  } | null;
}

export interface BindOptions {
  /** filter_expr source text → its `__fe__<sha8>` companion column name. */
  filterExprCompanions?: ReadonlyMap<string, string>;
  /** Called for a component type add_filter has no branch for. */
  onUnsupported?: (type: string) => void;
}

const SLIDER_OPS: readonly SliderOp[] = ['gte', 'gt', 'lte', 'lt', 'eq', 'ne'];
const TEXT_MATCH_MODES = new Set(['regex', 'contains']);
export const MAX_TEXT_PATTERN_LENGTH = 512;

// Characters the Rust regex crate treats as syntax (`_REGEX_META`).
const REGEX_META = new Set('\\.+*?()|[]{}^$#&-~'.split(''));

/** `escape_regex`: escape every Rust-regex metacharacter. */
export function escapeRegex(text: string): string {
  let out = '';
  for (const ch of text) out += REGEX_META.has(ch) ? `\\${ch}` : ch;
  return out;
}

/** `normalize_text_filter_options`: defaults filled, junk replaced. */
export function normalizeTextFilterOptions(
  caseSensitive: unknown,
  matchMode: unknown,
): [boolean, 'regex' | 'contains'] {
  let mode = matchMode ? String(matchMode).toLowerCase() : 'regex';
  if (!TEXT_MATCH_MODES.has(mode)) mode = 'regex';
  return [Boolean(caseSensitive), mode as 'regex' | 'contains'];
}

/**
 * `text_filter_pattern` → the `contains` BoundFilter's fields, or null for "no
 * filter". The server's case-insensitive form is the `(?i)` prefix; JS spells
 * it as the `i` flag. A regex JS rejects is treated like one Rust rejects.
 */
export function textFilterPattern(
  value: unknown,
  caseSensitive: unknown,
  matchMode: unknown,
): { pattern: string; literal: boolean; flags: string } | null {
  if (value === null || value === undefined || typeof value === 'object') return null;
  const text = String(value).trim();
  if (!text || text.length > MAX_TEXT_PATTERN_LENGTH) return null;
  const [sensitive, mode] = normalizeTextFilterOptions(caseSensitive, matchMode);
  const literal = mode === 'contains';
  if (literal && sensitive) return { pattern: text, literal: true, flags: '' };
  const pattern = literal ? escapeRegex(text) : text;
  const flags = sensitive ? '' : 'i';
  try {
    new RegExp(pattern, flags);
  } catch {
    return null;
  }
  return { pattern, literal: false, flags };
}

/** `canonical_chrom`: no leading chr/Chr/CHR, `M` and `MT` are one. */
export function canonicalChrom(name: unknown): string {
  let s = String(name).trim();
  if (s.slice(0, 3).toLowerCase() === 'chr') s = s.slice(3);
  return s === 'M' || s === 'MT' ? 'MT' : s;
}

/** `chrom_name_variants`: the values plus their chr / no-chr spellings. */
export function chromNameVariants(values: unknown): string[] {
  const items = Array.isArray(values) ? values : [values];
  const out = new Set<string>();
  for (const v of items) {
    if (v === null || v === undefined) continue;
    out.add(String(v));
    const canon = canonicalChrom(v);
    const spellings = [canon, `chr${canon}`];
    if (canon === 'MT') spellings.push('M', 'chrM', 'MT', 'chrMT');
    for (const s of spellings) out.add(s);
  }
  return [...out];
}

/** Parse the ISO-ish strings the date pickers emit into epoch-microseconds,
 *  as WALL-CLOCK time — the server parses them into naive datetimes and the
 *  `__ts__` companions epoch wall-clock too. */
export function parseWallClockMicros(raw: unknown): bigint | undefined {
  if (typeof raw !== 'string') {
    if (raw instanceof Date) return BigInt(raw.getTime()) * 1000n;
    return undefined;
  }
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?/);
  if (!m) return undefined;
  const [, y, mo, d, h = '0', mi = '0', s = '0', frac = ''] = m;
  const ms = Date.UTC(+y, +mo - 1, +d, +h, +mi, +s);
  const fracUs = Math.round(Number(`0.${frac || '0'}`) * 1e6);
  return BigInt(ms) * 1000n + BigInt(fracUs);
}

function pick<K extends keyof NonNullable<FilterLike['metadata']>>(
  f: FilterLike,
  key: K,
): unknown {
  const top = (f as unknown as Record<string, unknown>)[key as string];
  if (top !== null && top !== undefined && top !== '') return top;
  return f.metadata?.[key];
}

/** Entries `clean_filter_payload` keeps: a column and a non-empty value. */
export function isActiveFilter(f: FilterLike): boolean {
  const column = f.column_name || f.metadata?.column_name;
  const v = f.value;
  if (!column) return false;
  return !(v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0));
}

/** The filter_expr a filter entry carries (top level, then metadata). */
export function filterExprOf(f: FilterLike): string | null {
  const expr = f.filter_expr || f.metadata?.filter_expr;
  return expr ? String(expr) : null;
}

/** Bind a viewer filter list the way `process_metadata_and_filter` does. */
export function bindFilters(filters: readonly FilterLike[], opts: BindOptions = {}): BoundFilter[] {
  const out: BoundFilter[] = [];
  for (const f of filters ?? []) {
    const type = (f.interactive_component_type || f.metadata?.interactive_component_type) ?? '';
    if (type === LINK_NO_MATCH) {
      out.push({ kind: 'link_no_match' });
      continue;
    }
    if (!isActiveFilter(f)) continue;
    const column = String(f.column_name || f.metadata?.column_name);
    let v = f.value;
    switch (type) {
      case 'Select':
      case 'MultiSelect':
      case 'SegmentedControl': {
        if ((f.source || f.metadata?.source) === GENOME_SELECTION_SOURCE && type !== 'SegmentedControl') {
          v = chromNameVariants(v);
        }
        out.push({ kind: 'in', column, values: Array.isArray(v) ? v : [v] });
        break;
      }
      case 'TextInput': {
        const compiled = textFilterPattern(v, pick(f, 'case_sensitive'), pick(f, 'match_mode'));
        if (compiled) out.push({ kind: 'contains', column, ...compiled });
        break;
      }
      case 'Slider': {
        if (Array.isArray(v)) break;
        const raw = pick(f, 'slider_mode');
        let op = (raw ? String(raw) : 'gte').toLowerCase() as SliderOp;
        if (!SLIDER_OPS.includes(op)) op = 'gte';
        out.push({ kind: 'cmp', column, op, value: v });
        break;
      }
      case 'RangeSlider':
        if (Array.isArray(v) && v.length === 2) {
          out.push({ kind: 'range', column, min: Number(v[0]), max: Number(v[1]) });
        }
        break;
      case 'DateRangePicker':
      case 'Timeline':
        if (Array.isArray(v) && v.length === 2) {
          const min = parseWallClockMicros(v[0]);
          const max = parseWallClockMicros(v[1]);
          if (min !== undefined && max !== undefined) out.push({ kind: 'ts_range', column, min, max });
        }
        break;
      default:
        // Switch / Checkbox: the server has no add_filter branch either.
        opts.onUnsupported?.(type);
    }
    const expr = filterExprOf(f);
    if (expr) {
      const companion = opts.filterExprCompanions?.get(expr);
      if (companion) out.push({ kind: 'flag', column: companion });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// region scoping (depictio/api/v1/region_scope.py)
// ---------------------------------------------------------------------------

/** Either half of a genome region pair or of a residue range pair. */
export function isLocusFilter(f: FilterLike): boolean {
  const src = f.source || f.metadata?.source;
  return src === GENOME_SELECTION_SOURCE || src === RESIDUE_SELECTION_SOURCE;
}

/** `follows_region`: the explicit opt-in, on the component or its config. */
export function followsRegion(component: Record<string, unknown> | null | undefined): boolean {
  if (!component) return false;
  if (component.follow_region_filter === true) return true;
  const config = component.config as Record<string, unknown> | undefined;
  return Boolean(config && typeof config === 'object' && config.follow_region_filter === true);
}

function* stringValues(value: unknown): Generator<string> {
  if (typeof value === 'string') yield value;
  else if (Array.isArray(value)) for (const v of value) yield* stringValues(v);
  else if (value && typeof value === 'object') {
    for (const v of Object.values(value as Record<string, unknown>)) yield* stringValues(v);
  }
}

/**
 * `scope_region_filters`: the filters without the locus pair when the
 * component should not follow it. Cards and interactive components never do
 * (unless they opt in); figures do only when their `dict_kwargs` name a region
 * column; every other type gets the list unchanged.
 */
export function scopeRegionFilters<T extends FilterLike>(
  filters: readonly T[],
  componentType: string,
  component?: Record<string, unknown> | null,
): T[] {
  if (componentType !== 'card' && componentType !== 'figure' && componentType !== 'interactive') {
    return [...filters];
  }
  const region = filters.filter(isLocusFilter);
  if (region.length === 0 || followsRegion(component)) return [...filters];
  if (componentType === 'figure' && component) {
    const columns = new Set(
      region.map((f) => f.column_name || f.metadata?.column_name).filter(Boolean) as string[],
    );
    for (const s of stringValues(component.dict_kwargs ?? {})) {
      if (columns.has(s)) return [...filters];
    }
  }
  return filters.filter((f) => !isLocusFilter(f));
}

const RESIDUE_BLIND_KINDS = new Set(['complex_heatmap', 'upset', 'upset_plot']);

/** `scope_residue_filters`: heatmap/UpSet ignore the whole residue gesture. */
export function scopeResidueFilters<T extends FilterLike>(
  filters: readonly T[],
  vizKind: string | null | undefined,
): T[] {
  if (!vizKind || !RESIDUE_BLIND_KINDS.has(vizKind)) return [...filters];
  return filters.filter((f) => {
    const src = f.source || f.metadata?.source;
    const paired = f.paired_with || f.metadata?.paired_with;
    return src !== RESIDUE_SELECTION_SOURCE && paired !== RESIDUE_SELECTION_SOURCE;
  });
}
