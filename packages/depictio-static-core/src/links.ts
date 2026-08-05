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
  resolver?: 'direct' | 'sample_mapping' | 'pattern' | 'regex' | 'wildcard';
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
  /** 'MultiSelect', or {@link LINK_NO_MATCH} when the chain matched nothing. */
  interactive_component_type: string;
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
 * fallback (resolvers.py:114). Restricted to suffixes with an explicit prefix
 * letter (R/L/REP/TECH) so legit IDs ending in digits ('Sample_2024',
 * 'Patient_42') are never over-stripped onto the same base bucket.
 */
const SAMPLE_SUFFIX_RE = /_(?:R\d+|L\d+|REP\d+|TECH\d+)$/i;

/** Strip `_R1` / `_L001` / `_REP1` / `_TECH1` style suffixes (resolvers.py:120). */
function stripSampleSuffix(name: string): string {
  return name.replace(SAMPLE_SUFFIX_RE, '');
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
 * - sample_mapping (resolvers.py:88): exact key lookup first (a linear
 *   case-folded scan when `case_sensitive` is false), then the suffix-stripped
 *   base-bucket fallback aggregating variants from every key sharing the base;
 *   a value with no mapping is emitted AS-IS and recorded unmapped.
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
      const mappings = config?.mappings ?? {};
      const caseSensitive = config?.case_sensitive ?? true;

      // Pre-bucket mapping keys by their stripped base (resolvers.py:147).
      const baseToVariants = new Map<string, string[]>();
      for (const [key, variants] of Object.entries(mappings)) {
        const base = stripSampleSuffix(key);
        const bucketKey = caseSensitive ? base : base.toLowerCase();
        const bucket = baseToVariants.get(bucketKey);
        if (bucket) bucket.push(...variants);
        else baseToVariants.set(bucketKey, [...variants]);
      }

      const resolved: string[] = [];
      const unmapped: string[] = [];
      for (const val of values) {
        const strVal = toStr(val);
        const lookupVal = caseSensitive ? strVal : strVal.toLowerCase();

        // 1. exact key match (resolvers.py:157–164). Python's `if not
        //    found_mapping` treats an empty variant list like a miss.
        let found: string[] | null = null;
        if (caseSensitive) {
          found = mappings[strVal] ?? null;
        } else {
          for (const [key, variants] of Object.entries(mappings)) {
            if (key.toLowerCase() === lookupVal) {
              found = variants;
              break;
            }
          }
        }

        // 2. base-bucket fallback (resolvers.py:168–173), deduped with
        //    first-occurrence order (Python dict.fromkeys).
        if (!found || found.length === 0) {
          const fallback = baseToVariants.get(lookupVal);
          if (fallback && fallback.length > 0) {
            found = [...new Set(fallback)];
          }
        }

        if (found && found.length > 0) {
          resolved.push(...found);
        } else {
          // No mapping: pass the value through AND record it (resolvers.py:180).
          resolved.push(strVal);
          unmapped.push(strVal);
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
          'Valid types: direct, sample_mapping, pattern, regex, wildcard',
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
  filtersByDc: Record<string, { value?: unknown; metadata?: { column_name?: string } }[]>,
  projectLinks: DCLinkLike[],
  resolveHop: ResolveHop,
): Promise<SyntheticLinkFilter[]> {
  const linkFilters: SyntheticLinkFilter[] = [];

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
