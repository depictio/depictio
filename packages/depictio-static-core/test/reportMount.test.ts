import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { parseManifest, type BundleManifest } from '../src/manifest';
import {
  componentFor,
  groupMountVerdict,
  parseTileRefs,
  tileMountVerdict,
} from '../src/reportMount';

const FIXTURE = join(__dirname, '..', 'fixtures', 'manifest-basic.json');
const TABS_FIXTURE = join(__dirname, '..', 'fixtures', 'manifest-tabs.json');
const TAB = 'f1x70000000000000000c0de';

function fixture(): BundleManifest {
  return parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
}

describe('parseTileRefs', () => {
  it('reads one ref, several, and drops malformed tokens', () => {
    expect(parseTileRefs(`${TAB}:comp-card-1`)).toEqual([{ tabId: TAB, index: 'comp-card-1' }]);
    expect(parseTileRefs(` a:1  b:2\n c:3 `).map((r) => r.index)).toEqual(['1', '2', '3']);
    expect(parseTileRefs('no-colon :lead trail: ok:x')).toEqual([{ tabId: 'ok', index: 'x' }]);
    expect(parseTileRefs(null)).toEqual([]);
  });

  it('splits on the first colon only (an index may carry one)', () => {
    expect(parseTileRefs('tab:a:b')).toEqual([{ tabId: 'tab', index: 'a:b' }]);
  });
});

describe('tileMountVerdict', () => {
  it('mounts a live tile', () => {
    expect(tileMountVerdict(fixture(), { tabId: TAB, index: 'comp-text-1' })).toEqual({
      mount: true,
    });
  });

  it('mounts a frozen tile only while the report opens on the default state', () => {
    const m = fixture();
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-figure-1' }).mount).toBe(true);
    m.initial_filters = [{ index: 'comp-interactive-1', value: ['Adelie'] }];
    const verdict = tileMountVerdict(m, { tabId: TAB, index: 'comp-figure-1' });
    expect(verdict.mount).toBe(false);
    expect(verdict.mount === false && verdict.reason).toMatch(/default state/);
    // A live tile follows the filters, so the initial state does not matter.
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-text-1' }).mount).toBe(true);
  });

  it('keeps the fallback for an omitted tile, naming the reason', () => {
    const m = fixture();
    m.tiers['comp-card-1'] = { tier: 'omitted', detail: 'needs the server' };
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-card-1' })).toEqual({
      mount: false,
      reason: 'needs the server',
    });
  });

  it('keeps the fallback for a tab or a component the manifest does not hold', () => {
    const m = fixture();
    expect(tileMountVerdict(m, { tabId: 'other', index: 'comp-card-1' }).mount).toBe(false);
    expect(tileMountVerdict(m, { tabId: TAB, index: 'nope' }).mount).toBe(false);
    delete m.tiers['comp-text-1'];
    expect(tileMountVerdict(m, { tabId: TAB, index: 'comp-text-1' }).mount).toBe(false);
  });

  it('resolves components per tab of a family', () => {
    const m = parseManifest(JSON.parse(readFileSync(TABS_FIXTURE, 'utf-8')));
    for (const tab of m.tabs) {
      const meta = (tab.doc.stored_metadata as { index: string }[] | undefined) ?? [];
      for (const comp of meta) {
        expect(componentFor(m, { tabId: tab.id, index: comp.index })).not.toBeNull();
      }
    }
  });
});

describe('groupMountVerdict', () => {
  it('mounts a card row whole or not at all', () => {
    const m = fixture();
    const row = [
      { tabId: TAB, index: 'comp-card-1' },
      { tabId: TAB, index: 'comp-text-1' },
    ];
    expect(groupMountVerdict(m, row).mount).toBe(true);
    m.tiers['comp-card-1'] = { tier: 'omitted' };
    const verdict = groupMountVerdict(m, row);
    expect(verdict.mount).toBe(false);
    expect(verdict.mount === false && verdict.reason).toMatch(/^comp-card-1:/);
    expect(groupMountVerdict(m, []).mount).toBe(false);
  });
});
