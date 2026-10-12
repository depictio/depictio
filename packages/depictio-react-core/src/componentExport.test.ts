import { describe, expect, it } from 'vitest';

import { componentExportPath } from './api';

describe('componentExportPath', () => {
  it('names the format and theme, and nothing it was not given', () => {
    const path = componentExportPath('d1', 'c1', { format: 'json', theme: 'dark' });
    const [route, query] = path.split('?');
    expect(route).toBe('/depictio/api/v1/export/dashboards/d1/components/c1');
    expect(Object.fromEntries(new URLSearchParams(query))).toEqual({
      format: 'json',
      theme: 'dark',
    });
  });

  it('carries the filters as one URL-encoded JSON array', () => {
    const filters = [{ index: 'f1', value: ['soil & sand'] }];
    const path = componentExportPath('d1', 'c1', { format: 'html', theme: 'light', filters });
    const query = new URLSearchParams(path.split('?')[1]);
    expect(JSON.parse(query.get('filters') ?? '')).toEqual(filters);
  });

  it('leaves out empty filters and controls', () => {
    const path = componentExportPath('d1', 'c1', {
      format: 'json',
      theme: 'light',
      filters: [],
      controls: {},
    });
    expect(path).not.toContain('filters=');
    expect(path).not.toContain('controls=');
  });

  it('encodes ids that are not plain words', () => {
    const path = componentExportPath('d1', 'pr points/1', { format: 'json', theme: 'light' });
    expect(path).toContain('/components/pr%20points%2F1?');
  });
});
