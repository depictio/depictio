import { describe, it, expect } from 'vitest';
import { githubRawUrl } from '../catalog/githubRaw';
import { encodeBase64, decodeBase64 } from '../catalog/base64';
import { makeIsHeavy } from '../catalog/kinds';
import { metaFor, defaultRenderId, bindsOf, variantOf } from '../viz/renderMeta';
import { fixtureToColumnSpecs } from '../builder/columnSpecs';
import type { KindsMap, ParsedFixture, RenderSpec } from '../types';

describe('githubRawUrl', () => {
  it('rewrites blob and tree URLs to the raw host', () => {
    expect(githubRawUrl('https://github.com/o/r/blob/main/a.yml')).toBe(
      'https://raw.githubusercontent.com/o/r/main/a.yml',
    );
    expect(githubRawUrl('https://github.com/o/r/tree/main/dir')).toBe(
      'https://raw.githubusercontent.com/o/r/main/dir',
    );
  });

  it('leaves a non-GitHub URL alone', () => {
    expect(githubRawUrl('https://example.org/a')).toBe('https://example.org/a');
  });
});

describe('base64', () => {
  it('round-trips non-ASCII, which btoa alone cannot', () => {
    const text = 'id: café\ndescription: "coverage ≥ 30×"\n';
    expect(decodeBase64(encodeBase64(text))).toBe(text);
  });

  it('decodes the newline-wrapped base64 the GitHub contents API returns', () => {
    const b64 = encodeBase64('hello world');
    const wrapped = b64.replace(/(.{4})/g, '$1\n');
    expect(decodeBase64(wrapped)).toBe('hello world');
  });
});

const kinds: KindsMap = {
  volcano: { roles: { feature_id: ['String'] }, required_roles: ['feature_id'], heavy: false, label: 'Volcano' },
  embedding: { roles: { x: ['Float64'] }, required_roles: ['x'], heavy: true, label: 'Embedding' },
};

describe('makeIsHeavy', () => {
  it('reports the kinds depictio computes server-side', () => {
    const isHeavy = makeIsHeavy(kinds);
    expect(isHeavy('embedding')).toBe(true);
    expect(isHeavy('volcano')).toBe(false);
    expect(isHeavy('not_a_kind')).toBe(false);
  });
});

describe('renderMeta', () => {
  it('falls back to the type name for an unknown component', () => {
    expect(metaFor('nonsense').name).toBe('nonsense');
    expect(metaFor('figure').name).toBe('Figure');
  });

  it('derives a readable default render id per component', () => {
    expect(
      defaultRenderId({ uid: '1', component: 'figure', visu_type: 'histogram', dict_kwargs: { x: 'a' } }),
    ).toMatch(/histogram/);
    expect(defaultRenderId({ uid: '2', component: 'card', column: 'cov', aggregation: 'average' })).toMatch(
      /cov|average|card/,
    );
    expect(
      defaultRenderId({ uid: '3', component: 'advanced_viz', kind: 'volcano', roles: {} }),
    ).toMatch(/volcano/);
  });

  it('lists the column bindings a render declares', () => {
    const figure: RenderSpec = {
      uid: 'f',
      component: 'figure',
      visu_type: 'scatter',
      dict_kwargs: { x: 'a', y: 'b' },
    };
    expect(Object.fromEntries(bindsOf(figure))).toMatchObject({ x: 'a', y: 'b' });
  });

  it('names the variant a render renders as', () => {
    expect(
      variantOf({ uid: 'v', component: 'advanced_viz', kind: 'volcano', roles: {} }, kinds),
    ).toBeTruthy();
  });
});

describe('fixtureToColumnSpecs', () => {
  const fixture: ParsedFixture = {
    fileName: 'f.csv',
    delimiter: ',',
    columns: [
      { name: 'gene', dtype: 'String' },
      { name: 'cov', dtype: 'Int64' },
    ],
    rows: [
      { gene: 'A', cov: '10' },
      { gene: 'B', cov: '30' },
      { gene: 'A', cov: '20' },
    ],
    raw: 'gene,cov\nA,10\nB,30\nA,20\n',
  };

  it('precomputes the per-column specs depictio\'s builder reads from the API', () => {
    const specs = fixtureToColumnSpecs(fixture);
    expect(specs.map((s) => s.name)).toEqual(['gene', 'cov']);
    const cov = specs.find((s) => s.name === 'cov')!;
    expect(cov.type).toBeTruthy();
    // Without these the reused CardBuilder/ColumnSelect render empty.
    expect(cov.specs).toBeTruthy();
  });
});
