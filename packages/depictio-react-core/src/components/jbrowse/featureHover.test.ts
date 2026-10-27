import { describe, expect, it, vi } from 'vitest';

import type { JBrowseLocusSource } from '../../api';
import {
  createHoverTracker,
  hoverBand,
  hoverEventFromFeature,
  hoverFeatureOf,
  hoverRegion,
  recordToRegion,
  summariseFeature,
  watchFeatureHover,
  widenBand,
  type ReceivedHover,
} from './featureHover';

const source: JBrowseLocusSource = {
  dc_id: 'dc',
  chrom_column: 'chrom',
  start_column: 'pos',
  end_column: null,
};
const interval: JBrowseLocusSource = { ...source, start_column: 'start', end_column: 'end' };

/** A JBrowse feature: `get(key)` and `id()`. */
const feature = (id: string, data: Record<string, unknown>) => ({
  id: () => id,
  get: (key: string) => data[key],
});

describe('hoverEventFromFeature', () => {
  it('publishes the span 1-based, the name as entity and row key, and the row', () => {
    const ev = hoverEventFromFeature(
      { refName: 'chr8', start: 999, end: 1001, name: 'rs123' },
      source,
      ['8'],
    );
    expect(ev).toMatchObject({
      entity: 'rs123',
      rowKeys: ['rs123'],
      genomic: { refName: 'chr8', start: 1000, end: 1001, aliases: ['8'] },
      record: { chrom: 'chr8', pos: 1000 },
      positionColumn: '__genome__',
      start: 1000,
      end: 1001,
    });
  });

  it('falls back to the contig as entity when the feature has no name', () => {
    const ev = hoverEventFromFeature({ refName: 'chr8', start: 9, end: 10 }, null, ['8']);
    expect(ev.entity).toBe('chr8');
    expect(ev.entityAliases).toEqual(['8']);
    expect(ev.rowKeys).toBeUndefined();
    expect(ev.record).toBeUndefined();
  });

  it('never ends before it starts', () => {
    const ev = hoverEventFromFeature({ refName: 'c', start: 5, end: 5 }, null);
    expect(ev.start).toBe(6);
    expect(ev.end).toBe(6);
  });
});

describe('summariseFeature', () => {
  it('reads a JBrowse feature or a plain object', () => {
    expect(summariseFeature(feature('f1', { refName: 'c', start: 1, end: 4, name: 'x' }))).toEqual({
      id: 'f1',
      refName: 'c',
      start: 1,
      end: 4,
      name: 'x',
    });
    expect(summariseFeature({ refName: 'c', start: 1, end: 4 })).toMatchObject({ refName: 'c' });
  });

  it('drops an empty or VCF "." name, and anything without a span', () => {
    expect(summariseFeature(feature('f', { refName: 'c', start: 1, end: 2, name: '.' }))?.name).toBeUndefined();
    expect(summariseFeature(feature('f', { refName: 'c', start: 1 }))).toBeNull();
    expect(summariseFeature(null)).toBeNull();
  });
});

describe('hoverFeatureOf', () => {
  const read = feature('r1', { refName: 'c', start: 10, end: 20, name: 'read/1' });

  it('takes the fresh RPC feature of a feature display', () => {
    const d = { featureIdUnderMouse: 'r1', featureUnderMouse: read, features: { get: () => undefined } };
    expect(hoverFeatureOf(d)).toMatchObject({ name: 'read/1' });
  });

  it('stands in the rendered block copy for a stale RPC feature', () => {
    const stale = feature('old', { refName: 'c', start: 1, end: 2 });
    const d = { featureIdUnderMouse: 'r1', featureUnderMouse: stale, features: { get: () => read } };
    expect(hoverFeatureOf(d)).toMatchObject({ start: 10, end: 20 });
  });

  it('is null once the id is gone, whatever the stale feature says', () => {
    expect(hoverFeatureOf({ featureIdUnderMouse: undefined, featureUnderMouse: read })).toBeNull();
  });

  it('reads the pileup half of an alignments display, then its coverage half', () => {
    const bin = feature('bin', { refName: 'c', start: 5, end: 6 });
    const pileup = { featureIdUnderMouse: undefined };
    const coverage = { featureIdUnderMouse: 'bin', features: { get: () => bin } };
    expect(hoverFeatureOf({ PileupDisplay: pileup, SNPCoverageDisplay: coverage })).toMatchObject({
      start: 5,
    });
    const onRead = { featureIdUnderMouse: 'r1', features: { get: () => read } };
    expect(hoverFeatureOf({ PileupDisplay: onRead, SNPCoverageDisplay: coverage })).toMatchObject({
      name: 'read/1',
    });
  });

  it('reads the synthetic bin of a multi-wiggle display (no id)', () => {
    const bin = feature('mouseoverfeat', { refName: 'c', start: 7, end: 8 });
    expect(hoverFeatureOf({ featureUnderMouse: bin })).toMatchObject({ start: 7 });
  });
});

describe('createHoverTracker', () => {
  const a = { refName: 'c', start: 1, end: 2 };
  const b = { refName: 'c', start: 5, end: 6 };

  it('reports the display that spoke last, and hands the turn back on leave', () => {
    const t = createHoverTracker();
    const d1 = {};
    const d2 = {};
    expect(t.set(d1, a)).toBe(a);
    expect(t.set(d2, b)).toBe(b);
    expect(t.set(d2, null)).toBe(a);
    expect(t.set(d1, null)).toBeNull();
  });
});

describe('watchFeatureHover', () => {
  it('reports a change once, and not a display that never held a hover', async () => {
    const { observable, runInAction } = await import('mobx');
    const display = observable({
      featureIdUnderMouse: undefined as string | undefined,
      featureUnderMouse: undefined as unknown,
      features: { get: (_: string) => feature('r1', { refName: 'c', start: 1, end: 3 }) },
    });
    const view = observable({ tracks: [{ displays: [display] }] as Array<{ displays: unknown[] }> });
    const onHover = vi.fn();
    const stop = watchFeatureHover(view, onHover);
    expect(onHover).not.toHaveBeenCalled();
    runInAction(() => {
      display.featureIdUnderMouse = 'r1';
    });
    expect(onHover).toHaveBeenLastCalledWith(expect.objectContaining({ refName: 'c', start: 1 }));
    runInAction(() => {
      display.featureIdUnderMouse = undefined;
    });
    expect(onHover).toHaveBeenLastCalledWith(null);
    const calls = onHover.mock.calls.length;
    // A track closing with nothing hovered says nothing.
    runInAction(() => {
      view.tracks.splice(0, 1);
    });
    expect(onHover.mock.calls.length).toBe(calls);
    stop();
  });
});

describe('recordToRegion', () => {
  it('reads the contig and a point through the locus columns', () => {
    expect(recordToRegion({ chrom: 'chr8', pos: 1000 }, source)).toEqual({
      refName: 'chr8',
      start: 1000,
      end: 1000,
    });
  });

  it('reads an interval through the end column', () => {
    expect(recordToRegion({ chrom: 'chr8', start: 10, end: 20 }, interval)).toEqual({
      refName: 'chr8',
      start: 10,
      end: 20,
    });
  });

  it('coerces numeric strings and bigints, a numeric contig to text', () => {
    expect(recordToRegion({ chrom: 8, start: '10', end: BigInt(25) }, interval)).toEqual({
      refName: '8',
      start: 10,
      end: 25,
    });
  });

  it('is null for missing columns, unreadable or sub-1 positions, or no source', () => {
    expect(recordToRegion({ chrom: 'chr8' }, source)).toBeNull();
    expect(recordToRegion({ pos: 5 }, source)).toBeNull();
    expect(recordToRegion({ chrom: 'chr8', pos: 'n/a' }, source)).toBeNull();
    expect(recordToRegion({ chrom: 'chr8', pos: '' }, source)).toBeNull();
    expect(recordToRegion({ chrom: 'chr8', pos: 0 }, source)).toBeNull();
    expect(recordToRegion({ chrom: 'chr8', pos: 5 }, null)).toBeNull();
    expect(recordToRegion(null, source)).toBeNull();
  });

  it('treats an end before the start as a point', () => {
    expect(recordToRegion({ chrom: 'c', start: 20, end: 10 }, interval)?.end).toBe(20);
  });
});

describe('hoverRegion and hoverBand', () => {
  const canonical = (name: string) => ({ chr8: 'chr8', '8': 'chr8' })[name];
  const ev = (over: Partial<ReceivedHover>): ReceivedHover => ({
    sourceIndex: 'other',
    start: 1,
    ...over,
  });

  it('prefers the genomic field, then the record', () => {
    const g = { refName: 'chr8', start: 5, end: 9 };
    expect(hoverRegion(ev({ genomic: g, record: { chrom: 'chr1', pos: 1 } }), source)).toBe(g);
    expect(hoverRegion(ev({ record: { chrom: 'chr1', pos: 7 } }), source)).toMatchObject({
      refName: 'chr1',
      start: 7,
    });
    expect(hoverRegion(ev({}), source)).toBeNull();
  });

  it('draws a 0-based band from a genomic span, resolving an alias', () => {
    const band = hoverBand(
      ev({ genomic: { refName: 'NC_8', start: 100, end: 200, aliases: ['8'] } }),
      source,
      canonical,
      'hg38',
    );
    expect(band).toMatchObject({ refName: 'chr8', start: 99, end: 200, assemblyName: 'hg38' });
  });

  it('draws a band from a table row through the locus columns', () => {
    const band = hoverBand(ev({ record: { chrom: 'chr8', pos: 500 } }), source, canonical, 'hg38');
    expect(band).toMatchObject({ refName: 'chr8', start: 499, end: 500 });
  });

  it('ignores a row this tile has no columns for, and an unknown contig', () => {
    expect(hoverBand(ev({ record: { gene: 'TP53' }, entity: 'TP53' }), source, canonical, 'hg38')).toBeNull();
    expect(
      hoverBand(ev({ genomic: { refName: 'chrZ', start: 1, end: 2 } }), source, canonical, 'hg38'),
    ).toBeNull();
  });

  it('keeps the position-only rule for an event with no span fields', () => {
    expect(hoverBand(ev({ entity: 'chr8', start: 10 }), source, canonical, 'hg38')).toMatchObject({
      start: 9,
      end: 10,
    });
  });

  it('widens a band narrower than a few pixels about its centre', () => {
    const band = { refName: 'chr8', start: 999, end: 1000, assemblyName: 'hg38' };
    const wide = widenBand(band, 10);
    expect(wide.end - wide.start).toBeGreaterThanOrEqual(30);
    expect(wide.start).toBeLessThan(999);
    expect(wide.end).toBeGreaterThan(1000);
    // Already wide enough, or no scale known: untouched.
    expect(widenBand({ ...band, end: 2000 }, 10)).toEqual({ ...band, end: 2000 });
    expect(widenBand(band, undefined)).toBe(band);
  });
});
