/**
 * Cross-DC link resolution unit tests — behavioral mirror of the Python
 * suites pinning the server implementation:
 *
 *   - depictio/tests/unit/test_link_graph_traversal.py       (graph + walk + emission)
 *   - depictio/tests/api/v1/endpoints/links_endpoints/test_sample_mapping_resolver.py
 *   - depictio/tests/api/v1/test_filter_links.py              (target-column precedence)
 *
 * plus the tier-B `translateViaTable` lookup and the routes.py:689 trigger
 * rule (`needsTranslation`). Where a test name matches a Python test, the
 * assertions match it too.
 */

import { describe, expect, it } from 'vitest';

import {
  applyResolver,
  extendFiltersViaLinks,
  LINK_NO_MATCH,
  linkPaths,
  linkTargetColumn,
  needsTranslation,
  translateViaTable,
  walkLinkPath,
  type DCLinkConfig,
  type DCLinkLike,
  type ResolveHop,
} from '../src/links';

function link(
  id: string,
  source: string,
  target: string,
  opts: { sourceColumn?: string; enabled?: boolean; config?: DCLinkConfig } = {},
): DCLinkLike {
  return {
    id,
    source_dc_id: source,
    target_dc_id: target,
    source_column: opts.sourceColumn ?? 'sample_id',
    enabled: opts.enabled ?? true,
    link_config: opts.config ?? { resolver: 'direct' },
  };
}

const ids = (paths: DCLinkLike[][]): string[][] => paths.map((p) => p.map((l) => String(l.id)));

// ---------------------------------------------------------------------------
// linkPaths (test_link_graph_traversal.py — path finding)
// ---------------------------------------------------------------------------

describe('linkPaths', () => {
  it('finds a direct path', () => {
    const links = [link('l1', 'A', 'B')];
    expect(ids(linkPaths(links, 'A', 'B'))).toEqual([['l1']]);
  });

  it('finds a two-hop chain', () => {
    const links = [link('l1', 'A', 'B'), link('l2', 'B', 'C')];
    expect(ids(linkPaths(links, 'A', 'C'))).toEqual([['l1', 'l2']]);
  });

  it('star topology keeps every source', () => {
    // Two sources pointing at one target: each origin contributes its own
    // single-link path, found separately per origin.
    const links = [link('l1', 'A', 'C'), link('l2', 'B', 'C')];
    expect(linkPaths(links, 'A', 'C')).toHaveLength(1);
    expect(linkPaths(links, 'B', 'C')).toHaveLength(1);
  });

  it('returns every route to the same target', () => {
    const links = [link('l1', 'A', 'B'), link('l2', 'B', 'D'), link('l3', 'A', 'D')];
    const paths = linkPaths(links, 'A', 'D');
    const routes = ids(paths)
      .map((p) => p.join(''))
      .sort();
    expect(routes).toEqual(['l1l2', 'l3']);
    // Breadth-first: the direct route is discovered before the two-hop one.
    expect(paths[0]).toHaveLength(1);
  });

  it('terminates on cycles', () => {
    const links = [link('l1', 'A', 'B'), link('l2', 'B', 'A'), link('l3', 'B', 'C')];
    expect(ids(linkPaths(links, 'A', 'C'))).toEqual([['l1', 'l3']]);
  });

  it('bounds depth at maxHops', () => {
    // A->B->C->D->E->F->G: 6 hops, unreachable at max 3; A->D (3 hops) is not.
    const links = Array.from({ length: 6 }, (_, i) =>
      link(`l${i}`, String.fromCharCode(65 + i), String.fromCharCode(66 + i)),
    );
    expect(linkPaths(links, 'A', 'G', 3)).toEqual([]);
    expect(linkPaths(links, 'A', 'D', 3)).toHaveLength(1);
    // A 4-link chain is unreachable at the DEFAULT max of 3.
    expect(linkPaths(links, 'A', 'E')).toEqual([]);
    expect(linkPaths(links, 'A', 'D')).toHaveLength(1);
  });

  it('does not traverse disabled links', () => {
    const links = [link('l1', 'A', 'B'), link('l2', 'B', 'C', { enabled: false })];
    expect(linkPaths(links, 'A', 'C')).toEqual([]);
  });

  it('has no path from a DC to itself', () => {
    expect(linkPaths([link('l1', 'A', 'B')], 'A', 'A')).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// walkLinkPath (test_link_graph_traversal.py — walking a path)
// ---------------------------------------------------------------------------

describe('walkLinkPath', () => {
  it('composes hops — each hop output is the next hop input', async () => {
    const seen: [string, string, unknown[], string][] = [];
    const resolveHop: ResolveHop = async (l, column, values) => {
      seen.push([String(l.source_dc_id), column, values, String(l.target_dc_id)]);
      return { resolved_values: values.map((v) => `${String(v)}@${String(l.target_dc_id)}`) };
    };

    const path = [link('l1', 'A', 'B'), link('l2', 'B', 'C')];
    const [column, values] = await walkLinkPath(path, 'habitat', ['Groundwater'], resolveHop);

    expect(seen).toEqual([
      ['A', 'habitat', ['Groundwater'], 'B'],
      // hop 2 filters on the link's join column, not the user's column
      ['B', 'sample_id', ['Groundwater@B'], 'C'],
    ]);
    expect(column).toBe('sample_id');
    expect(values).toEqual(['Groundwater@B@C']);
  });

  it('a chain that matches nothing reports the FINAL column', async () => {
    // A hop resolving to nothing is an answer: no rows, on the final link's
    // target column — distinguishable from an unusable chain, because the
    // caller has to emit a LINK_NO_MATCH filter for it.
    const resolveHop: ResolveHop = async (l) =>
      l.target_dc_id === 'B' ? { resolved_values: ['x'] } : { resolved_values: [] };

    const result = await walkLinkPath(
      [link('l1', 'A', 'B'), link('l2', 'B', 'C')],
      'habitat',
      ['Groundwater'],
      resolveHop,
    );
    expect(result).toEqual(['sample_id', []]);
  });

  it('a missing link is unusable, not an empty match', async () => {
    // The server's 404 (no such link) yields no result at all.
    const resolveHop: ResolveHop = async () => null;
    const result = await walkLinkPath([link('l1', 'A', 'B')], 'habitat', ['Groundwater'], resolveHop);
    expect(result).toEqual([null, []]);
  });

  it('propagates a resolution failure', async () => {
    // A timeout must reach the caller, never degrade into "no filter"
    // (LinkResolutionError semantics — filter_links.py:42).
    const resolveHop: ResolveHop = async () => {
      throw new Error('timed out');
    };
    await expect(
      walkLinkPath([link('l1', 'A', 'B')], 'habitat', ['Groundwater'], resolveHop),
    ).rejects.toThrow('timed out');
  });
});

// ---------------------------------------------------------------------------
// extendFiltersViaLinks (test_link_graph_traversal.py — end to end)
// ---------------------------------------------------------------------------

describe('extendFiltersViaLinks', () => {
  const habitatFilter = { value: ['Groundwater'], metadata: { column_name: 'habitat' } };

  it('a two-hop filter reaches the far DC, index joins the path link ids', async () => {
    const resolveHop: ResolveHop = async (l, _column, values) => ({
      resolved_values: values.map((v) => `${String(v)}->${String(l.target_dc_id)}`),
    });

    const out = await extendFiltersViaLinks(
      'C',
      { A: [habitatFilter] },
      [link('l1', 'A', 'B'), link('l2', 'B', 'C')],
      resolveHop,
    );

    expect(out).toHaveLength(1);
    expect(out[0].index).toBe('link_l1_l2');
    expect(out[0].metadata.dc_id).toBe('C');
    expect(out[0].metadata.column_name).toBe('sample_id');
    expect(out[0].value).toEqual(['Groundwater->B->C']);
  });

  it('single-hop behaviour', async () => {
    const resolveHop: ResolveHop = async () => ({ resolved_values: ['s1', 's2'] });
    const out = await extendFiltersViaLinks('B', { A: [habitatFilter] }, [link('l1', 'A', 'B')], resolveHop);
    expect(out).toHaveLength(1);
    expect(out[0].index).toBe('link_l1');
    expect(out[0].value).toEqual(['s1', 's2']);
    expect(out[0].metadata.column_name).toBe('sample_id');
  });

  it('three filtered sources all reach one target without index collisions', async () => {
    const resolveHop: ResolveHop = async (l) => ({
      resolved_values: [`from_${String(l.source_dc_id)}`],
    });
    const out = await extendFiltersViaLinks(
      'D',
      {
        A: [{ value: ['x'], metadata: { column_name: 'habitat' } }],
        B: [{ value: ['y'], metadata: { column_name: 'batch' } }],
        C: [{ value: ['z'], metadata: { column_name: 'site' } }],
      },
      [link('l1', 'A', 'D'), link('l2', 'B', 'D'), link('l3', 'C', 'D')],
      resolveHop,
    );
    expect(out.map((f) => f.value[0]).sort()).toEqual(['from_A', 'from_B', 'from_C']);
    expect(new Set(out.map((f) => f.index)).size).toBe(3);
  });

  it('filters on the component own DC are not re-resolved', async () => {
    const resolveHop: ResolveHop = async () => {
      throw new Error('resolved a filter that already applies natively');
    };
    const out = await extendFiltersViaLinks(
      'A',
      { A: [{ value: ['x'], metadata: { column_name: 'habitat' } }] },
      [link('l1', 'A', 'B')],
      resolveHop,
    );
    expect(out).toEqual([]);
  });

  it('inactive filter values are skipped', async () => {
    // Mirrors `value not in [None, [], "", False]` (filter_links.py:446).
    // NOTE: Python list membership uses ==, and `0 == False` is true, so a
    // plain 0 is ALSO inactive server-side (and the later `if not
    // filter_value` guard would drop it anyway) — ported faithfully.
    let calls = 0;
    const resolveHop: ResolveHop = async () => {
      calls++;
      return { resolved_values: ['s1'] };
    };
    const out = await extendFiltersViaLinks(
      'B',
      {
        A: [
          { value: null as unknown, metadata: { column_name: 'habitat' } },
          { value: [], metadata: { column_name: 'habitat' } },
          { value: '', metadata: { column_name: 'habitat' } },
          { value: false, metadata: { column_name: 'habitat' } },
          { value: 0, metadata: { column_name: 'habitat' } },
        ],
      },
      [link('l1', 'A', 'B')],
      resolveHop,
    );
    expect(out).toEqual([]);
    expect(calls).toBe(0);
  });

  it('a scalar value is wrapped into a single-element list', async () => {
    const seen: unknown[][] = [];
    const resolveHop: ResolveHop = async (_l, _c, values) => {
      seen.push(values);
      return { resolved_values: ['s1'] };
    };
    await extendFiltersViaLinks(
      'B',
      { A: [{ value: 'Groundwater', metadata: { column_name: 'habitat' } }] },
      [link('l1', 'A', 'B')],
      resolveHop,
    );
    expect(seen).toEqual([['Groundwater']]);
  });

  it('an empty resolution emits the LINK_NO_MATCH sentinel with value []', async () => {
    // Zero resolved values must survive as a filter meaning "no rows"; an
    // empty MultiSelect value would be read downstream as no filter at all.
    const resolveHop: ResolveHop = async () => ({ resolved_values: [] });
    const out = await extendFiltersViaLinks('B', { A: [habitatFilter] }, [link('l1', 'A', 'B')], resolveHop);
    expect(out).toHaveLength(1);
    expect(out[0].value).toEqual([]);
    expect(out[0].metadata.interactive_component_type).toBe(LINK_NO_MATCH);
    expect(LINK_NO_MATCH).toBe('__link_no_match__');
  });

  it('top-level column_name / interactive_component_type mirror metadata', async () => {
    // The flattened shape the SPA endpoint returns
    // (dashboards_endpoints/routes.py:1449–1467) duplicates both fields.
    const hits: ResolveHop = async () => ({ resolved_values: ['s1'] });
    const miss: ResolveHop = async () => ({ resolved_values: [] });
    for (const resolveHop of [hits, miss]) {
      const out = await extendFiltersViaLinks('B', { A: [habitatFilter] }, [link('l1', 'A', 'B')], resolveHop);
      expect(out[0].column_name).toBe(out[0].metadata.column_name);
      expect(out[0].interactive_component_type).toBe(out[0].metadata.interactive_component_type);
    }
  });

  it('a missing link id renders as "?" in the index', async () => {
    const anon = link('x', 'A', 'B');
    delete (anon as { id?: unknown }).id;
    const resolveHop: ResolveHop = async () => ({ resolved_values: ['s1'] });
    const out = await extendFiltersViaLinks('B', { A: [habitatFilter] }, [anon], resolveHop);
    expect(out[0].index).toBe('link_?');
  });
});

// ---------------------------------------------------------------------------
// linkTargetColumn precedence (test_filter_links.py)
// ---------------------------------------------------------------------------

describe('linkTargetColumn', () => {
  const directLink = (targetField: string | null): DCLinkLike =>
    link('l1', 'A', 'B', { config: { resolver: 'direct', target_field: targetField } });

  it('falls back to the join column, never the filter column', () => {
    expect(linkTargetColumn(directLink(null))).toBe('sample_id');
    expect(linkTargetColumn(directLink(null), { resolved_values: ['s1'] })).toBe('sample_id');
  });

  it('target_field overrides the join column', () => {
    expect(linkTargetColumn(directLink('sample_name'))).toBe('sample_name');
  });

  it('an explicit resolved target_column wins over everything', () => {
    expect(
      linkTargetColumn(directLink('sample_name'), {
        resolved_values: ['s1'],
        target_column: 'explicit_col',
      }),
    ).toBe('explicit_col');
  });

  it('returns null when nothing is resolvable', () => {
    const bare = directLink(null);
    bare.source_column = '';
    expect(linkTargetColumn(bare)).toBeNull();
  });

  it('link filter uses the join column, not the user filter column (regression)', async () => {
    // test_filter_links.py:59 — resolver returns values but no target_column
    // and target_field is null: the synthetic filter must name 'sample_id',
    // not 'habitat'.
    const resolveHop: ResolveHop = async () => ({
      resolved_values: ['SRR10070141', 'SRR10070133', 'SRR10070132'],
    });
    const out = await extendFiltersViaLinks(
      'T',
      { S: [{ value: ['Groundwater'], metadata: { column_name: 'habitat' } }] },
      [link('l1', 'S', 'T', { config: { resolver: 'direct', target_field: null } })],
      resolveHop,
    );
    expect(out).toHaveLength(1);
    expect(out[0].metadata.column_name).toBe('sample_id');
    expect(out[0].metadata.dc_id).toBe('T');
    expect(out[0].value).toEqual(['SRR10070141', 'SRR10070133', 'SRR10070132']);
  });

  it('the link is skipped when no join column is resolvable', async () => {
    // test_filter_links.py:128 — never emit a filter with a null column.
    const resolveHop: ResolveHop = async () => ({ resolved_values: ['s1'] });
    const crippled = link('l1', 'S', 'T', { config: { resolver: 'direct', target_field: null } });
    crippled.source_column = '';
    const out = await extendFiltersViaLinks(
      'T',
      { S: [{ value: ['Groundwater'], metadata: { column_name: 'habitat' } }] },
      [crippled],
      resolveHop,
    );
    expect(out).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// applyResolver — sample_mapping (test_sample_mapping_resolver.py, 12 cases)
// ---------------------------------------------------------------------------

describe('applyResolver / sample_mapping', () => {
  // Mirror of the Python suite's `_config` helper: case-insensitive default.
  const config = (mappings: Record<string, string[]>, caseSensitive = false): DCLinkConfig => ({
    resolver: 'sample_mapping',
    mappings,
    case_sensitive: caseSensitive,
  });

  it('exact key match takes precedence', () => {
    const mappings = {
      HG001_R1: ['HG001_R1', 'HG001_R1 - adapter'],
      HG001_R2: ['HG001_R2'],
    };
    const { resolved, unmapped } = applyResolver(config(mappings), ['HG001_R1']);
    expect(resolved).toEqual(['HG001_R1', 'HG001_R1 - adapter']);
    expect(unmapped).toEqual([]);
  });

  it('base name falls back to the suffix bucket', () => {
    // 'HG001' -> union of every key whose stripped base is HG001.
    const mappings = {
      HG001_R1: ['HG001_R1', 'HG001_R1 - adapter'],
      HG001_R2: ['HG001_R2', 'HG001_R2 - adapter'],
      DONOR_A_R1: ['DONOR_A_R1'],
    };
    const { resolved, unmapped } = applyResolver(config(mappings), ['HG001']);
    expect(new Set(resolved)).toEqual(
      new Set(['HG001_R1', 'HG001_R1 - adapter', 'HG001_R2', 'HG001_R2 - adapter']),
    );
    expect(unmapped).toEqual([]);
  });

  it('a truly missing canonical passes through and is recorded unmapped', () => {
    const { resolved, unmapped } = applyResolver(config({ HG001_R1: ['HG001_R1'] }), ['XXXXX']);
    expect(resolved).toEqual(['XXXXX']);
    expect(unmapped).toEqual(['XXXXX']);
  });

  it('dedupes when multiple keys share a variant', () => {
    const mappings = {
      HG001_R1: ['HG001_R1', 'shared_variant'],
      HG001_R2: ['HG001_R2', 'shared_variant'],
    };
    const { resolved } = applyResolver(config(mappings), ['HG001']);
    expect(resolved.filter((v) => v === 'shared_variant')).toHaveLength(1);
  });

  it('strips the lane suffix (_L001)', () => {
    const mappings = { Sample_L001: ['Sample_L001'], Sample_L002: ['Sample_L002'] };
    const { resolved } = applyResolver(config(mappings), ['Sample']);
    expect(new Set(resolved)).toEqual(new Set(['Sample_L001', 'Sample_L002']));
  });

  it('strips replicate and tech suffixes', () => {
    const mappings = {
      Sample_REP1: ['Sample_REP1'],
      Sample_REP2: ['Sample_REP2'],
      Other_TECH1: ['Other_TECH1'],
    };
    const { resolved } = applyResolver(config(mappings), ['Sample']);
    expect(new Set(resolved)).toEqual(new Set(['Sample_REP1', 'Sample_REP2']));
  });

  it('does not over-strip a year suffix (Sample_2024)', () => {
    const mappings = { Sample_2024: ['Sample_2024'], Sample_2025: ['Sample_2025'] };
    const { resolved, unmapped } = applyResolver(config(mappings), ['Sample']);
    expect(resolved).toEqual(['Sample']);
    expect(unmapped).toEqual(['Sample']);
  });

  it('does not over-strip a patient id (Patient_42)', () => {
    const mappings = { Patient_42: ['Patient_42', 'Patient_42 - adapter'] };
    const { resolved, unmapped } = applyResolver(config(mappings), ['Patient']);
    expect(resolved).toEqual(['Patient']);
    expect(unmapped).toEqual(['Patient']);
  });

  it('matches case-insensitively when case_sensitive is false', () => {
    const { resolved } = applyResolver(config({ HG001_R1: ['HG001_R1'] }, false), ['hg001']);
    expect(resolved).toEqual(['HG001_R1']);
  });

  it('matches strictly when case_sensitive is true', () => {
    const { resolved, unmapped } = applyResolver(config({ HG001_R1: ['HG001_R1'] }, true), ['hg001']);
    expect(resolved).toEqual(['hg001']);
    expect(unmapped).toEqual(['hg001']);
  });

  it('returns source unchanged on empty mappings', () => {
    const { resolved, unmapped } = applyResolver(config({}), ['HG001', 'DONOR_A']);
    expect(resolved).toEqual(['HG001', 'DONOR_A']);
    expect(unmapped).toEqual(['HG001', 'DONOR_A']);
  });

  it('handles mixed exact, fallback and missing in one call', () => {
    const mappings = {
      HG001_R1: ['HG001_R1', 'HG001_R1 - adapter'],
      HG001_R2: ['HG001_R2'],
      DONOR_A_R1: ['DONOR_A_R1'],
    };
    const { resolved, unmapped } = applyResolver(config(mappings), ['HG001_R1', 'DONOR_A', 'MISSING']);
    expect(resolved).toContain('HG001_R1');
    expect(resolved).toContain('HG001_R1 - adapter');
    expect(resolved).toContain('DONOR_A_R1');
    expect(resolved).toContain('MISSING');
    expect(unmapped).toEqual(['MISSING']);
  });
});

// ---------------------------------------------------------------------------
// applyResolver — direct / pattern / regex / wildcard
// ---------------------------------------------------------------------------

describe('applyResolver / other resolvers', () => {
  it('direct stringifies and passes through', () => {
    expect(applyResolver({ resolver: 'direct' }, ['S1', 2, true])).toEqual({
      resolved: ['S1', '2', 'true'],
      unmapped: [],
    });
    // An absent config behaves as the model default (resolver='direct').
    expect(applyResolver(undefined, ['S1'])).toEqual({ resolved: ['S1'], unmapped: [] });
  });

  it('pattern substitutes every {sample} placeholder', () => {
    expect(applyResolver({ resolver: 'pattern', pattern: '{sample}.bam' }, ['S1', 'S2'])).toEqual({
      resolved: ['S1.bam', 'S2.bam'],
      unmapped: [],
    });
    expect(applyResolver({ resolver: 'pattern', pattern: '{sample}/{sample}.vcf' }, ['S1'])).toEqual({
      resolved: ['S1/S1.vcf'],
      unmapped: [],
    });
  });

  it('pattern without a template behaves as direct', () => {
    expect(applyResolver({ resolver: 'pattern' }, ['S1', 7])).toEqual({
      resolved: ['S1', '7'],
      unmapped: [],
    });
  });

  it('regex and wildcard are pass-throughs (server calls them with target_known_values=None)', () => {
    // Per the RFC (§8): "Port regex/wildcard as the pass-through the server
    // currently does" — the target-matching branches never run server-side.
    for (const resolver of ['regex', 'wildcard'] as const) {
      expect(applyResolver({ resolver }, ['S1', 3])).toEqual({
        resolved: ['S1', '3'],
        unmapped: [],
      });
    }
  });

  it('throws on an unknown resolver, like get_resolver', () => {
    expect(() =>
      applyResolver({ resolver: 'bogus' as unknown as 'direct' }, ['S1']),
    ).toThrow(/Unknown resolver type/);
  });
});

// ---------------------------------------------------------------------------
// needsTranslation (routes.py:689–707 trigger rule)
// ---------------------------------------------------------------------------

describe('needsTranslation', () => {
  it('is true only when the filter column differs from the join column', () => {
    const l = link('l1', 'A', 'B', { sourceColumn: 'sample_id' });
    expect(needsTranslation('habitat', l)).toBe(true);
    expect(needsTranslation('sample_id', l)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// translateViaTable (tier-B lookup)
// ---------------------------------------------------------------------------

describe('translateViaTable', () => {
  it('concatenates per-value translations in order', () => {
    const table = { values: { Groundwater: ['S1', 'S2'], Riverwater: ['S3'] } };
    expect(translateViaTable(table, ['Groundwater', 'Riverwater'])).toEqual(['S1', 'S2', 'S3']);
  });

  it('a value absent from the table contributes nothing', () => {
    const table = { values: { Groundwater: ['S1'] } };
    expect(translateViaTable(table, ['Seawater', 'Groundwater'])).toEqual(['S1']);
    expect(translateViaTable(table, ['Seawater'])).toEqual([]);
  });

  it('dedupes preserving first-occurrence order and stringifies keys', () => {
    const table = { values: { A: ['S2', 'S1'], B: ['S1', 'S3'], '7': ['S9'] } };
    expect(translateViaTable(table, ['A', 'B', 7])).toEqual(['S2', 'S1', 'S3', 'S9']);
  });
});
