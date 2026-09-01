/**
 * The TypeScript builder must produce what the Python model accepts: validate
 * a built state against the committed JSON schema snapshot.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { buildAnalysisState } from './analysisState';

const SCHEMA_PATH = resolve(
  __dirname,
  '../../../depictio/models/models/analysis_state.schema.json',
);

type Schema = Record<string, unknown> & { $defs?: Record<string, Schema> };

/** A small structural validator: enough of JSON Schema for this contract
 *  (object properties, required, enum/const, type, arrays, $ref, anyOf). */
function validate(value: unknown, schema: Schema, root: Schema, path: string, errors: string[]) {
  if (schema.$ref) {
    const name = String(schema.$ref).replace('#/$defs/', '');
    const target = root.$defs?.[name];
    if (!target) errors.push(`${path}: unknown $ref ${schema.$ref}`);
    else validate(value, target, root, path, errors);
    return;
  }
  if (Array.isArray(schema.anyOf)) {
    const branchErrors = (schema.anyOf as Schema[]).map((s) => {
      const errs: string[] = [];
      validate(value, s, root, path, errs);
      return errs;
    });
    if (!branchErrors.some((e) => e.length === 0)) {
      errors.push(`${path}: matches no anyOf branch (${JSON.stringify(value)})`);
    }
    return;
  }
  if (schema.const !== undefined && value !== schema.const) {
    errors.push(`${path}: expected const ${JSON.stringify(schema.const)}`);
  }
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) {
    errors.push(`${path}: ${JSON.stringify(value)} not in enum`);
  }
  const type = schema.type as string | undefined;
  if (type === 'object') {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      errors.push(`${path}: expected object`);
      return;
    }
    const props = (schema.properties ?? {}) as Record<string, Schema>;
    for (const key of (schema.required as string[] | undefined) ?? []) {
      if (!(key in (value as object))) errors.push(`${path}.${key}: required`);
    }
    for (const [key, v] of Object.entries(value as Record<string, unknown>)) {
      const sub = props[key];
      if (sub) validate(v, sub, root, `${path}.${key}`, errors);
      else if (schema.additionalProperties === false) errors.push(`${path}.${key}: unexpected`);
    }
    return;
  }
  if (type === 'array') {
    if (!Array.isArray(value)) {
      errors.push(`${path}: expected array`);
      return;
    }
    const items = schema.items as Schema | undefined;
    if (items) value.forEach((v, i) => validate(v, items, root, `${path}[${i}]`, errors));
    return;
  }
  if (type === 'string' && typeof value !== 'string') errors.push(`${path}: expected string`);
  if (type === 'integer' && !Number.isInteger(value)) errors.push(`${path}: expected integer`);
  if (type === 'number' && typeof value !== 'number') errors.push(`${path}: expected number`);
  if (type === 'boolean' && typeof value !== 'boolean') errors.push(`${path}: expected boolean`);
  if (type === 'null' && value !== null) errors.push(`${path}: expected null`);
}

describe('buildAnalysisState', () => {
  const schema = JSON.parse(readFileSync(SCHEMA_PATH, 'utf8')) as Schema;

  it('produces a document the committed schema accepts', () => {
    const state = buildAnalysisState({
      filters: [
        {
          index: 'filter-species',
          value: ['Adelie', 'Gentoo'],
          column_name: 'species',
          interactive_component_type: 'MultiSelect',
          metadata: { dc_id: 'dc1', column_name: 'species' },
        },
        {
          index: '__depictio_group__:dc1:individual_id',
          value: ['N1A1'],
          column_name: 'individual_id',
          interactive_component_type: 'MultiSelect',
          source: 'group_filter',
          metadata: { dc_id: 'dc1' },
        },
      ],
      groups: [
        {
          id: 'g1',
          name: 'Heavy Adelie',
          color: '#e64980',
          dcId: 'dc1',
          columnName: 'individual_id',
          values: ['N1A1'],
          createdAt: 1700000000000,
          filterActive: true,
        },
      ],
      colorBy: { kind: 'column', columnName: 'island' },
      displayMode: 'facet',
      showOther: true,
      showOverall: false,
      compareInCards: true,
      funnel: { enabled: true, order: ['filter-species'] },
      splitPanels: [
        {
          name: 'Biscoe',
          color: '#333',
          constraints: [
            {
              index: '__depictio_group__:panel:b',
              value: ['Biscoe'],
              column_name: 'island',
              interactive_component_type: 'MultiSelect',
              source: 'group_filter',
              metadata: { dc_id: 'dc1' },
            },
          ],
        },
      ],
      dashboardId: 'dash',
      familyId: 'fam',
      theme: 'dark',
    });
    const errors: string[] = [];
    validate(state, schema, schema, 'state', errors);
    expect(errors).toEqual([]);
    expect(state.version).toBe(1);
    expect(state.color_by).toEqual({ kind: 'column', column_name: 'island' });
    expect(state.groups[0].filter_active).toBe(true);
    expect(state.split_panels[0].constraints[0].metadata?.dc_id).toBe('dc1');
  });

  it('keeps an empty state minimal but valid', () => {
    const state = buildAnalysisState({
      filters: [],
      groups: [],
      colorBy: { kind: 'none' },
      displayMode: 'color',
      showOther: true,
      showOverall: true,
      compareInCards: false,
      funnel: { enabled: false, order: [] },
      splitPanels: [],
      dashboardId: 'dash',
      theme: 'light',
    });
    const errors: string[] = [];
    validate(state, schema, schema, 'state', errors);
    expect(errors).toEqual([]);
    expect(state.context.family_id).toBeNull();
  });
});
