import { describe, expect, it } from 'vitest';

import { columnProfiles } from './alignment';
import {
  CLUSTAL_COLOURS,
  clustalColour,
  hydrophobicityColour,
  identityColour,
  plddtBand,
  plddtIsFractional,
  schemeColour,
  zappoColour,
} from './residueColours';

describe('Clustal X', () => {
  it('colours a residue whose class holds the column', () => {
    const col = columnProfiles(['L', 'I', 'V', 'K'])[0];
    expect(clustalColour('L', col)).toEqual(CLUSTAL_COLOURS.hydrophobic);
    expect(clustalColour('K', col)).toBeNull();
  });

  it('always colours glycine and proline', () => {
    const col = columnProfiles(['G', 'A', 'A', 'A'])[0];
    expect(clustalColour('G', col)).toEqual(CLUSTAL_COLOURS.glycine);
  });
});

describe('per-residue schemes', () => {
  it('uses Zappo classes', () => {
    expect(zappoColour('d')).toEqual([255, 0, 0]);
    expect(zappoColour('X')).toBeNull();
  });

  it('runs the Kyte-Doolittle ramp from hydrophilic blue to hydrophobic red', () => {
    expect(hydrophobicityColour('I')).toEqual([255, 0, 0]);
    expect(hydrophobicityColour('R')).toEqual([0, 0, 255]);
  });

  it('never colours a gap', () => {
    expect(schemeColour('zappo', '-')).toBeNull();
    expect(schemeColour('none', 'A')).toBeNull();
  });
});

describe('percent identity', () => {
  it('shades only consensus residues, by agreement', () => {
    const col = columnProfiles(['A', 'A', 'A', 'A', 'K'])[0];
    expect(identityColour('A', col)).toEqual([153, 153, 255]);
    expect(identityColour('K', col)).toBeNull();
  });
});

describe('pLDDT bands', () => {
  it('uses the AlphaFold thresholds', () => {
    expect(plddtBand(95).key).toBe('very_high');
    expect(plddtBand(90).key).toBe('confident');
    expect(plddtBand(71).key).toBe('confident');
    expect(plddtBand(55).key).toBe('low');
    expect(plddtBand(20).key).toBe('very_low');
  });

  it('reads a 0-1 protein as fractions, decided once per protein', () => {
    expect(plddtIsFractional([0.2, 0.95, null])).toBe(true);
    expect(plddtIsFractional([0.5, 80])).toBe(false);
    expect(plddtBand(0.95, true).key).toBe('very_high');
  });
});
