import { afterEach, describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import {
  announceDefaultRegion,
  defaultRegionEntries,
  defaultRegionGateOpen,
  defaultRegionNavigators,
  preannounceDefaultRegions,
  resetDefaultRegionGate,
  settleDefaultRegion,
  withdrawDefaultRegion,
} from './defaultRegionGate';

const region: InteractiveFilter[] = [
  { index: 'nav', value: ['chr2'], source: 'genome_selection', column_name: 'chrom' },
];

function gate(opts: {
  filters?: InteractiveFilter[];
  ownIndex?: string;
  startedAt?: number;
  now?: number;
}) {
  return defaultRegionGateOpen({
    entries: defaultRegionEntries(),
    ownIndex: opts.ownIndex ?? 'track',
    filters: opts.filters ?? [],
    startedAt: opts.startedAt ?? 0,
    now: opts.now ?? 100,
    timeoutMs: 2000,
  });
}

afterEach(() => resetDefaultRegionGate());

describe('defaultRegionGateOpen', () => {
  it('is open when no navigator announced a default region', () => {
    expect(gate({})).toBe(true);
  });

  it('holds a follower while a navigator is pending', () => {
    announceDefaultRegion('nav');
    expect(gate({})).toBe(false);
  });

  it('never holds the navigator on itself', () => {
    announceDefaultRegion('nav');
    expect(gate({ ownIndex: 'nav' })).toBe(true);
  });

  it('opens as soon as a region filter is in force', () => {
    announceDefaultRegion('nav');
    expect(gate({ filters: region })).toBe(true);
  });

  it('keeps holding right after emission, until the filter arrives', () => {
    announceDefaultRegion('nav');
    settleDefaultRegion('nav', true, 50);
    expect(gate({ now: 100 })).toBe(false);
    expect(gate({ now: 100, filters: region })).toBe(true);
  });

  it('opens when the navigator decided not to emit', () => {
    announceDefaultRegion('nav');
    settleDefaultRegion('nav', false);
    expect(gate({})).toBe(true);
  });

  it('opens when the navigator unmounts', () => {
    announceDefaultRegion('nav');
    withdrawDefaultRegion('nav');
    expect(gate({})).toBe(true);
  });

  it('opens after the timeout whatever the navigator does', () => {
    announceDefaultRegion('nav');
    expect(gate({ startedAt: 0, now: 2000 })).toBe(true);
  });

  it('ignores an emission older than the timeout', () => {
    announceDefaultRegion('nav');
    settleDefaultRegion('nav', true, 0);
    expect(gate({ startedAt: 2500, now: 2600 })).toBe(true);
  });
});

describe('pre-announced navigators (LazyMount gap)', () => {
  const navigator = (index: string, config: Record<string, unknown>) => ({
    index,
    component_type: 'advanced_viz',
    viz_kind: 'genome_view',
    config,
  });

  it('reads navigators off the stored config', () => {
    expect(
      defaultRegionNavigators([
        navigator('nav', { default_region: 'chr1:1-1000' }),
        navigator('blank', { default_region: '  ' }),
        navigator('off', { default_region: 'chr1:1-1000', region_filter_enabled: false }),
        { index: 'track', component_type: 'advanced_viz', viz_kind: 'coverage_track', config: {} },
      ]),
    ).toEqual(['nav']);
  });

  it('holds followers until the pre-announcement expires', () => {
    preannounceDefaultRegions(['nav'], 0, 2000);
    expect(gate({ startedAt: 0, now: 100 })).toBe(false);
    // Expired: a navigator that never mounted stops holding (the follower's
    // own timeout is pushed out so only the expiry is under test).
    expect(
      defaultRegionGateOpen({
        entries: defaultRegionEntries(),
        ownIndex: 'track',
        filters: [],
        startedAt: 1500,
        now: 2100,
        timeoutMs: 2000,
      }),
    ).toBe(true);
  });

  it('is taken over by the navigator when it mounts', () => {
    preannounceDefaultRegions(['nav'], 0, 2000);
    announceDefaultRegion('nav');
    expect(defaultRegionEntries().get('nav')).toEqual({ state: 'pending' });
  });

  it('is cleared when the navigator settles, and not re-announced', () => {
    preannounceDefaultRegions(['nav'], 0, 2000);
    settleDefaultRegion('nav', false);
    expect(defaultRegionEntries().has('nav')).toBe(false);
    preannounceDefaultRegions(['nav'], 0, 2000);
    expect(defaultRegionEntries().has('nav')).toBe(false);
  });
});
