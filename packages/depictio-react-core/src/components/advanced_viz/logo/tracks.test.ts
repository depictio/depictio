import { describe, expect, it } from 'vitest';

import {
  cleanTracks,
  COLLAPSED_TRACK_PX,
  stackTracks,
  trackSpans,
  trackState,
  TRACK_KEYS,
  type StackInput,
  type TrackKey,
} from './tracks';

const INPUTS: StackInput[] = [
  { lane: 'logo', track: null, h: 100 },
  { lane: 'consensus', track: 'consensus', h: 14 },
  { lane: 'rf', track: 'consensus', h: 12 },
  { lane: 'insertProb', track: 'insert', h: 12 },
  { lane: 'insertLength', track: 'insert', h: 12 },
  { lane: 'occupancy', track: 'occupancy', h: 18 },
  { lane: 'coverage', track: 'hits', h: 26 },
  { lane: 'hits', track: 'hits', h: 34 },
  { lane: 'ruler', track: 'ruler', h: 30 },
];

const set = (...t: TrackKey[]) => new Set<TrackKey>(t);

describe('trackState', () => {
  it('lets hidden win over collapsed and never touches a lane of no track', () => {
    expect(trackState('hits', set(), set())).toBe('shown');
    expect(trackState('hits', set(), set('hits'))).toBe('collapsed');
    expect(trackState('hits', set('hits'), set('hits'))).toBe('hidden');
    expect(trackState(null, set('hits'), set('hits'))).toBe('shown');
  });
});

describe('stackTracks', () => {
  it('stacks every lane contiguously when nothing is hidden or collapsed', () => {
    const s = stackTracks(INPUTS, set(), set());
    expect(s.slots.map((x) => x.lane)).toEqual(INPUTS.map((x) => x.lane));
    expect(s.total).toBe(258);
    s.slots.slice(1).forEach((x, i) => expect(x.y).toBe(s.slots[i].y + s.slots[i].h));
    expect(s.slots.every((x) => !x.collapsed)).toBe(true);
  });

  it('removes the lanes of a hidden track and closes the gap', () => {
    const s = stackTracks(INPUTS, set('insert'), set());
    expect(s.slots.map((x) => x.lane)).not.toContain('insertProb');
    expect(s.total).toBe(258 - 24);
    const occupancy = s.slots.find((x) => x.lane === 'occupancy')!;
    expect(occupancy.y).toBe(100 + 26);
  });

  it('turns a collapsed track into one thin strip', () => {
    const s = stackTracks(INPUTS, set(), set('consensus', 'hits'));
    const strips = s.slots.filter((x) => x.collapsed);
    expect(strips.map((x) => [x.track, x.lane, x.h])).toEqual([
      ['consensus', 'strip', COLLAPSED_TRACK_PX],
      ['hits', 'strip', COLLAPSED_TRACK_PX],
    ]);
    expect(s.slots.map((x) => x.lane)).toEqual(['logo', 'strip', 'insertProb', 'insertLength', 'occupancy', 'strip', 'ruler']);
    expect(s.total).toBe(100 + 10 + 24 + 18 + 10 + 30);
  });

  it('drops a track that is both hidden and collapsed', () => {
    const s = stackTracks(INPUTS, set('occupancy'), set('occupancy'));
    expect(s.slots.some((x) => x.track === 'occupancy')).toBe(false);
  });

  it('keeps only the logo when every track is hidden', () => {
    const s = stackTracks(INPUTS, new Set(TRACK_KEYS), set());
    expect(s.slots).toEqual([{ lane: 'logo', track: null, y: 0, h: 100, collapsed: false }]);
    expect(s.total).toBe(100);
  });

  it('keeps the logo when every track is collapsed', () => {
    const s = stackTracks(INPUTS, set(), new Set(TRACK_KEYS));
    expect(s.slots[0].lane).toBe('logo');
    expect(s.slots.slice(1).every((x) => x.collapsed && x.h === COLLAPSED_TRACK_PX)).toBe(true);
    expect(s.slots).toHaveLength(1 + TRACK_KEYS.length);
  });

  it('shows the hits alone when the other tracks are hidden', () => {
    const others = TRACK_KEYS.filter((t) => t !== 'hits');
    const s = stackTracks(INPUTS, new Set(others), set());
    expect(s.slots.map((x) => x.lane)).toEqual(['logo', 'coverage', 'hits']);
    expect(s.total).toBe(160);
  });

  it('draws no strip for a track whose lanes have no height', () => {
    const s = stackTracks([{ lane: 'logo', track: null, h: 50 }, { lane: 'hits', track: 'hits', h: 0 }], set(), set('hits'));
    expect(s.slots.map((x) => x.lane)).toEqual(['logo']);
  });

  it('does not mutate its inputs and is repeatable', () => {
    const copy = JSON.parse(JSON.stringify(INPUTS));
    const a = stackTracks(INPUTS, set('insert'), set('hits'));
    const b = stackTracks(INPUTS, set('insert'), set('hits'));
    expect(a).toEqual(b);
    expect(INPUTS).toEqual(copy);
  });
});

describe('trackSpans', () => {
  it('gives one extent per track, a strip when collapsed', () => {
    const s = stackTracks(INPUTS, set('occupancy'), set('hits'));
    expect(trackSpans(s.slots)).toEqual([
      { track: 'consensus', y: 100, h: 26, collapsed: false },
      { track: 'insert', y: 126, h: 24, collapsed: false },
      { track: 'hits', y: 150, h: 10, collapsed: true },
      { track: 'ruler', y: 160, h: 30, collapsed: false },
    ]);
  });
});

describe('cleanTracks', () => {
  it('keeps known names once, in track order', () => {
    expect(cleanTracks(['hits', 'bogus', 'consensus', 'hits', 3])).toEqual(['consensus', 'hits']);
    expect(cleanTracks(null)).toEqual([]);
    expect(cleanTracks('hits')).toEqual([]);
  });
});
