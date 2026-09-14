import { describe, expect, it } from 'vitest';

import { EMPTY_INGESTION_FILTERS, adminUrl, parseAdminUrl } from './adminUrlState';
import type { AdminRoute } from './adminUrlState';

const route = (overrides: Partial<AdminRoute>): AdminRoute => ({
  tab: 'users',
  pane: 'tasks',
  ingestion: { ...EMPTY_INGESTION_FILTERS },
  ...overrides,
});

describe('parseAdminUrl', () => {
  it('names no tab for a bare /admin, so the remembered tab can win', () => {
    expect(parseAdminUrl('/admin', '')).toEqual(route({ tab: null as never }));
    expect(parseAdminUrl('/admin/', '').tab).toBeNull();
  });

  it('reads a plain tab from the path', () => {
    expect(parseAdminUrl('/admin/backups', '').tab).toBe('backups');
  });

  it('opens Log & Task on the pane a monitoring path names', () => {
    expect(parseAdminUrl('/admin/ingestion', '')).toMatchObject({
      tab: 'monitoring',
      pane: 'ingestion',
    });
    expect(parseAdminUrl('/admin/logs/', '')).toMatchObject({ tab: 'monitoring', pane: 'logs' });
  });

  it('treats /admin/monitoring as the Tasks pane', () => {
    expect(parseAdminUrl('/admin/monitoring', '')).toMatchObject({
      tab: 'monitoring',
      pane: 'tasks',
    });
  });

  it('falls back on an unknown segment instead of blanking the page', () => {
    expect(parseAdminUrl('/admin/nope', '').tab).toBeNull();
  });

  it('reads the Ingestion filters from the query string', () => {
    expect(
      parseAdminUrl('/admin/ingestion', '?status=failed&instance=hpc%20a&project=abc123&q=rna'),
    ).toEqual(
      route({
        tab: 'monitoring',
        pane: 'ingestion',
        ingestion: { status: 'failed', instance: 'hpc a', projectId: 'abc123', q: 'rna' },
      }),
    );
  });

  it('drops a status this build does not know', () => {
    expect(parseAdminUrl('/admin/ingestion', '?status=exploded').ingestion.status).toBeNull();
  });

  it('ignores filters on any other path', () => {
    expect(parseAdminUrl('/admin/logs', '?status=failed').ingestion).toEqual(
      EMPTY_INGESTION_FILTERS,
    );
  });
});

describe('adminUrl', () => {
  it('writes a plain tab as its own segment', () => {
    expect(adminUrl(route({ tab: 'maintenance' }))).toBe('/admin/maintenance');
  });

  it('writes the monitoring tab as its pane', () => {
    expect(adminUrl(route({ tab: 'monitoring', pane: 'health' }))).toBe('/admin/health');
  });

  it('carries Ingestion filters in the query string, empty ones left out', () => {
    expect(
      adminUrl(
        route({
          tab: 'monitoring',
          pane: 'ingestion',
          ingestion: { status: 'abandoned', instance: null, projectId: 'abc123', q: '  ' },
        }),
      ),
    ).toBe('/admin/ingestion?status=abandoned&project=abc123');
    expect(adminUrl(route({ tab: 'monitoring', pane: 'ingestion' }))).toBe('/admin/ingestion');
  });

  it('keeps filters out of other panes and tabs', () => {
    const ingestion = { status: 'failed' as const, instance: 'hpc', projectId: null, q: 'x' };
    expect(adminUrl(route({ tab: 'monitoring', pane: 'logs', ingestion }))).toBe('/admin/logs');
    expect(adminUrl(route({ tab: 'users', pane: 'ingestion', ingestion }))).toBe('/admin/users');
  });

  it('round-trips through parseAdminUrl', () => {
    const original = route({
      tab: 'monitoring',
      pane: 'ingestion',
      ingestion: { status: 'interrupted', instance: 'Web UI', projectId: 'p1', q: 'rna, seq' },
    });
    const [pathname, search = ''] = adminUrl(original).split('?');
    expect(parseAdminUrl(pathname, `?${search}`)).toEqual(original);
  });
});
