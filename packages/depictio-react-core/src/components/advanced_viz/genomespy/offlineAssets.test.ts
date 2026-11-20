import { afterEach, describe, expect, it, vi } from 'vitest';

import { clearGeneAnnotationCache, loadGeneAnnotation } from './geneAnnotations';
import { fetchesFont, setGeneAssetSource, withEmbeddedFonts } from './offlineAssets';

describe('withEmbeddedFonts', () => {
  it('drops the bold lane title that sent every genome view to GitHub', () => {
    // The shape `buildDataLane` gives a titled lane.
    const spec = {
      vconcat: [
        {
          name: 'lane-0',
          title: { text: 'Coverage', orient: 'top', fontSize: 12, fontWeight: 'bold', color: '#333' },
          layer: [{ mark: { type: 'text', font: 'Lato', fontStyle: 'normal', size: 9 } }],
        },
      ],
    };
    const out = withEmbeddedFonts(spec);
    const title = (out.vconcat[0] as { title: Record<string, unknown> }).title;
    expect(title).toEqual({ text: 'Coverage', orient: 'top', fontSize: 12, color: '#333' });
    // The embedded font itself (Lato, normal, 400) is left as written.
    expect(out.vconcat[0].layer[0].mark).toEqual({
      type: 'text',
      font: 'Lato',
      fontStyle: 'normal',
      size: 9,
    });
    // The input is not mutated.
    expect(spec.vconcat[0].title.fontWeight).toBe('bold');
  });

  it('covers every font key GenomeSpy reads', () => {
    expect(fetchesFont('font', 'Roboto')).toBe(true);
    expect(fetchesFont('labelFont', 'Inter')).toBe(true);
    expect(fetchesFont('titleFontWeight', 700)).toBe(true);
    expect(fetchesFont('labelFontStyle', 'italic')).toBe(true);
    expect(fetchesFont('fontWeight', 400)).toBe(false);
    expect(fetchesFont('fontWeight', 'normal')).toBe(false);
    expect(fetchesFont('font', 'sans-serif')).toBe(false);
    expect(fetchesFont('fontSize', 30)).toBe(false);
  });

  it('returns the same object when nothing would be fetched', () => {
    const spec = { layer: [{ mark: 'rect' }], data: { values: [{ font: 'Roboto' }] } };
    // Data rows are not settings: never walked, never copied.
    expect(withEmbeddedFonts(spec)).toBe(spec);
  });
});

describe('loadGeneAnnotation with a host source', () => {
  afterEach(() => {
    setGeneAssetSource(null);
    clearGeneAnnotationCache();
    vi.unstubAllGlobals();
  });

  it('asks the host, never the network', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const asked: string[] = [];
    setGeneAssetSource(async (assembly) => {
      asked.push(assembly);
      return assembly === 'hg38'
        ? { assembly: 'hg38', columns: ['name', 'chrom', 'start', 'end'], genes: [['TP53', 'chr17', 1, 2]] }
        : null;
    });

    const hg38 = await loadGeneAnnotation('hg38');
    expect(hg38?.genes.map((g) => g.name)).toEqual(['TP53']);
    // Not shipped: no lane, and still no request.
    expect(await loadGeneAnnotation('mm10')).toBeNull();
    expect(asked).toEqual(['hg38', 'mm10']);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
