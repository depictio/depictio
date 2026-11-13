import { describe, expect, it } from 'vitest';

import { helpTopics, type HelpContext } from './help';

const BASE: HelpContext = {
  samples: false,
  sampleFollowsFilter: false,
  plate: false,
  hasZ: false,
  hasT: false,
  channels: 1,
  points: false,
  colourBy: null,
  pointsFollowPlane: false,
  selectable: false,
  labels: false,
};

const keys = (ctx: Partial<HelpContext>) => helpTopics({ ...BASE, ...ctx }).map((t) => t.key);

describe('helpTopics', () => {
  it('explains only what a plain 2D image offers', () => {
    expect(keys({})).toEqual(['move', 'channels', 'badges', 'open']);
  });

  it('adds a topic for each control the image has', () => {
    expect(
      keys({ samples: true, hasZ: true, points: true, selectable: true, labels: true }),
    ).toEqual(['move', 'pick', 'planes', 'channels', 'cells', 'select', 'labels', 'badges', 'open']);
  });

  it('names only the plane axes that exist', () => {
    const z = helpTopics({ ...BASE, hasZ: true }).find((t) => t.key === 'planes')!;
    expect(z.text).toMatch(/^Z moves/);
    expect(z.text).not.toMatch(/Time/);
    const t = helpTopics({ ...BASE, hasT: true }).find((t) => t.key === 'planes')!;
    expect(t.text).toMatch(/^Time steps/);
  });

  it('says a filter drives the sample when it does', () => {
    const pick = helpTopics({ ...BASE, samples: true, sampleFollowsFilter: true }).find(
      (t) => t.key === 'pick',
    )!;
    expect(pick.text).toMatch(/dashboard filter decides/);
  });

  it('mentions the channel limit only past it', () => {
    const text = (n: number) =>
      helpTopics({ ...BASE, channels: n }).find((t) => t.key === 'channels')!.text;
    expect(text(3)).not.toMatch(/at most/);
    expect(text(8)).toMatch(/at most 6 at once/);
  });

  it('names the colour column and the plane switch for cells', () => {
    const cells = helpTopics({
      ...BASE,
      points: true,
      colourBy: 'gfp_mean',
      pointsFollowPlane: true,
    }).find((t) => t.key === 'cells')!;
    expect(cells.text).toMatch(/coloured by gfp_mean/);
    expect(cells.text).toMatch(/All planes/);
  });
});
