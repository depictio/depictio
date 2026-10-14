import { describe, expect, it } from 'vitest';

import {
  countFavoured,
  isFavoured,
  labelAnchor,
  pointInPolygon,
  polygonPath,
  REGION_NOTE,
  regionAt,
  regionSet,
  regionSetFor,
  regionSetOfClass,
  type RegionSetName,
  type Vertex,
} from './regions';

const SQUARE: readonly Vertex[] = [
  [0, 0],
  [10, 0],
  [10, 10],
  [0, 10],
];

describe('pointInPolygon', () => {
  it('tells inside from outside a square', () => {
    expect(pointInPolygon(5, 5, SQUARE)).toBe(true);
    expect(pointInPolygon(15, 5, SQUARE)).toBe(false);
    expect(pointInPolygon(5, -1, SQUARE)).toBe(false);
  });

  it('handles a concave polygon', () => {
    const arrow: Vertex[] = [
      [0, 0],
      [10, 0],
      [10, 10],
      [5, 4],
      [0, 10],
    ];
    expect(pointInPolygon(2, 2, arrow)).toBe(true);
    // The notch between the two upper vertices is outside.
    expect(pointInPolygon(5, 8, arrow)).toBe(false);
  });

  it('is false for an empty polygon', () => {
    expect(pointInPolygon(0, 0, [])).toBe(false);
  });
});

describe('general-case regions', () => {
  it('puts the canonical alpha helix in alpha-R', () => {
    expect(regionAt(-57, -47, 'general')).toBe('alpha_r');
  });

  it('puts the canonical beta strand in beta', () => {
    expect(regionAt(-120, 130, 'general')).toBe('beta');
  });

  it('puts the left-handed helix in alpha-L', () => {
    expect(regionAt(60, 45, 'general')).toBe('alpha_l');
  });

  it('leaves the classic outlier outside every region', () => {
    expect(regionAt(60, -150, 'general')).toBeNull();
    expect(isFavoured(60, -150, 'general')).toBe(false);
  });

  it('continues the strand across the psi edge', () => {
    expect(regionAt(-120, -175, 'general')).toBe('beta');
  });

  it('keeps the bulk of the forbidden middle empty', () => {
    // phi near zero is sterically closed for every residue but glycine.
    expect(isFavoured(0, 0, 'general')).toBe(false);
    expect(isFavoured(0, 180, 'general')).toBe(false);
  });
});

describe('glycine and proline regions', () => {
  it('opens the mirror image of the general map for glycine', () => {
    // A general outlier is a favoured glycine: the map is point symmetric.
    expect(isFavoured(60, -150, 'glycine')).toBe(true);
    expect(isFavoured(57, 47, 'glycine')).toBe(true);
    expect(isFavoured(-57, -47, 'glycine')).toBe(true);
    expect(regionAt(-60, -30, 'glycine')).toBe('alpha_r');
  });

  it('is point symmetric for glycine', () => {
    for (const [phi, psi] of [
      [-57, -47],
      [-120, 130],
      [-100, 60],
      [-30, 100],
    ] as const) {
      expect(isFavoured(phi, psi, 'glycine')).toBe(isFavoured(-phi, -psi, 'glycine'));
    }
  });

  it('restricts proline to a narrow band of phi', () => {
    expect(regionAt(-65, -35, 'proline')).toBe('alpha_r');
    expect(regionAt(-65, 140, 'proline')).toBe('beta');
    expect(isFavoured(-150, -35, 'proline')).toBe(false);
    expect(isFavoured(60, 45, 'proline')).toBe(false);
  });

  it('draws no left-handed region for proline', () => {
    expect(regionSet('proline').some((r) => r.name === 'alpha_l')).toBe(false);
  });
});

describe('region sets', () => {
  it('picks the set of a class', () => {
    expect(regionSetOfClass('glycine')).toBe('glycine');
    expect(regionSetOfClass('proline')).toBe('proline');
    expect(regionSetOfClass('general')).toBe('general');
    // Pre-proline has no distribution of its own in the schematic.
    expect(regionSetOfClass('pre_proline')).toBe('general');
  });

  it('draws the glycine or proline set only for a plot filtered to that class', () => {
    expect(regionSetFor(null)).toBe('general');
    expect(regionSetFor([])).toBe('general');
    expect(regionSetFor(['glycine'])).toBe('glycine');
    expect(regionSetFor(['proline'])).toBe('proline');
    expect(regionSetFor(['pre_proline'])).toBe('general');
    expect(regionSetFor(['glycine', 'proline'])).toBe('general');
    expect(regionSetFor(['general', 'glycine'])).toBe('general');
  });

  it('keeps every vertex inside the plot window', () => {
    for (const set of ['general', 'glycine', 'proline'] as RegionSetName[]) {
      for (const region of regionSet(set)) {
        expect(region.polygon.length).toBeGreaterThanOrEqual(3);
        for (const [phi, psi] of region.polygon) {
          expect(phi).toBeGreaterThanOrEqual(-180);
          expect(phi).toBeLessThanOrEqual(180);
          expect(psi).toBeGreaterThanOrEqual(-180);
          expect(psi).toBeLessThanOrEqual(180);
        }
      }
    }
  });

  it('labels one polygon per region name at most per mirror image', () => {
    const labelled = regionSet('general').filter((r) => r.labelled);
    expect(labelled.map((r) => r.name).sort()).toEqual(['alpha_l', 'alpha_r', 'beta']);
  });
});

describe('countFavoured', () => {
  it('judges every residue against the regions of its own class', () => {
    const counts = countFavoured([
      { phi: -57, psi: -47, cls: 'general' },
      { phi: -120, psi: 130, cls: 'general' },
      { phi: 60, psi: -150, cls: 'general' },
      // The same point is fine for a glycine and not for a general residue.
      { phi: 60, psi: -150, cls: 'glycine' },
      { phi: -65, psi: -35, cls: 'proline' },
      { phi: 60, psi: 45, cls: 'proline' },
    ]);
    expect(counts).toEqual({ inside: 4, outside: 2 });
  });

  it('counts nothing for no residues', () => {
    expect(countFavoured([])).toEqual({ inside: 0, outside: 0 });
  });
});

describe('drawing helpers', () => {
  it('writes a polygon as a closed SVG path', () => {
    expect(polygonPath(SQUARE)).toBe('M0,0L10,0L10,10L0,10Z');
    expect(polygonPath([[-180, 100], [-45, 180], [-180, 180]])).toBe('M-180,100L-45,180L-180,180Z');
  });

  it('anchors a label at the mean of the vertices', () => {
    expect(labelAnchor(SQUARE)).toEqual([5, 5]);
    expect(labelAnchor([])).toEqual([0, 0]);
  });

  it('keeps the disclaimer the legend must carry', () => {
    expect(REGION_NOTE).toContain('approximate');
    expect(REGION_NOTE).toContain('not MolProbity contours');
  });
});
