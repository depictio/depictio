import { describe, expect, it, vi } from 'vitest';
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

import {
  finalizeGenomeSpy,
  isGenomeSpyLive,
  pushOverlayRows,
  readScaleDomain,
  readViewDomain,
  restoreViewDomain,
  setGenomeSpyRows,
  zoomToRegion,
} from './useGenomeSpy';

function fakeEmbed() {
  const set = vi.fn();
  const zoomTo = vi.fn(async () => undefined);
  const api = {
    finalize: vi.fn(),
    datasets: { set },
    getScaleResolutionByName: () => ({ isZoomable: () => true, zoomTo }),
  } as unknown as EmbedResult;
  return { api, set, zoomTo };
}

const REGION = { chrom: 'chr1', start: 100, end: 200 };

describe('a live embed', () => {
  it('takes rows and zooms', async () => {
    const { api, set, zoomTo } = fakeEmbed();
    setGenomeSpyRows(api, [{ pos: 1 }]);
    setGenomeSpyRows(api, [{ start: 1 }], 'exons');
    await zoomToRegion(api, REGION);
    expect(set).toHaveBeenCalledTimes(2);
    expect(set).toHaveBeenLastCalledWith('exons', [{ start: 1 }]);
    expect(zoomTo).toHaveBeenCalledOnce();
  });
});

describe('an embed a viz control change tore down', () => {
  // The renderer's effects still hold it in the commit that replaces it, and
  // GenomeSpy throws on a data call through a finalized embed.
  it('skips rows and zoom instead of throwing', async () => {
    const { api, set, zoomTo } = fakeEmbed();
    finalizeGenomeSpy(api);
    expect(api.finalize).toHaveBeenCalledOnce();
    expect(isGenomeSpyLive(api)).toBe(false);
    setGenomeSpyRows(api, [{ pos: 1 }]);
    await zoomToRegion(api, REGION);
    expect(set).not.toHaveBeenCalled();
    expect(zoomTo).not.toHaveBeenCalled();
  });
});

describe('pushOverlayRows', () => {
  const rows = [{ chrom: 'chr1', start: 1, end: 9 }];

  it('prefers updateNamedData', () => {
    const { api, set } = fakeEmbed();
    const updateNamedData = vi.fn();
    (api as unknown as { updateNamedData: unknown }).updateNamedData = updateNamedData;
    expect(pushOverlayRows(api, 'depictioWindow', rows)).toBe('named');
    expect(updateNamedData).toHaveBeenCalledWith('depictioWindow', rows);
    expect(set).not.toHaveBeenCalled();
  });
  it('falls back to datasets.set', () => {
    const { api, set } = fakeEmbed();
    expect(pushOverlayRows(api, 'depictioHover', rows)).toBe('dataset');
    expect(set).toHaveBeenCalledWith('depictioHover', rows);
  });
  it('reports null when the embed has neither call or is finalized', () => {
    const bare = { finalize: vi.fn() } as unknown as EmbedResult;
    expect(pushOverlayRows(bare, 'depictioHover', rows)).toBeNull();
    const { api, set } = fakeEmbed();
    finalizeGenomeSpy(api);
    expect(pushOverlayRows(api, 'depictioHover', rows)).toBeNull();
    expect(set).not.toHaveBeenCalled();
  });
  it('treats a throwing source (undeclared name) as no overlay', () => {
    const api = {
      finalize: vi.fn(),
      updateNamedData: () => {
        throw new Error('no such source');
      },
    } as unknown as EmbedResult;
    expect(pushOverlayRows(api, 'depictioHover', rows)).toBeNull();
  });
});

describe('readScaleDomain', () => {
  it('reads the domain where the build exposes one', () => {
    const api = {
      finalize: vi.fn(),
      getScaleResolutionByName: () => ({ getScale: () => ({ domain: () => [10, 90] }) }),
    } as unknown as EmbedResult;
    expect(readScaleDomain(api)).toEqual([10, 90]);
  });
  it('is null otherwise', () => {
    expect(readScaleDomain({ finalize: vi.fn() } as unknown as EmbedResult)).toBeNull();
    const { api } = fakeEmbed();
    expect(readScaleDomain(api)).toBeNull();
  });
});

describe('keeping the view across a rebuild', () => {
  const VIEW = [
    { chrom: 'chr6', pos: 26_100_000 },
    { chrom: 'chr6', pos: 26_150_000 },
  ];

  it('reads the old embed as loci and puts them on the new one at once', async () => {
    const old = {
      finalize: vi.fn(),
      getScaleResolutionByName: () => ({ getComplexDomain: () => VIEW }),
    } as unknown as EmbedResult;
    const view = readViewDomain(old);
    expect(view).toEqual(VIEW);
    const { api, zoomTo } = fakeEmbed();
    expect(await restoreViewDomain(api, view)).toBe(true);
    expect(zoomTo).toHaveBeenCalledWith(VIEW, { duration: 0 });
  });

  it('reports false with no view, or one the new axis rejects', async () => {
    const { api } = fakeEmbed();
    expect(await restoreViewDomain(api, null)).toBe(false);
    const rejecting = {
      finalize: vi.fn(),
      getScaleResolutionByName: () => ({
        isZoomable: () => true,
        zoomTo: async () => {
          throw new Error('unknown contig');
        },
      }),
    } as unknown as EmbedResult;
    expect(await restoreViewDomain(rejecting, VIEW)).toBe(false);
  });
});
