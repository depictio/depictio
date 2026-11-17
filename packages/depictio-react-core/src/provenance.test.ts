import { describe, expect, it } from 'vitest';

import type { ImportHop } from './api';
import { provenanceBadge } from './provenance';

const hop = (over: Partial<ImportHop> = {}): ImportHop => ({
  source_instance: 'https://a.example',
  source_depictio_version: '1.19.0',
  bundle_format_version: 1,
  exported_at: null,
  imported_at: '2026-01-02T03:04:05',
  target_depictio_version: '1.20.3',
  bundle_sha256: null,
  migration_request_id: null,
  via: 'zip',
  ...over,
});

describe('provenanceBadge', () => {
  it('is legacy without any version', () => {
    for (const p of [null, undefined, { created_with_version: null, imported_from: [] }]) {
      const b = provenanceBadge(p, '1.20.3');
      expect(b.label).toBe('Depictio: unknown');
      expect(b.state).toBe('legacy');
      expect(b.tooltipLines).toEqual(['Created before version tracking']);
    }
  });

  it('is same on equal versions, ignoring a leading v', () => {
    const b = provenanceBadge({ created_with_version: '1.20.3', imported_from: [] }, 'v1.20.3');
    expect(b.label).toBe('Depictio v1.20.3');
    expect(b.state).toBe('same');
    expect(b.tooltipLines).toEqual(['Created with v1.20.3', 'Running instance: v1.20.3']);
  });

  it('is older when the project predates the running instance', () => {
    const b = provenanceBadge({ created_with_version: '1.9.0', imported_from: [] }, '1.10.0');
    expect(b.state).toBe('older');
  });

  it('is newer when the project is ahead of the running instance', () => {
    const b = provenanceBadge({ created_with_version: '2.0.0', imported_from: [] }, '1.20.3');
    expect(b.state).toBe('newer');
  });

  it('is unknown_running without a running version', () => {
    const b = provenanceBadge({ created_with_version: '1.0.0', imported_from: [] }, null);
    expect(b.state).toBe('unknown_running');
  });

  it('lists each import hop and falls back to the first hop version', () => {
    const b = provenanceBadge(
      {
        created_with_version: null,
        imported_from: [hop(), hop({ source_instance: 'b', source_depictio_version: null, via: 'cli' })],
      },
      '1.20.3',
    );
    expect(b.label).toBe('Depictio v1.19.0');
    expect(b.state).toBe('older');
    expect(b.tooltipLines).toContain(
      'Imported on 2026-01-02T03:04:05 from https://a.example (exported with v1.19.0, via zip)',
    );
    expect(b.tooltipLines).toContain('Imported on 2026-01-02T03:04:05 from b (via cli)');
  });
});
