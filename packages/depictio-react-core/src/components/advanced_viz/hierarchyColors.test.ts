import { describe, expect, it } from 'vitest';

import { assignColors, semanticColor } from '../../palettes';
import {
  abundanceRanked,
  isLossLabel,
  isUnassigned,
  lineageIsOneHue,
  lineageShade,
  mixHex,
  remainderColour,
  ringColour,
  unassignedGrey,
} from './hierarchyColors';

describe('mixHex', () => {
  it('moves a colour toward another, and leaves a non-hex one alone', () => {
    expect(mixHex('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixHex('#c2255c', '#ffffff', 0)).toBe('#c2255c');
    expect(mixHex('#abc', '#fff', 1)).toBe('#ffffff');
    expect(mixHex('teal', '#ffffff', 0.5)).toBe('teal');
  });
});

describe('lineageShade', () => {
  it('keeps the lineage colour at its own level and lightens below it', () => {
    expect(lineageShade('#1098ad', 0, 3, false)).toBe('#1098ad');
    const child = lineageShade('#1098ad', 1, 0, false);
    const grandchild = lineageShade('#1098ad', 2, 0, false);
    const brightness = (h: string) => parseInt(h.slice(1, 3), 16) + parseInt(h.slice(3, 5), 16);
    expect(brightness(child)).toBeGreaterThan(brightness('#1098ad'));
    expect(brightness(grandchild)).toBeGreaterThan(brightness(child));
  });

  it('parts neighbouring siblings', () => {
    expect(lineageShade('#1098ad', 1, 0, false)).not.toBe(lineageShade('#1098ad', 1, 1, false));
  });
});

describe('isUnassigned', () => {
  it('knows the remainders, not the taxa', () => {
    expect(['Unclassified', 'unclassified_Bacteria', 'Other (12)', '', 'NA'].map(isUnassigned)).toEqual([
      true, true, true, true, true,
    ]);
    expect(['Bacteria', 'Otherwise', 'uncultured'].map(isUnassigned)).toEqual([false, false, false]);
  });

  it('reads the shared reserved values, as Python does', () => {
    expect(['Others', 'Rest', 'Undetermined', 'null', '-'].map(isUnassigned)).toEqual([
      true, true, true, true, true,
    ]);
  });
});

describe('remainderColour', () => {
  it('takes the shared semantic grey of the remainder, per scheme', () => {
    expect(remainderColour('Other (12)', false)).toBe(semanticColor('other', 'light'));
    expect(remainderColour('NA', true)).toBe(semanticColor('na', 'dark'));
    expect(remainderColour('Unclassified', false)).toBe(semanticColor('unclassified', 'light'));
    expect(remainderColour('', true)).toBe(semanticColor('na', 'dark'));
    expect(remainderColour('unknown', true)).toBe(unassignedGrey(true));
  });
});

describe('abundanceRanked', () => {
  const weight = new Map([['Bacteria', 90], ['Archaea', 5], ['Fungi', 5], ['Viruses', 1]]);

  it('orders by weight (ties alphabetical), then the unseen rest of the universe', () => {
    expect(abundanceRanked(weight, ['Zeta', 'Bacteria', 'Alpha', '', null])).toEqual([
      'Bacteria', 'Archaea', 'Fungi', 'Viruses', 'Alpha', 'Zeta',
    ]);
    expect(abundanceRanked(weight, null)).toEqual(['Bacteria', 'Archaea', 'Fungi', 'Viruses']);
  });

  it('gives the heaviest values the slots and the tail the Other grey', () => {
    const colours = assignColors(abundanceRanked(weight, null), {
      palette: ['#111111', '#222222'],
      ranked: true,
    });
    expect(colours.get('Bacteria')).toBe('#111111');
    expect(colours.get('Archaea')).toBe('#222222');
    expect(colours.get('Fungi')).toBe(semanticColor('other', 'light'));
    expect(colours.get('Viruses')).toBe(semanticColor('other', 'light'));
  });

  it('keeps a pin whatever its rank', () => {
    const colours = assignColors(abundanceRanked(weight, null), {
      pinned: { Viruses: '#e8590c' },
      palette: ['#111111', '#222222'],
      ranked: true,
    });
    expect(colours.get('Viruses')).toBe('#e8590c');
  });
});

describe('ringColour', () => {
  const opts = {
    localColourIdx: 1,
    colourMap: new Map([['Pseudomonadota', '#925FC4'], ['Acidobacteriota', '#F68B33']]),
    ringPins: [{ Bacteria: '#6495ED', Archaea: '#925FC4' }, null, null],
    grey: '#adb5bd',
    context: '#9aa1a8',
    isDark: false,
  };

  it('paints the ring above the colour-by rank with its own column pins', () => {
    const bacteria = { label: 'Bacteria', depth: 0, colourKey: null, unassigned: false };
    expect(ringColour(bacteria, 0, opts)).toBe('#6495ED');
    expect(ringColour({ ...bacteria, label: 'Eukaryota' }, 0, opts)).toBe('#9aa1a8');
  });

  it('paints the colour-by ring with the pinned colour itself, not a shade', () => {
    const phylum = { label: 'Pseudomonadota', depth: 1, colourKey: 'Pseudomonadota', unassigned: false };
    expect(ringColour(phylum, 0, opts)).toBe('#925FC4');
    expect(ringColour({ ...phylum, label: 'Acidobacteriota', colourKey: 'Acidobacteriota' }, 1, opts)).toBe('#F68B33');
  });

  it('shades the rings below the colour-by rank from it', () => {
    const cls = { label: 'Gammaproteobacteria', depth: 2, colourKey: 'Pseudomonadota', unassigned: false };
    expect(ringColour(cls, 0, opts)).toBe(lineageShade('#925FC4', 1, 0, false));
    expect(ringColour(cls, 0, opts)).not.toBe('#925FC4');
  });

  it('keeps a remainder grey', () => {
    expect(ringColour({ label: 'Unclassified', depth: 1, colourKey: 'Unclassified', unassigned: true }, 0, opts)).toBe('#adb5bd');
  });
});

describe('sankey loss and single-root colouring', () => {
  it('names a dead end', () => {
    expect(isLossLabel('Lost')).toBe(true);
    expect(isLossLabel(' filtered out ')).toBe(true);
    expect(isLossLabel('Quality filtered')).toBe(false);
  });
  it('one first-step value makes lineage one hue', () => {
    expect(lineageIsOneHue(['Input reads'])).toBe(true);
    expect(lineageIsOneHue(['Input reads', 'Lost', 'Unclassified'])).toBe(true);
    expect(lineageIsOneHue(['Bacteria', 'Archaea'])).toBe(false);
  });
});
