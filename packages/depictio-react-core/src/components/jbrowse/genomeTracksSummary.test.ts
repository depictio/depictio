import { describe, expect, it } from 'vitest';

import type { JBrowseSessionResponse, JBrowseTrackRow } from '../../api';
import {
  MAX_LISTED_TRACKS,
  buildGenomeTracksSummary,
  type GenomeSection,
} from './genomeTracksSummary';

const row = (over: Partial<JBrowseTrackRow>): JBrowseTrackRow => ({
  track_id: 't1',
  name: 'Coverage',
  format: 'bigwig',
  sample: null,
  selection_value: null,
  source: 'manifest',
  ...over,
});

const payload = (over: Partial<JBrowseSessionResponse> = {}): JBrowseSessionResponse => ({
  assembly: { name: 'asm', aliases: ['a1', 'a2'] },
  tracks: [],
  shown_track_ids: [],
  location: 'chr1:1-100',
  view: {},
  configuration: {},
  track_rows: [],
  selection_column: null,
  tracks_dc_id: 'dc',
  filter_applied: false,
  total_tracks: 0,
  matched_tracks: 0,
  truncated: false,
  data_version: null,
  assembly_kind: 'preset',
  ...over,
});

const section = (sections: GenomeSection[], id: GenomeSection['id']) =>
  sections.find((s) => s.id === id);
const value = (s: GenomeSection | undefined, label: string) =>
  s?.rows.find((r) => r.label === label)?.value;

describe('buildGenomeTracksSummary', () => {
  it('shows only the static config before the tile has rendered', () => {
    const out = buildGenomeTracksSummary(
      {
        assembly: 'hg19',
        location: 'chr2:5-50',
        locus_from: {
          data_collection_tag: 'variants',
          chrom_column: 'CHROM',
          start_column: 'POS',
          padding: 100,
          max_rows: 5,
        },
        ucsc_tracks: ['gc5Base'],
      },
      null,
      null,
    );
    expect(out.loaded).toBe(false);
    expect(out.sections.map((s) => s.id)).toEqual(['assembly', 'location', 'ucsc']);
    expect(value(section(out.sections, 'assembly'), 'Name')).toBe('hg19');
    expect(value(section(out.sections, 'assembly'), 'Source')).toBe('Built-in preset');
    const loc = section(out.sections, 'location');
    expect(value(loc, 'Initial')).toBe('chr2:5-50');
    expect(value(loc, 'Framed from')).toBe('variants (CHROM, POS)');
    expect(value(loc, 'Framing')).toBe('100 bp padding, up to 5 rows');
    expect(section(out.sections, 'ucsc')?.rows.map((r) => r.value)).toEqual(['gc5Base']);
  });

  it('frames from the primary source when locus_from is a list', () => {
    const out = buildGenomeTracksSummary(
      {
        locus_from: [
          { data_collection_tag: 'peaks', chrom_column: 'chr', start_column: 'start', name: 'ATAC' },
          { data_collection_tag: 'de', chrom_column: 'seqname', start_column: 'pos' },
        ],
      },
      null,
      null,
    );
    expect(value(section(out.sections, 'location'), 'Framed from')).toBe('peaks (chr, start)');
  });

  it('reads assembly name, aliases and kind from the payload', () => {
    const out = buildGenomeTracksSummary(
      {},
      payload({ assembly: { name: 'a', displayName: 'Assembly A', aliases: ['x'] }, assembly_kind: 'custom' }),
      null,
    );
    const asm = section(out.sections, 'assembly');
    expect(value(asm, 'Name')).toBe('Assembly A');
    expect(value(asm, 'Aliases')).toBe('x');
    expect(value(asm, 'Source')).toBe('Custom assembly');
  });

  it('puts the current locus ahead of the initial one', () => {
    const out = buildGenomeTracksSummary({}, payload(), 'chr1:10..20');
    const loc = section(out.sections, 'location');
    expect(loc?.rows.map((r) => r.label)).toEqual(['Now', 'Initial']);
  });

  it('groups the shown tracks by category with origin, index and storage', () => {
    const rows = [
      row({ track_id: 'a', name: 'A', category: 'Signal', uri: 'a.bw', storage: 'remote' }),
      row({
        track_id: 'b',
        name: 'B',
        format: 'bam',
        sample: 'S1',
        category: 'Reads',
        uri: 'b.bam',
        index_uri: 'b.bam.bai',
        storage: 'depictio',
      }),
      row({ track_id: 'c', name: 'C', category: 'Signal', storage: 'direct' }),
      row({ track_id: 'hidden', name: 'Hidden', category: 'Signal' }),
      row({ track_id: 'u', name: 'UCSC thing', source: 'ucsc', category: 'Genes' }),
    ];
    const out = buildGenomeTracksSummary(
      {},
      payload({ track_rows: rows, shown_track_ids: ['a', 'b', 'c', 'u'], total_tracks: 4 }),
      null,
    );
    const tracks = section(out.sections, 'tracks');
    expect(tracks?.groups?.map((g) => g.category)).toEqual(['Signal', 'Reads']);
    expect(tracks?.groups?.[0].tracks.map((t) => t.name)).toEqual(['A', 'C']);
    expect(tracks?.groups?.[0].tracks[0]).toEqual({
      name: 'A',
      detail: 'bigwig · read in place',
      origin: 'a.bw',
    });
    expect(tracks?.groups?.[1].tracks[0]).toEqual({
      name: 'B',
      detail: 'bam · S1 · ingested',
      origin: 'b.bam',
      index: 'b.bam.bai',
    });
    // UCSC tracks get their own section, not the list.
    expect(section(out.sections, 'ucsc')?.rows.map((r) => r.value)).toEqual(['UCSC thing']);
  });

  it('caps the track list and says how many are left out', () => {
    const rows = Array.from({ length: MAX_LISTED_TRACKS + 5 }, (_, i) =>
      row({ track_id: `t${i}`, name: `T${i}` }),
    );
    const out = buildGenomeTracksSummary(
      {},
      payload({ track_rows: rows, shown_track_ids: rows.map((r) => r.track_id) }),
      null,
    );
    const tracks = section(out.sections, 'tracks');
    expect(tracks?.groups?.[0].tracks).toHaveLength(MAX_LISTED_TRACKS);
    expect(tracks?.more).toBe(5);
  });

  it('says so when no track matches', () => {
    const out = buildGenomeTracksSummary({}, payload({ filter_applied: true }), null);
    expect(value(section(out.sections, 'tracks'), 'Open')).toBe('No track matches the filters');
  });

  it('reports live versus pinned data, counts and truncation', () => {
    const rows = [row({ track_id: 'a' }), row({ track_id: 'b' })];
    const live = buildGenomeTracksSummary(
      {},
      payload({
        track_rows: rows,
        shown_track_ids: ['a'],
        total_tracks: 9,
        filter_applied: true,
        matched_tracks: 3,
        truncated: true,
        max_tracks: 1,
        remote_base: 'https://host.example.org/run/',
      }),
      null,
    );
    const data = section(live.sections, 'data');
    expect(value(data, 'Version')).toBe('Live (latest ingest)');
    expect(value(data, 'Shown')).toBe('1 of 9 tracks, 3 match the filters');
    expect(value(data, 'Capped')).toBe('Only the first 1 matching tracks open');
    expect(data?.rows.find((r) => r.label === 'Remote folder')).toEqual({
      label: 'Remote folder',
      value: 'https://host.example.org/run/',
      uri: true,
    });

    const pinned = buildGenomeTracksSummary({}, payload({ data_version: 4 }), null);
    expect(value(section(pinned.sections, 'data'), 'Version')).toBe('Pinned to data version 4');
    expect(section(pinned.sections, 'data')?.rows.some((r) => r.label === 'Remote folder')).toBe(
      false,
    );
  });
});
