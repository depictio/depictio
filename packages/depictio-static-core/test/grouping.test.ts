/**
 * Selection groups, colour-by and split: the TypeScript redraw against the
 * server's own figure.
 *
 * `fixtures/grouping-expected.json` is written by
 * `scripts/generate_grouping_fixture.py`: for each case, the binding the
 * producer ships, the request, and the figure `groups.py` + plotly-express
 * answer (annotated frame, `apply_*_kwargs`, `tidy_facet_layout`). `refillFigure`
 * must produce that figure from the binding and the bundled columns.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { BindingTable } from '../src/manifest';
import { refillFigure } from '../src/refill';
import {
  GROUP_COLUMN,
  groupingColumns,
  groupingRefusal,
  sanitizeColorByColumn,
  sanitizeGroupDefs,
  type GroupingRequest,
} from '../src/grouping';

interface Case {
  name: string;
  visu: string;
  binding: BindingTable;
  request: {
    groups?: { name: string; column_name: string; values: string[]; color: string }[];
    column?: string;
    colorMap?: Record<string, string>;
    display?: 'color' | 'facet';
    showOther?: boolean;
  };
  keep: number[] | null;
  expected: { data: Record<string, unknown>[]; layout: Record<string, unknown> };
}

const FIXTURE = JSON.parse(
  readFileSync(join(__dirname, '..', 'fixtures', 'grouping-expected.json'), 'utf-8'),
) as { columns: Record<string, unknown[]>; cases: Case[] };

const ROWS = Object.values(FIXTURE.columns)[0].length;

function toRequest(c: Case): GroupingRequest {
  const r = c.request;
  const base = { display: r.display, showOther: r.showOther };
  return r.groups
    ? { ...base, groups: r.groups, colorByGroup: true }
    : { ...base, colorByColumn: { columnName: r.column!, colorMap: r.colorMap } };
}

function maskOf(keep: number[] | null): Uint8Array | null {
  if (keep === null) return null;
  const mask = new Uint8Array(ROWS);
  for (const i of keep) mask[i] = 1;
  return mask;
}

/** Deep equality with a float tolerance and no regard to key order. */
function diff(a: unknown, b: unknown, path = ''): string | null {
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b)) ? null : `${path}: ${a} != ${b}`;
  }
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
      return `${path}: array ${JSON.stringify(a)?.slice(0, 80)} != ${JSON.stringify(b)?.slice(0, 80)}`;
    }
    for (let i = 0; i < a.length; i++) {
      const d = diff(a[i], b[i], `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (typeof a === 'object' && a !== null && typeof b === 'object' && b !== null) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) {
      const d = diff(
        (a as Record<string, unknown>)[k],
        (b as Record<string, unknown>)[k],
        `${path}.${k}`,
      );
      if (d) return d;
    }
    return null;
  }
  return a === b ? null : `${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`;
}

function columns(names: string[]): Promise<Record<string, ArrayLike<unknown>>> {
  const out: Record<string, ArrayLike<unknown>> = {};
  for (const n of names) {
    if (!(n in FIXTURE.columns)) throw new Error(`no column ${n}`);
    out[n] = FIXTURE.columns[n];
  }
  return Promise.resolve(out);
}

describe('grouped figure parity with the server', () => {
  for (const c of FIXTURE.cases) {
    it(c.name, async () => {
      const result = await refillFigure({
        binding: c.binding,
        columns,
        mask: maskOf(c.keep),
        grouping: toRequest(c),
      });
      expect(result.grouping, 'the figure was recoloured').toBeDefined();
      expect(result.figure.data).toHaveLength(c.expected.data.length);
      c.expected.data.forEach((trace, i) => {
        const d = diff(result.figure.data[i], trace, `data[${i}]`);
        expect(d, `${c.name}: ${d}`).toBeNull();
      });
      const layout = { ...result.figure.layout } as Record<string, unknown>;
      delete layout.template;
      const d = diff(layout, c.expected.layout, 'layout');
      expect(d, `${c.name}: ${d}`).toBeNull();
    });
  }

  it('reports what coloured the figure, as the server does', async () => {
    const groups = FIXTURE.cases[0];
    const byGroup = await refillFigure({
      binding: groups.binding,
      columns,
      mask: null,
      grouping: toRequest(groups),
    });
    expect(byGroup.grouping).toEqual({ groupColored: true, columnColored: null });
    const byColumn = FIXTURE.cases.find((k) => k.request.column === 'species')!;
    const col = await refillFigure({
      binding: byColumn.binding,
      columns,
      mask: null,
      grouping: toRequest(byColumn),
    });
    expect(col.grouping).toEqual({ groupColored: false, columnColored: 'species' });
  });
});

describe('what is left as built', () => {
  const base = FIXTURE.cases[0];

  it('draws the figure untouched without a request', async () => {
    const plain = await refillFigure({ binding: base.binding, columns, mask: null });
    const none = await refillFigure({ binding: base.binding, columns, mask: null, grouping: {} });
    expect(plain.grouping).toBeUndefined();
    expect(none.grouping).toBeUndefined();
    expect(none.figure.data).toHaveLength(plain.figure.data.length);
  });

  it('leaves a figure whose column the table lacks', async () => {
    const result = await refillFigure({
      binding: base.binding,
      columns,
      mask: null,
      grouping: { colorByColumn: { columnName: 'not_a_column' } },
    });
    expect(result.grouping).toBeUndefined();
  });

  it('refuses a binding with a trendline or a continuous colour', () => {
    const withTrend = {
      ...base.binding,
      trendlines: [{ i: 1, on: 0 }],
    } as BindingTable;
    expect(groupingRefusal(withTrend)).toMatch(/trendline/);
    const continuous = {
      ...base.binding,
      traces: [{ ...base.binding.traces[0], fields: { x: 'sepal_width', 'marker.color': 'petal_width' } }],
    } as BindingTable;
    expect(groupingRefusal(continuous)).toMatch(/colour scale/);
  });

  it('prefers groups over a column and lists what to project', () => {
    const request: GroupingRequest = {
      groups: [{ name: 'g', column_name: 'sid', values: ['s00'], color: '#e03131' }],
      colorByGroup: true,
      colorByColumn: { columnName: 'species' },
    };
    expect(groupingColumns(request)).toEqual(['sid']);
    expect(groupingColumns({ colorByColumn: { columnName: 'species' } })).toEqual(['species']);
    expect(groupingColumns(undefined)).toEqual([]);
  });
});

describe('sanitizing, as the server does at its trust boundary', () => {
  it('keeps well-formed groups, first name wins, "Other" is reserved', () => {
    const out = sanitizeGroupDefs([
      { name: ' A ', column_name: 'c', values: [1, 2], color: '#112233' },
      { name: 'A', column_name: 'c', values: ['x'], color: '#112233' },
      { name: 'Other', column_name: 'c', values: ['x'], color: '#112233' },
      { name: 'B', column_name: 'c', values: [], color: '#112233' },
      { name: 'C', column_name: ' ', values: ['x'], color: '#112233' },
      { name: 'D', column_name: 'c', values: ['x'], color: 'red' },
      'nope',
    ]);
    expect(out.map((g) => g.name)).toEqual(['A', 'D']);
    expect(out[0].values).toEqual(['1', '2']);
    // a colour that is not #rrggbb falls back to the tab10 slot of its position
    expect(out[1].color).toBe('#ff7f0e');
    expect(sanitizeGroupDefs('x')).toEqual([]);
  });

  it('drops a non-hex palette entry and an over-long column', () => {
    expect(
      sanitizeColorByColumn({ columnName: 'sp', colorMap: { a: '#abcdef', b: 'blue' } }),
    ).toEqual({ columnName: 'sp', colorMap: { a: '#abcdef' } });
    expect(sanitizeColorByColumn({ columnName: 'x'.repeat(201) })).toBeNull();
    expect(sanitizeColorByColumn({ columnName: ' ' })).toBeNull();
  });

  it('names the synthetic column the server uses', () => {
    expect(GROUP_COLUMN).toBe('__depictio_group__');
  });
});
