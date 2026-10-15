import { describe, expect, it } from 'vitest';

import {
  architectureRows,
  architectureString,
  buildProteins,
  capProteins,
  domainAt,
  domainTooltip,
  filterHits,
  formatEvalue,
  FULL_MATCH,
  groupArchitectures,
  groupKey,
  hasSources,
  hmmCoverage,
  isPartial,
  LENGTH_LABEL_GAP_PX,
  LENGTH_LABEL_PAD_PX,
  lengthGutter,
  lengthLabel,
  normaliseCoverage,
  normaliseResidueWidth,
  packLanes,
  parseDomainHits,
  partialEdges,
  proteinLengths,
  proteinRows,
  labelColumnPx,
  pxPerResidue,
  representative,
  residueAt,
  residueX,
  RESIDUE_WIDTH_MAX_PX,
  rowAt,
  rowHeight,
  rowOffsets,
  rowWindow,
  sortProteins,
  trackBox,
  trackLayout,
  UNLABELLED,
  valueCounts,
  visibleResidues,
  type DomainColumns,
  type DomainHit,
  type ProteinArch,
} from './architecture';

const COLS: DomainColumns = {
  entity: 'entity',
  start: 'start',
  end: 'end',
  label: 'label',
  proteinLength: 'protein_length',
  hmmFrom: 'hmm_from',
  hmmTo: 'hmm_to',
  hmmLength: 'hmm_length',
  hmmCoverage: 'hmm_coverage',
  evalue: 'i_evalue',
  source: 'source',
  description: 'description',
  accession: 'accession',
  score: 'dom_score',
};

/** A hit with every optional field empty, overridden by `over`. */
function hit(
  over: Partial<DomainHit> & { entity?: string; start?: number; end?: number },
): DomainHit {
  return {
    row: 0,
    entity: 'P1',
    start: 1,
    end: 10,
    label: 'PF00001',
    source: null,
    accession: null,
    description: null,
    evalue: null,
    score: null,
    hmmFrom: null,
    hmmTo: null,
    hmmLength: null,
    coverage: null,
    proteinLength: null,
    ...over,
  };
}

/** A protein from hits, lengths read off the same hits. */
function proteinsOf(hits: DomainHit[]): ProteinArch[] {
  return buildProteins(hits, proteinLengths(hits));
}

describe('parseDomainHits', () => {
  it('reads a hmmsearch domain table by the configured names', () => {
    const frame = {
      entity: ['P1', 'P1', 'P2'],
      start: [10, 80, 5],
      end: [60, 40, 50],
      label: ['PF00001', null, 'PF00003'],
      accession: ['PF00001.2', 'PF00002.9', null],
      protein_length: [200, 200, null],
      hmm_from: [1, 3, null],
      hmm_to: [50, 40, null],
      hmm_length: [50, 60, null],
      hmm_coverage: [1, 0.63, 74],
      i_evalue: [1e-20, 0.5, null],
      source: ['Pfam', 'Pfam', 'SMART'],
      dom_score: [55.2, 3.1, null],
    };
    const { hits, skipped } = parseDomainHits(frame, COLS);
    expect(skipped).toBe(0);
    expect(hits).toHaveLength(3);
    expect(hits[0]).toMatchObject({
      entity: 'P1',
      start: 10,
      end: 60,
      label: 'PF00001',
      hmmFrom: 1,
    });
    // A reversed span is put back in order; no label falls back to the accession.
    expect(hits[1]).toMatchObject({ start: 40, end: 80, label: 'PF00002.9', coverage: 0.63 });
    // A coverage above 1 reads as a percentage.
    expect(hits[2].coverage).toBeCloseTo(0.74);
    expect(hits[2].proteinLength).toBeNull();
    expect(hits[0].score).toBe(55.2);
  });

  it('skips rows without an entity or a span, and reads a plain table', () => {
    const frame = {
      entity: ['P1', null, 'P2', 'P3'],
      start: [1, 2, null, 4],
      end: [5, 6, 7, 9],
      label: ['A', 'B', 'C', null],
    };
    const { hits, skipped } = parseDomainHits(frame, {
      entity: 'entity',
      start: 'start',
      end: 'end',
      label: 'label',
    });
    expect(skipped).toBe(2);
    expect(hits.map((h) => h.entity)).toEqual(['P1', 'P3']);
    expect(hits[1].label).toBe(UNLABELLED);
    expect(hits[0].hmmFrom).toBeNull();
  });

  it('counts every row as skipped when a span column is missing', () => {
    expect(parseDomainHits({ entity: ['P1'], label: ['A'] }, COLS)).toEqual({
      hits: [],
      skipped: 1,
    });
    expect(parseDomainHits(null, COLS)).toEqual({ hits: [], skipped: 0 });
  });

  it('normalises coverage', () => {
    expect(normaliseCoverage(0.5)).toBe(0.5);
    expect(normaliseCoverage(50)).toBe(0.5);
    expect(normaliseCoverage(-1)).toBeNull();
    expect(normaliseCoverage(500)).toBeNull();
    expect(normaliseCoverage('')).toBeNull();
  });
});

describe('partialEdges', () => {
  it('cuts the left edge when the match starts after the first HMM state', () => {
    expect(partialEdges(hit({ hmmFrom: 5, hmmTo: 100, hmmLength: 100 }))).toEqual({
      left: true,
      right: false,
      unknown: false,
    });
  });

  it('cuts the right edge when the match ends before the last state', () => {
    expect(partialEdges(hit({ hmmFrom: 1, hmmTo: 80, hmmLength: 100 }))).toEqual({
      left: false,
      right: true,
      unknown: false,
    });
    expect(partialEdges(hit({ hmmFrom: 2, hmmTo: 99, hmmLength: 100 }))).toEqual({
      left: true,
      right: true,
      unknown: false,
    });
  });

  it('keeps a full match whole, whatever its coverage column says', () => {
    const full = hit({ hmmFrom: 1, hmmTo: 100, hmmLength: 100, coverage: 0.2 });
    expect(partialEdges(full)).toEqual(FULL_MATCH);
    expect(isPartial(partialEdges(full))).toBe(false);
  });

  it('falls back to coverage when the HMM states are absent: side unknown', () => {
    expect(partialEdges(hit({ coverage: 0.5 }), 0.9)).toEqual({
      left: false,
      right: false,
      unknown: true,
    });
    expect(partialEdges(hit({ coverage: 0.95 }), 0.9)).toEqual(FULL_MATCH);
    // The threshold is the config's `partial_coverage`.
    expect(partialEdges(hit({ coverage: 0.5 }), 0.4)).toEqual(FULL_MATCH);
    expect(partialEdges(hit({}))).toEqual(FULL_MATCH);
  });

  it('falls back to coverage when the states cannot decide the right end', () => {
    // hmm_from = 1 and no HMM length: the right end is unknown.
    expect(partialEdges(hit({ hmmFrom: 1, hmmTo: 40, coverage: 0.4 }))).toEqual({
      left: false,
      right: false,
      unknown: true,
    });
    // A known left cut wins over the coverage fallback.
    expect(partialEdges(hit({ hmmFrom: 7, hmmTo: 40, coverage: 0.4 }))).toEqual({
      left: true,
      right: false,
      unknown: false,
    });
  });

  it('derives the coverage from the states when there is no coverage column', () => {
    expect(hmmCoverage(hit({ hmmFrom: 11, hmmTo: 60, hmmLength: 100 }))).toBeCloseTo(0.5);
    expect(hmmCoverage(hit({ coverage: 0.3, hmmFrom: 1, hmmTo: 100, hmmLength: 100 }))).toBe(0.3);
    expect(hmmCoverage(hit({ hmmFrom: 1, hmmTo: 10 }))).toBeNull();
  });
});

describe('packLanes', () => {
  it('keeps disjoint domains in one lane', () => {
    expect(
      packLanes([
        { start: 1, end: 10 },
        { start: 11, end: 20 },
        { start: 30, end: 40 },
      ]),
    ).toEqual({
      lanes: [0, 0, 0],
      count: 1,
    });
  });

  it('moves overlapping domains to sub-lanes, inclusive ends overlapping', () => {
    expect(
      packLanes([
        { start: 1, end: 50 },
        { start: 10, end: 20 },
        { start: 20, end: 30 },
        { start: 51, end: 60 },
      ]),
    ).toEqual({ lanes: [0, 1, 2, 0], count: 3 });
    // A lane freed earlier is reused.
    expect(
      packLanes([
        { start: 1, end: 50 },
        { start: 10, end: 20 },
        { start: 25, end: 30 },
      ]),
    ).toEqual({ lanes: [0, 1, 1], count: 2 });
  });

  it('has one lane for a bare backbone', () => {
    expect(packLanes([])).toEqual({ lanes: [], count: 1 });
  });

  it('packs a protein built from overlapping hits', () => {
    const [p] = proteinsOf([
      hit({ start: 100, end: 150, label: 'B' }),
      hit({ start: 1, end: 120, label: 'A', source: 'Pfam' }),
      hit({ start: 5, end: 110, label: 'A2', source: 'SMART' }),
    ]);
    expect(p.domains.map((d) => d.label)).toEqual(['A', 'A2', 'B']);
    expect(p.lanes).toEqual([0, 1, 2]);
    expect(p.laneCount).toBe(3);
  });
});

describe('proteins and lengths', () => {
  it('uses the stated length, else the last domain end, never shorter than a domain', () => {
    const lengths = proteinLengths([
      hit({ entity: 'P1', end: 80, proteinLength: 300 }),
      hit({ entity: 'P2', end: 90 }),
      hit({ entity: 'P2', end: 140 }),
      hit({ entity: 'P3', end: 400, proteinLength: 350 }),
    ]);
    expect(lengths.get('P1')).toEqual({ length: 300, known: true });
    expect(lengths.get('P2')).toEqual({ length: 140, known: false });
    expect(lengths.get('P3')).toEqual({ length: 400, known: true });
  });

  it('keeps the unfiltered length after a filter drops the last domain', () => {
    const all = [
      hit({ entity: 'P1', start: 1, end: 20, evalue: 1e-10 }),
      hit({ entity: 'P1', start: 200, end: 260, evalue: 1 }),
    ];
    const [p] = buildProteins(filterHits(all, { evalueThreshold: 1e-3 }), proteinLengths(all));
    expect(p.length).toBe(260);
    expect(p.domains).toHaveLength(1);
  });
});

describe('architecture strings', () => {
  it('orders labels by start, keeping repeats', () => {
    expect(
      architectureString([
        hit({ start: 200, end: 260, label: 'PF00002' }),
        hit({ start: 1, end: 50, label: 'PF00001' }),
        hit({ start: 100, end: 150, label: 'PF00001' }),
      ]),
    ).toBe('PF00001~PF00001~PF00002');
    expect(architectureString([])).toBe('');
  });

  it('sorts proteins by architecture then entity, naturally', () => {
    const sorted = sortProteins(
      proteinsOf([
        hit({ entity: 'P10', label: 'B' }),
        hit({ entity: 'P2', label: 'B' }),
        hit({ entity: 'P3', label: 'A' }),
        hit({ entity: 'P1', label: 'B' }),
      ]),
    );
    expect(sorted.map((p) => `${p.architecture}:${p.entity}`)).toEqual([
      'A:P3',
      'B:P1',
      'B:P2',
      'B:P10',
    ]);
  });
});

describe('groupArchitectures', () => {
  // Three proteins with A~B, two with C, two with A (a tie with C), one with D.
  const proteins = sortProteins(
    proteinsOf([
      hit({ entity: 'x1', start: 1, end: 10, label: 'A', proteinLength: 100 }),
      hit({ entity: 'x1', start: 20, end: 30, label: 'B' }),
      hit({ entity: 'x2', start: 1, end: 10, label: 'A', proteinLength: 300 }),
      hit({ entity: 'x2', start: 20, end: 30, label: 'B' }),
      hit({ entity: 'x3', start: 1, end: 10, label: 'A', proteinLength: 200 }),
      hit({ entity: 'x3', start: 20, end: 30, label: 'B' }),
      hit({ entity: 'c1', label: 'C' }),
      hit({ entity: 'c2', label: 'C' }),
      hit({ entity: 'a1', label: 'A' }),
      hit({ entity: 'a2', label: 'A' }),
      hit({ entity: 'd1', label: 'D' }),
    ]),
  );

  it('counts proteins per architecture, ties broken by the architecture string', () => {
    const g = groupArchitectures(proteins, 10);
    expect(g.groups.map((x) => [x.architecture, x.members.length])).toEqual([
      ['A~B', 3],
      ['A', 2],
      ['C', 2],
      ['D', 1],
    ]);
    expect(g.architectures).toBe(4);
    expect(g.proteins).toBe(8);
    expect(g.others).toEqual({ architectures: 0, proteins: 0 });
  });

  it('summarises the architectures past the cap', () => {
    const g = groupArchitectures(proteins, 2);
    expect(g.groups.map((x) => x.architecture)).toEqual(['A~B', 'A']);
    expect(g.others).toEqual({ architectures: 2, proteins: 3 });
  });

  it('draws each group with its median-length member', () => {
    const g = groupArchitectures(proteins, 1);
    expect(g.groups[0].representative.entity).toBe('x3');
    expect(g.groups[0].members.map((m) => m.entity)).toEqual(['x1', 'x2', 'x3']);
  });

  it('takes the lower median of an even group, ties by entity', () => {
    const ps = proteinsOf([
      hit({ entity: 'b', proteinLength: 100 }),
      hit({ entity: 'a', proteinLength: 100 }),
      hit({ entity: 'c', proteinLength: 300 }),
      hit({ entity: 'd', proteinLength: 400 }),
    ]);
    expect(representative(ps)?.entity).toBe('b');
    expect(representative([])).toBeNull();
  });

  it('lists the rows of the architectures view', () => {
    const g = groupArchitectures(proteins, 2);
    const closed = architectureRows(g, new Set());
    expect(closed.map((r) => r.kind)).toEqual(['group', 'group', 'note']);
    expect(closed[2]).toMatchObject({ kind: 'note', text: '2 other architectures (3 proteins)' });
    const open = architectureRows(g, new Set([groupKey('A~B')]), 2);
    expect(open.map((r) => r.key)).toEqual([
      'arch:A~B',
      'arch:A~B|x1',
      'arch:A~B|x2',
      'arch:A~B|more',
      'arch:A',
      'others',
    ]);
    expect(open[1]).toMatchObject({ kind: 'protein', indent: true });
  });
});

describe('filterHits', () => {
  const hits = [
    hit({ label: 'A', evalue: 1e-30, source: 'Pfam' }),
    hit({ label: 'B', evalue: 0.5, source: 'SMART' }),
    hit({ label: 'C', evalue: null, source: 'pfam' }),
    hit({ label: 'D', evalue: 1e-3, source: null }),
  ];
  const labels = (hs: DomainHit[]) => hs.map((h) => h.label);

  it('keeps hits at or below the E-value threshold, and hits without one', () => {
    expect(labels(filterHits(hits, { evalueThreshold: 1e-3 }))).toEqual(['A', 'C', 'D']);
    expect(labels(filterHits(hits, { evalueThreshold: null }))).toEqual(['A', 'B', 'C', 'D']);
    expect(labels(filterHits(hits, { evalueThreshold: 0 }))).toEqual(['A', 'B', 'C', 'D']);
  });

  it('keeps the listed sources, case-insensitively', () => {
    expect(labels(filterHits(hits, { sources: ['Pfam'] }))).toEqual(['A', 'C']);
    expect(labels(filterHits(hits, { sources: [] }))).toEqual(['A', 'B', 'C', 'D']);
    expect(labels(filterHits(hits, { sources: ['Pfam'], evalueThreshold: 1e-10 }))).toEqual([
      'A',
      'C',
    ]);
  });

  it('ignores the source filter when no hit has a source', () => {
    const bare = [hit({ label: 'A' }), hit({ label: 'B' })];
    expect(hasSources(bare)).toBe(false);
    expect(labels(filterHits(bare, { sources: ['Pfam'] }))).toEqual(['A', 'B']);
  });
});

describe('capProteins', () => {
  const ps = sortProteins(proteinsOf(['p1', 'p2', 'p3', 'p4'].map((entity) => hit({ entity }))));

  it('keeps the first N and says so', () => {
    const c = capProteins(ps, 2);
    expect(c.shown.map((p) => p.entity)).toEqual(['p1', 'p2']);
    expect(c).toMatchObject({ total: 4, capped: true });
    expect(capProteins(ps, 10)).toMatchObject({ total: 4, capped: false });
  });

  it('keeps a protein picked elsewhere on screen', () => {
    expect(capProteins(ps, 2, ['p4']).shown.map((p) => p.entity)).toEqual(['p1', 'p2', 'p4']);
    expect(capProteins(ps, 2, ['p1']).shown.map((p) => p.entity)).toEqual(['p1', 'p2']);
  });
});

describe('legend and hit testing', () => {
  it('counts values, the most frequent first, ties by value', () => {
    const hs = ['B', 'A', 'B', 'C', 'A', 'D'].map((label) => hit({ label }));
    expect(valueCounts(hs, (h) => h.label, 3)).toEqual({
      items: [
        { value: 'A', count: 2 },
        { value: 'B', count: 2 },
        { value: 'C', count: 1 },
      ],
      more: 1,
    });
  });

  it('finds the domain under the pointer in its lane, the narrowest first', () => {
    const [p] = proteinsOf([
      hit({ start: 1, end: 100, label: 'wide' }),
      hit({ start: 40, end: 50, label: 'narrow' }),
      hit({ start: 120, end: 130, label: 'far' }),
    ]);
    // `wide` and `far` share lane 0, `narrow` is in lane 1.
    expect(p.domains[domainAt(p, 0, 45)].label).toBe('wide');
    expect(p.domains[domainAt(p, 1, 45)].label).toBe('narrow');
    expect(domainAt(p, 0, 110)).toBe(-1);
    expect(p.domains[domainAt(p, 0, 118.5, 1)].label).toBe('far');
  });
});

describe('virtualised rows', () => {
  const ps = proteinsOf([
    hit({ entity: 'a', start: 1, end: 10 }),
    hit({ entity: 'b', start: 1, end: 10 }),
    hit({ entity: 'b', start: 5, end: 12 }),
    hit({ entity: 'c', start: 1, end: 10 }),
  ]);
  const geometry = { padPx: 5, lanePx: 16, notePx: 22 };
  const heights = proteinRows(ps).map((r) => rowHeight(r, geometry));
  const offsets = rowOffsets(heights);

  it('sizes a row by its lanes', () => {
    expect(heights).toEqual([26, 42, 26]);
    expect(Array.from(offsets)).toEqual([0, 26, 68, 94]);
  });

  it('finds the row at an offset', () => {
    expect(rowAt(offsets, 0)).toBe(0);
    expect(rowAt(offsets, 25.9)).toBe(0);
    expect(rowAt(offsets, 26)).toBe(1);
    expect(rowAt(offsets, 93)).toBe(2);
    expect(rowAt(offsets, 94)).toBe(-1);
    expect(rowAt(offsets, -1)).toBe(-1);
  });

  it('windows the rows in view plus an overscan', () => {
    expect(rowWindow(offsets, 30, 20, 0)).toEqual([1, 1]);
    expect(rowWindow(offsets, 30, 20, 1)).toEqual([0, 2]);
    expect(rowWindow(offsets, 0, 0)).toEqual([0, -1]);
    expect(rowWindow(rowOffsets([]), 0, 100)).toEqual([0, -1]);
  });
});

describe('domainTooltip', () => {
  it('names the hit, its envelope, its HMM span, its partial side and its scores', () => {
    const h = hit({
      label: 'Pkinase',
      accession: 'PF00069',
      description: 'Protein kinase domain',
      source: 'Pfam',
      start: 30,
      end: 290,
      hmmFrom: 4,
      hmmTo: 264,
      hmmLength: 264,
      evalue: 3.2e-45,
      score: 152.34,
    });
    expect(domainTooltip(h, partialEdges(h), { evalueColumn: 'i_evalue' })).toEqual([
      'Pkinase (PF00069)',
      'Protein kinase domain',
      'Source Pfam',
      'Envelope 30-290 (261 aa)',
      'HMM 4-264 of 264 (99% coverage)',
      'Partial HMM match: start of the model missing',
      'i-Evalue 3.2e-45',
      'Score 152.3 bits',
    ]);
  });

  it('keeps to what a plain table has', () => {
    const h = hit({ label: 'A', start: 5, end: 9, coverage: 0.4 });
    expect(domainTooltip(h, partialEdges(h))).toEqual([
      'A',
      'Envelope 5-9 (5 aa)',
      'HMM coverage 40%',
      'Partial HMM match (by coverage, side unknown)',
    ]);
  });

  it('formats E-values', () => {
    expect(formatEvalue(0)).toBe('0');
    expect(formatEvalue(0.0123)).toBe('0.012');
    expect(formatEvalue(1.5e-12)).toBe('1.5e-12');
  });
});

describe('track geometry with a length-label gutter', () => {
  /** A fixed-pitch stand-in for `ctx.measureText`: 5.6 px a character. */
  const measure = (text: string) => text.length * 5.6;
  const VIEW_W = 620;
  const LABEL_COL = 96;
  const RIGHT_PAD = 8;
  const lengths = [65, 120, 252, 256];
  const longest = Math.max(...lengths);

  it('writes the label as the panel draws it', () => {
    expect(lengthLabel(256)).toBe('256 aa');
    expect(lengthLabel(12345)).toBe(`${(12345).toLocaleString()} aa`);
  });

  it('reserves the gap, the text and some padding', () => {
    const text = measure(lengthLabel(longest));
    expect(lengthGutter(text)).toBe(LENGTH_LABEL_GAP_PX + Math.ceil(text) + LENGTH_LABEL_PAD_PX);
    expect(lengthGutter(0)).toBe(0);
    expect(lengthGutter(Number.NaN)).toBe(0);
  });

  it('leaves a track as wide as before when no gutter is asked for', () => {
    expect(trackBox(VIEW_W, LABEL_COL, { rightPadPx: RIGHT_PAD })).toEqual({
      x: LABEL_COL + 6,
      w: VIEW_W - (LABEL_COL + 6) - RIGHT_PAD,
    });
  });

  it('shrinks the track by the gutter', () => {
    const gutterPx = lengthGutter(measure(lengthLabel(longest)));
    const bare = trackBox(VIEW_W, LABEL_COL, { rightPadPx: RIGHT_PAD });
    const box = trackBox(VIEW_W, LABEL_COL, { rightPadPx: RIGHT_PAD, gutterPx });
    expect(box.x).toBe(bare.x);
    expect(bare.w - box.w).toBe(gutterPx);
  });

  for (const scale of ['shared', 'per_protein'] as const) {
    it(`keeps the longest protein's label on the canvas on the ${scale} scale`, () => {
      const text = measure(lengthLabel(longest));
      const box = trackBox(VIEW_W, LABEL_COL, {
        rightPadPx: RIGHT_PAD,
        gutterPx: lengthGutter(text),
      });
      for (const length of lengths) {
        const ppr = pxPerResidue(box.w, scale, length, longest);
        const end = residueX(box.x, ppr, length);
        const labelEnd = end + LENGTH_LABEL_GAP_PX + measure(lengthLabel(length));
        // The backbone stays inside the track, its label inside the canvas.
        expect(end).toBeLessThanOrEqual(box.x + box.w + 1e-9);
        expect(labelEnd).toBeLessThanOrEqual(VIEW_W - RIGHT_PAD + 1e-9);
      }
    });

    it(`maps a residue to x and back with one mapping on the ${scale} scale`, () => {
      const box = trackBox(VIEW_W, LABEL_COL, { rightPadPx: RIGHT_PAD, gutterPx: 40 });
      for (const length of lengths) {
        const ppr = pxPerResidue(box.w, scale, length, longest);
        for (const pos of [0, 1, length / 2, length]) {
          expect(residueAt(box.x, ppr, residueX(box.x, ppr, pos))).toBeCloseTo(pos, 9);
        }
        // The last residue of the protein lies inside the track, the pointer
        // one pixel past the backbone's end does not map back onto it.
        expect(residueAt(box.x, ppr, residueX(box.x, ppr, length) + 1)).toBeGreaterThan(length);
      }
    });
  }

  it('fits the longest protein to the track on a shared scale and every one on a per-protein scale', () => {
    const box = trackBox(VIEW_W, LABEL_COL, { rightPadPx: RIGHT_PAD, gutterPx: 40 });
    expect(residueX(box.x, pxPerResidue(box.w, 'shared', longest, longest), longest)).toBeCloseTo(box.x + box.w);
    expect(residueX(box.x, pxPerResidue(box.w, 'shared', 65, longest), 65)).toBeLessThan(box.x + box.w);
    for (const length of lengths) {
      expect(residueX(box.x, pxPerResidue(box.w, 'per_protein', length, longest), length)).toBeCloseTo(box.x + box.w);
    }
  });

  it('caps the gutter on a tile too narrow for it, and never draws a track under 10 px', () => {
    const narrow = trackBox(200, LABEL_COL, { rightPadPx: RIGHT_PAD, gutterPx: 80 });
    const room = 200 - (LABEL_COL + 6) - RIGHT_PAD;
    expect(narrow.w).toBeGreaterThanOrEqual(room * 0.65 - 1e-9);
    expect(trackBox(50, LABEL_COL, { rightPadPx: RIGHT_PAD, gutterPx: 80 }).w).toBe(10);
  });
});

describe('labelColumnPx', () => {
  it('fits the widest label plus a pad when the tile has room', () => {
    expect(labelColumnPx(100, 1000)).toBe(112);
  });

  it('keeps the floor for a short label', () => {
    expect(labelColumnPx(10, 1000)).toBe(72);
  });

  it('caps a long identifier to a share of a narrow tile', () => {
    // 0.22 * 625 = 137.5, under both the widest label and the 200 px ceiling.
    expect(labelColumnPx(400, 625)).toBe(138);
    expect(labelColumnPx(400, 2000)).toBe(200);
  });

  it('never goes under the floor on a tiny or unmeasured tile', () => {
    expect(labelColumnPx(400, 100)).toBe(72);
    expect(labelColumnPx(400, 0)).toBe(72);
    expect(labelColumnPx(Infinity, 625)).toBe(138);
  });
});

describe('residue width', () => {
  const VIEW_W = 620;
  const LABEL_COL = 96;
  const opts = { rightPadPx: 8, gutterPx: 40, sharedLength: 256 };

  it('holds a whole number of px in 0..max, 0 for anything unusable', () => {
    expect(normaliseResidueWidth(7.6)).toBe(8);
    expect(normaliseResidueWidth(0)).toBe(0);
    expect(normaliseResidueWidth(-3)).toBe(0);
    expect(normaliseResidueWidth(1000)).toBe(RESIDUE_WIDTH_MAX_PX);
    expect(normaliseResidueWidth(null)).toBe(0);
    expect(normaliseResidueWidth(undefined)).toBe(0);
    expect(normaliseResidueWidth('abc')).toBe(0);
    expect(normaliseResidueWidth('12')).toBe(12);
  });

  it('keeps the fitted layout at width 0, and does not scroll', () => {
    const fitted = trackBox(VIEW_W, LABEL_COL, { rightPadPx: 8, gutterPx: 40 });
    expect(trackLayout(VIEW_W, LABEL_COL, { ...opts, residueWidth: 0 })).toEqual({
      ...fitted,
      contentW: VIEW_W,
      scrolls: false,
    });
    expect(trackLayout(VIEW_W, LABEL_COL, opts).scrolls).toBe(false);
  });

  it('makes the track N px per residue of the longest protein, with the gutter whole', () => {
    const box = trackLayout(VIEW_W, LABEL_COL, { ...opts, residueWidth: 8 });
    expect(box.x).toBe(LABEL_COL + 6);
    expect(box.w).toBe(8 * 256);
    expect(box.contentW).toBe(box.x + box.w + 40 + 8);
    expect(box.scrolls).toBe(true);
    expect(pxPerResidue(box.w, 'shared', 100, 256)).toBe(8);
  });

  it('stays in the tile when the explicit width is narrower than it', () => {
    const box = trackLayout(VIEW_W, LABEL_COL, { ...opts, residueWidth: 1, sharedLength: 100 });
    expect(box.w).toBe(100);
    expect(box.contentW).toBe(VIEW_W);
    expect(box.scrolls).toBe(false);
  });

  it('draws every backbone as wide as the longest on the per-protein scale', () => {
    const box = trackLayout(VIEW_W, LABEL_COL, { ...opts, residueWidth: 4 });
    for (const length of [65, 120, 256]) {
      const ppr = pxPerResidue(box.w, 'per_protein', length, 256);
      expect(residueX(box.x, ppr, length)).toBeCloseTo(box.x + 4 * 256, 9);
    }
  });

  it('maps a click back to the residue under it, scrolled or not', () => {
    const box = trackLayout(VIEW_W, LABEL_COL, { ...opts, residueWidth: 10 });
    const scrollLeft = 530;
    const origin = box.x - scrollLeft;
    for (const pos of [0, 37.5, 120, 256]) {
      const x = residueX(origin, 10, pos);
      expect(residueAt(origin, 10, x)).toBeCloseTo(pos, 9);
    }
  });

  it('finds the residues between two screen columns, clamped to the protein', () => {
    // Residue 0 sits 200 px left of the label column's edge (x = 100).
    const [a, b] = visibleResidues(-100, 10, 100, 500, 256);
    expect(a).toBeCloseTo(20, 9);
    expect(b).toBeCloseTo(60, 9);
    expect(visibleResidues(300, 10, 100, 500, 256)).toEqual([0, 20]);
    expect(visibleResidues(-5000, 10, 100, 500, 256)).toEqual([256, 256]);
    expect(visibleResidues(0, 0, 0, 100, 256)).toEqual([0, 0]);
  });
});
