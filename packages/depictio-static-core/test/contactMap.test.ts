/**
 * Parity of the contact-map window port with
 * depictio/api/v1/services/contact_map.py. The expected rows were produced by
 * calling the Python functions on the same inputs (levels below):
 * [span, pixels, target, choose_resolution, coarsest_within_budget(default
 * cells), coarsest_within_budget(max_cells=2000)].
 */
import { describe, expect, it } from 'vitest';

import {
  binOverlaps,
  chooseResolution,
  coarsestWithinBudget,
  resolveResolutionColumn,
} from '../src/contactMap';

const LEVELS = [5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
const PY: [number | null, number | null, number | null, number, number, number][] = [
  [null, null, null, 1000000, 1000000, 1000000], [null, 400, null, 1000000, 1000000, 1000000],
  [null, 1200, 0.5, 1000000, 1000000, 1000000], [null, 800, 0.1, 1000000, 1000000, 1000000],
  [0, null, null, 1000000, 1000000, 1000000], [0, 400, null, 1000000, 1000000, 1000000],
  [0, 1200, 0.5, 1000000, 1000000, 1000000], [0, 800, 0.1, 1000000, 1000000, 1000000],
  [1e5, null, null, 5000, 5000, 5000], [1e5, 400, null, 5000, 5000, 5000],
  [1e5, 1200, 0.5, 5000, 5000, 5000], [1e5, 800, 0.1, 5000, 5000, 5000],
  [2e5, null, null, 5000, 5000, 5000], [2e5, 400, null, 5000, 5000, 5000],
  [2e5, 1200, 0.5, 5000, 5000, 5000], [2e5, 800, 0.1, 5000, 5000, 5000],
  [1e6, null, null, 5000, 5000, 25000], [1e6, 400, null, 10000, 10000, 25000],
  [1e6, 1200, 0.5, 5000, 5000, 25000], [1e6, 800, 0.1, 10000, 10000, 25000],
  [3e6, null, null, 10000, 25000, 50000], [3e6, 400, null, 25000, 25000, 50000],
  [3e6, 1200, 0.5, 5000, 25000, 50000], [3e6, 800, 0.1, 50000, 50000, 50000],
  [1.5e7, null, null, 100000, 100000, 250000], [1.5e7, 400, null, 100000, 100000, 250000],
  [1.5e7, 1200, 0.5, 25000, 100000, 250000], [1.5e7, 800, 0.1, 250000, 250000, 250000],
  [5e7, null, null, 250000, 250000, 1000000], [5e7, 400, null, 500000, 500000, 1000000],
  [5e7, 1200, 0.5, 100000, 250000, 1000000], [5e7, 800, 0.1, 500000, 500000, 1000000],
  [2.48e8, null, null, 1000000, 1000000, 1000000], [2.48e8, 400, null, 1000000, 1000000, 1000000],
  [2.48e8, 1200, 0.5, 500000, 1000000, 1000000], [2.48e8, 800, 0.1, 1000000, 1000000, 1000000],
];

describe('contact map window port', () => {
  it.each(PY)('span %s px %s target %s', (span, px, target, chosen, budget, tight) => {
    const c = chooseResolution(LEVELS, span, px, target);
    expect(c).toBe(chosen);
    expect(coarsestWithinBudget(LEVELS, c, span)).toBe(budget);
    expect(coarsestWithinBudget(LEVELS, c, span, 2000)).toBe(tight);
  });

  it('matches the edge cases', () => {
    expect(chooseResolution([], 1e6)).toBeNull();
    expect(chooseResolution([0, -5, 7], 1e6)).toBe(7);
    expect(coarsestWithinBudget([], null, 1e6)).toBeNull();
    expect(coarsestWithinBudget([1000], null, null)).toBe(1000);
    expect(chooseResolution([1000, 4000], 3.2e6, 800, 1.0)).toBe(4000);
  });

  it('resolves the resolution column like the server', () => {
    expect(resolveResolutionColumn(['a', 'res'], 'res')).toBe('res');
    expect(resolveResolutionColumn(['a', 'resolution'], 'missing')).toBe('resolution');
    expect(resolveResolutionColumn(['a'], null)).toBeNull();
  });

  it('keeps a bin straddling the window edge, drops nulls', () => {
    // end column present
    expect(binOverlaps(90, 110, true, null, 100, 200)).toBe(true);
    expect(binOverlaps(90, 100, true, null, 100, 200)).toBe(false);
    // resolution stands in for the end
    expect(binOverlaps(95, null, false, 10, 100, 200)).toBe(true);
    expect(binOverlaps(90, null, false, 10, 100, 200)).toBe(false);
    // neither: start must be inside
    expect(binOverlaps(99, null, false, null, 100, 200)).toBe(false);
    expect(binOverlaps(200, 210, true, null, 100, 200)).toBe(false);
    expect(binOverlaps(null, 150, true, null, 100, 200)).toBe(false);
    expect(binOverlaps(150, null, true, null, 100, 200)).toBe(false);
  });
});

// ---- contactMapWindow against the server's contact_map_window ---------------
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { contactMapWindow, type ContactMapRequest } from '../src/contactMap';

interface Fixture {
  columns: Record<string, unknown[]>;
  masks: Record<string, number[]>;
  cases: {
    name: string;
    request: ContactMapRequest;
    resolution_col: string | null;
    mask: string | null;
    expected: Record<string, unknown>;
  }[];
}

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, '..', 'fixtures', 'contact-map-expected.json'), 'utf-8'),
) as Fixture;
const N = FIXTURE.columns.chrom.length;

describe('contactMapWindow = contact_map_window', () => {
  it.each(FIXTURE.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const cols = Object.fromEntries(
      Object.entries(FIXTURE.columns).filter(([k]) => c.resolution_col !== null || k !== 'resolution'),
    );
    const mask = c.mask ? FIXTURE.masks[c.mask] : null;
    const out = contactMapWindow(cols, N, mask, c.request, c.resolution_col);
    expect(out).toEqual(c.expected);
  });
});
