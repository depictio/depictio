import { describe, expect, it } from 'vitest';

import type { BioimageZarrStore } from '../../../api';
import {
  firstLabelPath,
  normaliseWellName,
  openContainer,
  plateWells,
  subStore,
  wellForValue,
  wellImagePath,
} from './layout';

const enc = new TextEncoder();

/** An in-memory zarr store: key → JSON (or bytes). */
function memoryStore(files: Record<string, unknown>): BioimageZarrStore & { reads: string[] } {
  const reads: string[] = [];
  const bytes = (key: string) => {
    reads.push(key);
    const v = files[key.replace(/^\/+/, '')];
    if (v === undefined) return undefined;
    return v instanceof Uint8Array ? v : enc.encode(JSON.stringify(v));
  };
  return {
    reads,
    get: async (key) => bytes(key),
    getRange: async (key) => bytes(key),
  };
}

const PLATE_04 = {
  plate: {
    version: '0.4',
    rows: [{ name: 'A' }, { name: 'B' }],
    columns: [{ name: '1' }, { name: '2' }],
    wells: [
      { path: 'A/1', rowIndex: 0, columnIndex: 0 },
      { path: 'B/2', rowIndex: 1, columnIndex: 1 },
    ],
    field_count: 2,
  },
};

describe('normaliseWellName', () => {
  it.each([
    ['A1', 'A1'],
    ['A01', 'A1'],
    ['a/1', 'A1'],
    ['B_12', 'B12'],
    ['AA 003', 'AA3'],
  ])('%s reads as %s', (raw, want) => {
    expect(normaliseWellName(raw)).toBe(want);
  });

  it('keeps a name it cannot parse, upper-cased', () => {
    expect(normaliseWellName('ctrl-x')).toBe('CTRL-X');
  });
});

describe('plateWells', () => {
  it('names each well by its row and column', () => {
    expect(plateWells(PLATE_04.plate)).toEqual([
      { path: 'A/1', name: 'A1', row: 'A', column: '1' },
      { path: 'B/2', name: 'B2', row: 'B', column: '2' },
    ]);
  });

  it('falls back to the path when the indices point nowhere', () => {
    const wells = plateWells({ rows: [], columns: [], wells: [{ path: 'C/7' }] });
    expect(wells).toEqual([{ path: 'C/7', name: 'C7', row: 'C', column: '7' }]);
  });

  it('is empty for anything that is not a plate', () => {
    expect(plateWells(null)).toEqual([]);
    expect(plateWells({ wells: 'nope' })).toEqual([]);
  });
});

describe('wellForValue', () => {
  const wells = plateWells(PLATE_04.plate);
  it('matches a filter value in any spelling', () => {
    expect(wellForValue(wells, 'b02')?.path).toBe('B/2');
    expect(wellForValue(wells, 'A/1')?.path).toBe('A/1');
  });
  it('finds nothing for a well the plate does not have', () => {
    expect(wellForValue(wells, 'H12')).toBeNull();
  });
});

describe('openContainer', () => {
  it('reads an image (NGFF 0.4)', async () => {
    const store = memoryStore({ '.zattrs': { multiscales: [{ version: '0.4' }] } });
    expect(await openContainer(store)).toEqual({ layout: 'image', version: '0.4', wells: [] });
  });

  it('reads a plate (NGFF 0.5, zarr.json)', async () => {
    const store = memoryStore({
      'zarr.json': {
        zarr_format: 3,
        node_type: 'group',
        attributes: { ome: { version: '0.5', plate: PLATE_04.plate } },
      },
    });
    const opened = await openContainer(store);
    expect(opened.layout).toBe('plate');
    expect(opened.version).toBe('0.5');
    expect(opened.wells.map((w) => w.name)).toEqual(['A1', 'B2']);
  });

  it('reads a bioformats2raw container', async () => {
    const store = memoryStore({ '.zattrs': { 'bioformats2raw.layout': 3 } });
    expect((await openContainer(store)).layout).toBe('bioformats2raw');
  });

  it('says unknown for a group without NGFF metadata', async () => {
    expect((await openContainer(memoryStore({}))).layout).toBe('unknown');
  });
});

describe('wellImagePath', () => {
  it('opens the first field the well lists', async () => {
    const store = memoryStore({
      'B/2/.zattrs': { well: { images: [{ path: 'f0' }, { path: 'f1' }] } },
    });
    expect(await wellImagePath(store, 'B/2')).toBe('B/2/f0');
    expect(await wellImagePath(store, 'B/2', 1)).toBe('B/2/f1');
  });

  it('says why a well cannot be shown', async () => {
    const store = memoryStore({ 'A/1/.zattrs': { well: { images: [] } } });
    await expect(wellImagePath(store, 'A/1')).rejects.toThrow('Well A/1 lists no images');
  });
});

describe('firstLabelPath', () => {
  it('names the first label image the labels group lists', async () => {
    const store = memoryStore({ 'labels/.zattrs': { labels: ['nuclei', 'cells'] } });
    expect(await firstLabelPath(store)).toBe('labels/nuclei');
  });

  it('is null for an image without labels', async () => {
    expect(await firstLabelPath(memoryStore({}))).toBeNull();
  });
});

describe('subStore', () => {
  it('reads keys under a prefix, and composes', async () => {
    const root = memoryStore({ 'A/1/0/.zattrs': { x: 1 } });
    const field = subStore(subStore(root, 'A/1'), '0');
    expect(await field.get('.zattrs')).toBeDefined();
    expect(root.reads).toEqual(['A/1/0/.zattrs']);
  });

  it('is the store itself for an empty prefix', () => {
    const root = memoryStore({});
    expect(subStore(root, '')).toBe(root);
  });
});
