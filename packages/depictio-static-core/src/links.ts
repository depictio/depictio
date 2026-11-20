/**
 * Browser-side port of cross-DC link resolution (filter propagation between
 * data collections).
 *
 * Sources of truth (the Python server is the authority; every rule here is a
 * line-for-line mirror):
 *
 *   - resolvers    — `depictio/api/v1/endpoints/links_endpoints/resolvers.py`
 *                    (DirectResolver :61, SampleMappingResolver :88,
 *                    PatternResolver :192, RegexResolver :232,
 *                    WildcardResolver :293)
 *   - graph walk   — `depictio/api/v1/filter_links.py`
 *                    (`_link_target_column` :57, `_link_paths` :81,
 *                    `_walk_link_path` :125, `extend_filters_via_links` :395)
 *   - trigger rule — `depictio/api/v1/endpoints/links_endpoints/routes.py:689`
 *                    (translate only when the filter column differs from the
 *                    link's join column)
 *   - link shapes  — `depictio/models/models/links.py` (LinkConfig / DCLink)
 *
 * What runs where: the pure resolver math and the graph traversal live here.
 * The one data-touching step — `_translate_filter_values` (routes.py:132),
 * `SELECT DISTINCT link_col WHERE filter_col IN (values)` on the source DC —
 * is injected by the runtime as a {@link ResolveHop} callback: tier A runs the
 * query against the bundled Parquet table then applies {@link applyResolver};
 * tier B looks the translation up in `manifest.links.tables` via
 * {@link translateViaTable}.
 */

import type { LinkTable } from './manifest';

/**
 * `filter_links.py` reads this from `predicates.py:31`. An empty resolved
 * list must survive as a filter meaning "no rows" — an empty MultiSelect value
 * is read downstream as "no filter" and renders every row — so it travels
 * under this sentinel component type instead.
 */
export const LINK_NO_MATCH = '__link_no_match__' as const;

/**
 * How many links a filter may travel before we stop looking
 * (filter_links.py:39). Three covers metadata -> samples -> features, the
 * deepest real topology shipped.
 */
export const MAX_LINK_HOPS = 3;

/** Mirror of `LinkConfig` (models/links.py:21). Defaults match the Pydantic model. */
export interface DCLinkConfig {
  /** Resolution strategy; the model defaults to 'direct'. */
  resolver?: 'direct' | 'sample_mapping' | 'pattern' | 'regex' | 'wildcard' | 'region';
  /** Role -> TARGET column, for the 'region' resolver ('chrom', 'pos'). */
  columns?: { chrom?: string | null; pos?: string | null } | null;
  /** Canonical ID -> variant list, for the sample_mapping resolver. */
  mappings?: Record<string, string[]> | null;
  /** '{sample}' template, for the pattern resolver. */
  pattern?: string | null;
  /** Column the resolved values name on the TARGET DC (cross-DC rename). */
  target_field?: string | null;
  /** Model default: true. */
  case_sensitive?: boolean;
}

/**
 * Shape of `manifest.links.configs` entries — Mongo-verbatim `DCLink` dicts
 * (models/links.py:79). Everything optional because the server code reads them
 * with `.get(...)`, never through the Pydantic model.
 */
export interface DCLinkLike {
  id?: unknown;
  source_dc_id?: string;
  target_dc_id?: string;
  source_column?: string;
  target_type?: string;
  link_config?: DCLinkConfig;
  enabled?: boolean;
}

/** One hop's resolution result — the subset of `LinkResolutionResponse` the walk reads. */
export interface ResolveOutcome {
  resolved_values: unknown[];
  /** Explicit target column, if the resolver ever returns one (top precedence). */
  target_column?: string | null;
}

/**
 * One hop's value translation + resolution, supplied by the runtime. Mirrors
 * `resolve_link_values` (filter_links.py:214) as seen by `_walk_link_path`:
 * return `null` for "no link usable on this hop" (the server's 404 — a real
 * answer, distinct from an empty match), and THROW on failure — a failed
 * resolution must never degrade into "no filter" (filter_links.py:42,
 * LinkResolutionError).
 *
 * Tier A implementations run `SELECT DISTINCT link_col WHERE filter_col IN
 * (values)` on the bundled source table when {@link needsTranslation} says so
 * (routes.py:689–707), then apply the pure {@link applyResolver}. Tier B
 * implementations look the translation up in `manifest.links.tables` via
 * {@link translateViaTable}.
 */
export type ResolveHop = (
  link: DCLinkLike,
  column: string,
  values: unknown[],
) => Promise<ResolveOutcome | null>;

/**
 * Synthetic filter emitted for a resolved link path. `metadata` mirrors
 * `extend_filters_via_links` (filter_links.py:482–497); the duplicated
 * top-level `column_name` / `interactive_component_type` mirror the flattened
 * shape the SPA endpoint hands back
 * (`dashboards_endpoints/routes.py:1449–1467`).
 */
export interface SyntheticLinkFilter {
  /** 'link_' + path link ids joined by '_' ('?' for a missing id) — keeps two routes to the same target from colliding. */
  index: string;
  value: unknown[];
  column_name: string;
  /** 'MultiSelect', or {@link LINK_NO_MATCH} when the chain matched nothing; a region link keeps its half's own type. */
  interactive_component_type: string;
  /** Set on region-link filters ({@link GENOME_SELECTION_SOURCE}). */
  source?: string;
  metadata: {
    dc_id: string;
    column_name: string;
    interactive_component_type: string;
  };
}

// ---------------------------------------------------------------------------
// resolvers (resolvers.py)
// ---------------------------------------------------------------------------

/**
 * Read-pair / lane / replicate / tech suffixes stripped for the base-bucket
 * fallback (services/multiqc/sample_matching.py `SAMPLE_SUFFIX_RE`). Restricted
 * to suffixes with an explicit prefix letter (R/L/REP/TECH) so legit IDs ending
 * in digits ('Sample_2024', 'Patient_42') are never over-stripped onto the same
 * base bucket.
 */
const SAMPLE_SUFFIX_RE = /_(?:R\d+|L\d+|REP\d+|TECH\d+)$/i;

/** Strip `_R1` / `_L001` / `_REP1` / `_TECH1` style suffixes (`strip_sample_suffix`). */
function stripSampleSuffix(name: string): string {
  return name.replace(SAMPLE_SUFFIX_RE, '');
}

/** Python `str(x).strip()`: whitespace trimmed on both ends. */
function strip(v: unknown): string {
  return String(v).trim();
}

/** Push each of `items` onto `into` unless already there (encounter order kept). */
function mergeUnique(into: string[], items: string[]): void {
  for (const it of items) if (!into.includes(it)) into.push(it);
}

/**
 * Port of `SampleLookup` (services/multiqc/sample_matching.py), the one
 * implementation the server's `SampleMappingResolver` and MultiQC patching
 * delegate to. Matching tries, first hit wins:
 *
 * 1. exact — the value is a mapping key; targets are the key itself plus its
 *    variants (a key with no variants resolves to itself and counts as mapped).
 * 2. variant — the value is one of the variant names; resolves to itself.
 * 3. base — the value equals a key once suffixes are stripped from the KEYS;
 *    targets are every such key plus their merged variants.
 * 4. source-suffix — the same stripping applied to the VALUE, then 1 and 3.
 * 5. passthrough — unmatched, the stripped value is returned and recorded.
 *
 * Whitespace is trimmed on both sides; case folding on both sides unless
 * `caseSensitive`. Indexes are built in key order, so the answer is
 * deterministic and matches the server's.
 */
class SampleLookup {
  private readonly exact = new Map<string, [string, string[]]>();
  private readonly variants = new Map<string, string>();
  private readonly base = new Map<string, [string[], string[]]>();

  constructor(
    mappings: Record<string, string[]>,
    private readonly caseSensitive: boolean,
  ) {
    for (const [rawKey, rawVariants] of Object.entries(mappings)) {
      const key = strip(rawKey);
      if (!key) continue;
      const variants = (rawVariants ?? []).map(strip).filter((v) => v.length > 0);

      const nk = this.norm(key);
      const known = this.exact.get(nk);
      if (known) mergeUnique(known[1], variants);
      else this.exact.set(nk, [key, [...variants]]);

      for (const v of variants) {
        const nv = this.norm(v);
        if (!this.variants.has(nv)) this.variants.set(nv, v);
      }

      const b = this.norm(stripSampleSuffix(key));
      let bucket = this.base.get(b);
      if (!bucket) {
        bucket = [[], []];
        this.base.set(b, bucket);
      }
      bucket[0].push(key);
      mergeUnique(bucket[1], variants);
    }
  }

  private norm(value: string): string {
    return this.caseSensitive ? value : value.toLowerCase();
  }

  private static forKey([key, variants]: [string, string[]]): string[] {
    return [...new Set([key, ...variants])];
  }

  private static forBase([keys, variants]: [string[], string[]]): string[] {
    return [...new Set([...keys, ...variants])];
  }

  match(value: unknown): { source: string; matched: boolean; targets: string[] } {
    const source = strip(value);
    const nv = this.norm(source);

    const exact = this.exact.get(nv);
    if (exact) return { source, matched: true, targets: SampleLookup.forKey(exact) };

    const variant = this.variants.get(nv);
    if (variant !== undefined) return { source, matched: true, targets: [variant] };

    const baseHit = this.base.get(nv);
    if (baseHit) return { source, matched: true, targets: SampleLookup.forBase(baseHit) };

    const stripped = this.norm(stripSampleSuffix(source));
    if (stripped !== nv) {
      const ex = this.exact.get(stripped);
      if (ex) return { source, matched: true, targets: SampleLookup.forKey(ex) };
      const bh = this.base.get(stripped);
      if (bh) return { source, matched: true, targets: SampleLookup.forBase(bh) };
    }
    return { source, matched: false, targets: [source] };
  }
}

/** `str(v)` for the resolvers: JS String() matches Python str() on the JSON scalars links carry. */
function toStr(v: unknown): string {
  return String(v);
}

/**
 * Apply a link's resolver to a batch of source values — the pure part of the
 * server's `/links/{project}/resolve` endpoint (routes.py:709–744 dispatching
 * into resolvers.py). Returns `(resolved, unmapped)` like every
 * `BaseLinkResolver.resolve`.
 *
 * - direct (resolvers.py:61): pass-through, stringified.
 * - sample_mapping (resolvers.py → services/multiqc/sample_matching.py):
 *   exact key, variant identity, suffix-stripped key base, suffix-stripped
 *   source value (see `SampleLookup`); a value with no mapping is emitted
 *   as-is and recorded unmapped.
 * - pattern (resolvers.py:192): substitute each value into the '{sample}'
 *   template; a missing pattern falls back to direct.
 * - regex / wildcard (resolvers.py:232/:293): the server always calls these
 *   with `target_known_values=None` (routes.py:743), which makes both a
 *   pass-through identical to direct. Ported as exactly that pass-through —
 *   per the RFC (docs/design/rfc-serverless-deployment.md §8): "Port
 *   `regex`/`wildcard` as the pass-through the server currently does; 'fixing'
 *   it client-side would make the bundle *diverge* from the server." The
 *   target-matching branches are deliberately NOT implemented.
 *
 * Throws on an unknown resolver name, mirroring `get_resolver`'s ValueError
 * (resolvers.py:357) which the server surfaces as a 400.
 */
export function applyResolver(
  config: DCLinkConfig | undefined,
  values: unknown[],
): { resolved: string[]; unmapped: string[] } {
  const resolver = config?.resolver ?? 'direct';
  switch (resolver) {
    case 'direct':
      return { resolved: values.map(toStr), unmapped: [] };

    case 'sample_mapping': {
      // `expand_samples` (sample_matching.py): order-preserving, deduplicated
      // across every source value; an unmatched value passes through AND is
      // recorded unmapped.
      const lookup = new SampleLookup(config?.mappings ?? {}, config?.case_sensitive ?? true);
      const resolved: string[] = [];
      const unmapped: string[] = [];
      const seen = new Set<string>();
      for (const val of values) {
        const m = lookup.match(val);
        if (!m.matched) unmapped.push(m.source);
        for (const t of m.targets) {
          if (!seen.has(t)) {
            seen.add(t);
            resolved.push(t);
          }
        }
      }
      return { resolved, unmapped };
    }

    case 'pattern': {
      const pattern = config?.pattern;
      if (!pattern) {
        // "No pattern configured, falling back to direct" (resolvers.py:215).
        return { resolved: values.map(toStr), unmapped: [] };
      }
      // Python `pattern.format(sample=str(val))` — replace every '{sample}'.
      return {
        resolved: values.map((v) => pattern.split('{sample}').join(toStr(v))),
        unmapped: [],
      };
    }

    case 'region':
      // Never reached through a walk (`linkPaths` skips region links, as
      // `_link_paths` does); a region renames columns, it maps no values.
      return { resolved: values.map(toStr), unmapped: [] };

    case 'regex':
    case 'wildcard':
      // `target_known_values` is always None server-side (routes.py:743), so
      // both resolvers take their "returning source as-is" early exit
      // (resolvers.py:256–258 / :316–318). See the RFC quote in the function
      // doc — this pass-through is the contract, not a shortcut.
      return { resolved: values.map(toStr), unmapped: [] };

    default:
      throw new Error(
        `Unknown resolver type: ${String(resolver)}. ` +
          'Valid types: direct, sample_mapping, pattern, regex, wildcard, region',
      );
  }
}

// ---------------------------------------------------------------------------
// per-hop helpers
// ---------------------------------------------------------------------------

/**
 * Whether a hop needs the SELECT-DISTINCT column translation before resolving
 * (routes.py:689–707): only when the user's filter column differs from the
 * link's join column.
 */
export function needsTranslation(filterColumn: string, link: DCLinkLike): boolean {
  return filterColumn !== link.source_column;
}

/**
 * The column a link's resolved values name on the TARGET DC — mirror of
 * `_link_target_column` (filter_links.py:57–78). Precedence (each falls
 * through on any falsy value, like the Python `or` chain):
 *
 *   1. `resolved.target_column` — explicit, if the resolver ever returns it.
 *   2. `link_config.target_field` — cross-DC rename (e.g. MultiQC
 *      sample_mapping). Often null for 'direct'.
 *   3. `link.source_column` — the join column; same name on both sides for a
 *      direct table->table link.
 *
 * NEVER the user's filter column: the target DC may not have it, and an
 * unknown column is dropped silently downstream — every row comes back and
 * the component looks like it never filtered.
 */
export function linkTargetColumn(
  link: DCLinkLike,
  resolved?: ResolveOutcome | null,
): string | null {
  const linkConfig = link.link_config ?? {};
  return resolved?.target_column || linkConfig.target_field || link.source_column || null;
}

/**
 * Tier-B hop translation: look each value up in a precomputed
 * `manifest.links.tables` entry. Concatenates `table.values[String(v)]` in
 * input order, deduped with first-occurrence order; a value absent from the
 * table contributes nothing (the precomputed table IS the full answer of the
 * server's SELECT DISTINCT — an absent key matched no row).
 */
export function translateViaTable(table: LinkTable, values: unknown[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const v of values) {
    for (const translated of table.values[String(v)] ?? []) {
      if (!seen.has(translated)) {
        seen.add(translated);
        out.push(translated);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// region links (filter_links.py `region_link_filters`)
// ---------------------------------------------------------------------------

/** The filter source a genome region travels under (`GENOME_SELECTION_SOURCE`). */
export const GENOME_SELECTION_SOURCE = 'genome_selection' as const;

/** The position half of a region pair carries its chromosome half's index plus this. */
const GENOME_POS_INDEX_SUFFIX = '::pos';

/** Which half of a region pair a filter is, by its component type (`_REGION_ROLE_BY_COMPONENT`). */
const REGION_ROLE_BY_COMPONENT: Record<string, 'chrom' | 'pos'> = {
  MultiSelect: 'chrom',
  Select: 'chrom',
  RangeSlider: 'pos',
  Slider: 'pos',
};

/** A source filter as the link walks read it: the viewer's `InteractiveFilter`, loosely. */
export interface LinkSourceFilter {
  index?: unknown;
  value?: unknown;
  source?: unknown;
  column_name?: string;
  interactive_component_type?: string;
  metadata?: { column_name?: string; interactive_component_type?: string; dc_id?: string };
}

/** True for a link that renames a genomic region rather than resolving values. */
export function isRegionLink(link: DCLinkLike): boolean {
  return link.link_config?.resolver === 'region';
}

/** Python's `value in (None, [], "", False)` for a region half. */
function isEmptyRegionValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    value === false ||
    value === 0 || // Python: 0 == False
    (Array.isArray(value) && value.length === 0)
  );
}

function componentOf(f: LinkSourceFilter): string {
  return String(f.metadata?.interactive_component_type || f.interactive_component_type || '');
}

/**
 * The (chromosome, position) filters of one region pair on one DC — mirror of
 * `_region_halves`. `sourceColumn` names the chromosome column the link
 * follows (empty: the first pair found wins); the position half is matched by
 * index (`<chrom index>::pos`), or is the only position filter there is.
 */
export function regionHalves(
  sourceFilters: LinkSourceFilter[],
  sourceColumn: string,
): [LinkSourceFilter | null, LinkSourceFilter | null] {
  let chromHalf: LinkSourceFilter | null = null;
  const positions = new Map<string, LinkSourceFilter>();
  for (const f of sourceFilters ?? []) {
    if (!f || typeof f !== 'object' || f.source !== GENOME_SELECTION_SOURCE) continue;
    if (isEmptyRegionValue(f.value)) continue;
    const role = REGION_ROLE_BY_COMPONENT[componentOf(f)];
    if (role === 'pos') {
      positions.set(String(f.index ?? ''), f);
    } else if (role === 'chrom' && chromHalf === null) {
      const column = String(f.metadata?.column_name || f.column_name || '');
      if (!sourceColumn || column === sourceColumn) chromHalf = f;
    }
  }
  if (chromHalf === null) return [null, null];
  let posHalf = positions.get(`${String(chromHalf.index ?? '')}${GENOME_POS_INDEX_SUFFIX}`) ?? null;
  if (posHalf === null && positions.size === 1) posHalf = [...positions.values()][0];
  return [chromHalf, posHalf];
}

/**
 * Rewrite genome-region filters onto a target DC's own coordinate columns —
 * mirror of `region_link_filters`. A region link resolves nothing and reads no
 * data: it names the target's chromosome and coordinate columns, and the brush's
 * two filters are re-emitted under those names. One hop only; the chromosome
 * half is required (a coordinate range on no contig would narrow every contig).
 */
export function regionLinkFilters(
  targetDcId: string,
  filtersByDc: Record<string, LinkSourceFilter[]>,
  projectLinks: DCLinkLike[],
): SyntheticLinkFilter[] {
  const out: SyntheticLinkFilter[] = [];
  for (const link of projectLinks) {
    const enabled = link.enabled === undefined ? true : Boolean(link.enabled);
    if (!enabled || !isRegionLink(link) || String(link.target_dc_id ?? '') !== targetDcId) continue;
    const originDc = String(link.source_dc_id ?? '');
    if (!originDc || originDc === targetDcId) continue;
    const columns = link.link_config?.columns ?? {};
    const chromCol = columns.chrom;
    const posCol = columns.pos;
    if (!chromCol || !posCol) continue;

    const [chromHalf, posHalf] = regionHalves(
      filtersByDc[originDc] ?? [],
      String(link.source_column ?? ''),
    );
    if (!chromHalf) continue;
    const linkId = link.id === undefined || link.id === null ? '?' : String(link.id);
    for (const [role, sourceFilter, targetColumn] of [
      ['chrom', chromHalf, chromCol],
      ['pos', posHalf, posCol],
    ] as const) {
      if (!sourceFilter) continue;
      const component = componentOf(sourceFilter);
      out.push({
        index: `region_link_${linkId}_${role}`,
        value: sourceFilter.value as unknown[],
        source: GENOME_SELECTION_SOURCE,
        column_name: targetColumn,
        interactive_component_type: component,
        metadata: {
          dc_id: targetDcId,
          column_name: targetColumn,
          interactive_component_type: component,
        },
      });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// graph traversal (filter_links.py)
// ---------------------------------------------------------------------------

/**
 * Every enabled link path from `originDc` to `targetDcId` — mirror of
 * `_link_paths` (filter_links.py:81–122).
 *
 * Breadth-first (FIFO) so the shortest path to a target is found first; the
 * depth guard runs BEFORE expanding a queue entry; a DC is never revisited
 * within a path (per-branch seen-set seeded with the origin), so declared
 * cycles terminate; `enabled: false` links are never traversed; same DC as
 * origin and target returns no paths (the filter already applies natively).
 */
export function linkPaths(
  projectLinks: DCLinkLike[],
  originDc: string,
  targetDcId: string,
  maxHops: number = MAX_LINK_HOPS,
): DCLinkLike[][] {
  if (originDc === targetDcId) return [];

  const bySource = new Map<string, DCLinkLike[]>();
  for (const link of projectLinks) {
    // Python `link.get("enabled", True)`: missing key means enabled; any
    // present falsy value disables.
    const enabled = link.enabled === undefined ? true : Boolean(link.enabled);
    if (!enabled) continue;
    // Region links are not value routes (`_link_paths`): walking one would
    // resolve a coordinate column that needs no translation.
    // `regionLinkFilters` handles them instead.
    if (isRegionLink(link)) continue;
    const source = String(link.source_dc_id ?? '');
    const bucket = bySource.get(source);
    if (bucket) bucket.push(link);
    else bySource.set(source, [link]);
  }

  const paths: DCLinkLike[][] = [];
  // (current DC, path taken, DCs already on that path). FIFO via head index.
  const queue: [string, DCLinkLike[], Set<string>][] = [
    [originDc, [], new Set([originDc])],
  ];
  let head = 0;
  while (head < queue.length) {
    const [dc, path, seen] = queue[head++];
    if (path.length >= maxHops) continue;
    for (const link of bySource.get(dc) ?? []) {
      const nxt = String(link.target_dc_id ?? '');
      if (!nxt || seen.has(nxt)) continue;
      if (nxt === targetDcId) {
        paths.push([...path, link]);
      } else {
        queue.push([nxt, [...path, link], new Set(seen).add(nxt)]);
      }
    }
  }
  return paths;
}

/**
 * Resolve a filter along a chain of links, hop by hop — mirror of
 * `_walk_link_path` (filter_links.py:125–190). Each hop translates the values
 * it receives into the next DC's join column; that output becomes the next
 * hop's input.
 *
 * Returns `[targetColumn, values]` with three outcomes, and keeping them
 * apart is the whole point:
 *
 *   - values                — the filter translated successfully.
 *   - `[finalColumn, []]`   — it translated to nothing: satisfiable on the
 *     source but matching no row here; reported on the FINAL path link's
 *     target column (not this hop's), and the caller must emit a
 *     {@link LINK_NO_MATCH} filter for it.
 *   - `[null, []]`          — the chain is unusable (no link on a hop, or no
 *     resolvable target column); the caller drops it rather than claiming a
 *     result.
 *
 * A failed resolution does not return at all — `resolveHop` throws (mirroring
 * LinkResolutionError) and the rejection propagates untouched, so a timeout
 * can never masquerade as "no filter".
 */
export async function walkLinkPath(
  path: DCLinkLike[],
  originColumn: string,
  originValues: unknown[],
  resolveHop: ResolveHop,
): Promise<[string | null, unknown[]]> {
  let column = originColumn;
  let values = originValues;
  for (const link of path) {
    const resolved = await resolveHop(link, column, values);
    const finalColumn = linkTargetColumn(path[path.length - 1]);
    if (resolved === null) {
      // No link declared for this hop (the server's 404). Nothing to translate.
      return [null, []];
    }
    if (!resolved.resolved_values || resolved.resolved_values.length === 0) {
      // Resolved, to nothing. Every later hop would also be empty, so stop
      // here and report the empty match on the FINAL target column.
      return [finalColumn, []];
    }
    values = resolved.resolved_values;
    column = linkTargetColumn(link, resolved) ?? '';
    if (!column) {
      // Could not resolve a target column mid-walk: unusable chain.
      return [null, []];
    }
  }
  return [column, values];
}

/**
 * Python `value not in [None, [], "", False]` (filter_links.py:446). List
 * membership uses `==`, so besides null/undefined, empty array, '' and false,
 * plain 0 is ALSO inactive (Python `0 == False` is true) — and the later
 * `if not filter_value` guard (filter_links.py:463) would skip it anyway.
 */
function isActiveFilterValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value) && value.length === 0) return false;
  if (value === '' || value === false || value === 0) return false;
  return true;
}

/**
 * Extend filters using DC links for cross-DC filtering — mirror of
 * `extend_filters_via_links` (filter_links.py:395–504). Walks the link GRAPH,
 * not just direct neighbours: a filter on A must still reach a component on C
 * when the project declares A -> B -> C.
 *
 * For every origin DC other than the target, every active source filter is
 * walked along every path to the target; each successful (path × filter) walk
 * emits one {@link SyntheticLinkFilter} — 'MultiSelect' when values resolved,
 * {@link LINK_NO_MATCH} with an empty value list when the chain matched
 * nothing. Unusable chains (no target column) emit nothing. A `resolveHop`
 * rejection propagates (LinkResolutionError semantics — never degrade a
 * failure into "no filter").
 */
export async function extendFiltersViaLinks(
  targetDcId: string,
  filtersByDc: Record<string, LinkSourceFilter[]>,
  projectLinks: DCLinkLike[],
  resolveHop: ResolveHop,
): Promise<SyntheticLinkFilter[]> {
  // Region links first, as the server does: they rename two columns and
  // resolve nothing.
  const linkFilters: SyntheticLinkFilter[] = regionLinkFilters(
    targetDcId,
    filtersByDc,
    projectLinks,
  );

  for (const [originDc, sourceFilters] of Object.entries(filtersByDc)) {
    if (originDc === targetDcId) continue; // same DC: applies natively

    const activeSourceFilters = sourceFilters.filter((f) => isActiveFilterValue(f.value));
    if (activeSourceFilters.length === 0) continue;

    const paths = linkPaths(projectLinks, originDc, targetDcId);
    if (paths.length === 0) continue;

    for (const path of paths) {
      for (const sourceFilter of activeSourceFilters) {
        const filterValue = sourceFilter.value ?? [];
        // Python `if not filter_value: continue` — redundant after the active
        // check except for the empty-array-shaped values it re-guards.
        if (!isActiveFilterValue(filterValue)) continue;
        const filterValues = Array.isArray(filterValue) ? filterValue : [filterValue];
        const originColumn = sourceFilter.metadata?.column_name ?? '';

        const [targetColumn, resolvedValues] = await walkLinkPath(
          path,
          originColumn,
          filterValues,
          resolveHop,
        );
        if (!targetColumn) continue; // unusable chain — claim nothing

        // One synthetic filter per (path, source filter). The path id keeps
        // two routes to the same target from colliding on index.
        const pathId = path
          .map((link) => (link.id === undefined || link.id === null ? '?' : String(link.id)))
          .join('_');
        const componentType = resolvedValues.length > 0 ? 'MultiSelect' : LINK_NO_MATCH;
        linkFilters.push({
          index: `link_${pathId}`,
          // Empty means "matched nothing", which must survive as a filter
          // (tagged LINK_NO_MATCH so it is not read as an unset filter).
          value: resolvedValues,
          column_name: targetColumn,
          interactive_component_type: componentType,
          metadata: {
            dc_id: targetDcId,
            column_name: targetColumn,
            interactive_component_type: componentType,
          },
        });
      }
    }
  }

  return linkFilters;
}
