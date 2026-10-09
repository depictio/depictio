import { describe, expect, it, vi } from 'vitest';
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

import {
  finalizeGenomeSpy,
  isGenomeSpyLive,
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
