import { describe, expect, it } from 'vitest';

import {
  absolutizeUris,
  breakpointTracks,
  buildBreakpointConfig,
  buildCircularOptions,
  circularTracks,
  jbrowseThemeFromMantine,
  type ExtraViewPayload,
} from './sessions';

const track = (trackId: string, type: string) => ({ trackId, type, name: trackId });

const payload = (over: Partial<ExtraViewPayload> = {}): ExtraViewPayload => ({
  assembly: { name: 'hg38', sequence: { type: 'ReferenceSequenceTrack' } },
  tracks: [
    track('genes', 'FeatureTrack'),
    track('cov', 'QuantitativeTrack'),
    track('bam-a', 'AlignmentsTrack'),
    track('sv', 'VariantTrack'),
    track('bam-b', 'AlignmentsTrack'),
  ],
  shown_track_ids: ['bam-a'],
  configuration: { rpc: { defaultDriver: 'MainThreadRpcDriver' } },
  sv_track_ids: ['sv'],
  ...over,
});

describe('breakpointTracks', () => {
  it('lists alignment tracks first, then variants, then the rest', () => {
    const ids = breakpointTracks(payload(), ['genes', 'sv', 'bam-b', 'cov', 'bam-a']).map(
      (t) => t.trackId,
    );
    expect(ids).toEqual(['bam-b', 'bam-a', 'sv', 'genes', 'cov']);
  });

  it('drops unknown ids and duplicates', () => {
    const ids = breakpointTracks(payload(), ['bam-a', 'gone', 'bam-a']).map((t) => t.trackId);
    expect(ids).toEqual(['bam-a']);
  });

  it('falls back to the shown tracks when no open id is known', () => {
    const ids = breakpointTracks(payload(), ['gone']).map((t) => t.trackId);
    expect(ids).toEqual(['bam-a']);
  });

  it('is empty when nothing is known at all', () => {
    expect(breakpointTracks(payload({ shown_track_ids: [] }), [])).toEqual([]);
  });
});

describe('buildBreakpointConfig', () => {
  const { config, trackIds } = buildBreakpointConfig(
    payload(),
    { locus: 'chr4:1782000-1783000', mateLocus: 'chr4:1736000-1737000', openTrackIds: ['bam-a', 'genes'] },
    { palette: { mode: 'light' } },
  );

  it('opens one BreakpointSplitView with the two loci, in order', () => {
    const session = config.defaultSession as { views: Array<Record<string, any>> };
    expect(session.views).toHaveLength(1);
    const view = session.views[0];
    expect(view.type).toBe('BreakpointSplitView');
    expect(view.init.views.map((v: { loc: string }) => v.loc)).toEqual([
      'chr4:1782000-1783000',
      'chr4:1736000-1737000',
    ]);
    for (const row of view.init.views) {
      expect(row.assembly).toBe('hg38');
      expect(row.tracks).toEqual(['bam-a', 'genes']);
    }
  });

  it('keeps the connections on and the two rows independent', () => {
    const view = (config.defaultSession as { views: Array<Record<string, unknown>> }).views[0];
    expect(view.showIntraviewLinks).toBe(true);
    expect(view.interactiveOverlay).toBe(true);
    expect(view.linkViews).toBe(false);
    expect(view.showHeader).toBe(true);
  });

  it('reuses the assembly and only the opened track configs verbatim', () => {
    expect(trackIds).toEqual(['bam-a', 'genes']);
    expect(config.assemblies[0]).toMatchObject({
      name: 'hg38',
      sequence: { type: 'ReferenceSequenceTrack' },
    });
    expect(config.tracks.map((t) => t.trackId)).toEqual(['bam-a', 'genes']);
  });

  it('merges the theme into the payload configuration', () => {
    expect(config.configuration).toEqual({
      rpc: { defaultDriver: 'MainThreadRpcDriver' },
      theme: { palette: { mode: 'light' } },
    });
  });
});

describe('circularTracks', () => {
  it('keeps the sv ids that exist and have a chord display', () => {
    const p = payload({ sv_track_ids: ['sv', 'gone', 'genes', 'sv'] });
    expect(circularTracks(p).map((t) => t.trackId)).toEqual(['sv']);
  });

  it('is empty when the payload carries no sv_track_ids', () => {
    expect(circularTracks(payload({ sv_track_ids: undefined }))).toEqual([]);
  });
});

describe('buildCircularOptions', () => {
  it('shows the sv tracks on the payload assembly in a CircularView', () => {
    const { options, trackIds } = buildCircularOptions(payload(), {});
    expect(trackIds).toEqual(['sv']);
    expect(options.assembly).toMatchObject({ name: 'hg38' });
    expect(options.tracks.map((t) => t.trackId)).toEqual(['sv']);
    const view = (options.defaultSession as { view: Record<string, any> }).view;
    expect(view.type).toBe('CircularView');
    expect(view.init).toEqual({ assembly: 'hg38', tracks: ['sv'] });
  });
});

describe('absolutizeUris', () => {
  it('anchors root-relative uris on the origin and leaves the rest alone', () => {
    const out = absolutizeUris(
      {
        a: { uri: '/depictio/api/v1/jbrowse/file?sig=1' },
        b: [{ uri: 'https://s3.example/x.bam' }],
        c: { name: '/not-a-uri' },
      },
      'https://host.example',
    );
    expect(out.a.uri).toBe('https://host.example/depictio/api/v1/jbrowse/file?sig=1');
    expect(out.b[0].uri).toBe('https://s3.example/x.bam');
    expect(out.c.name).toBe('/not-a-uri');
  });
});

describe('jbrowseThemeFromMantine', () => {
  const scale = (p: string) => Array.from({ length: 10 }, (_, i) => `${p}${i}`);
  const mantine = {
    primaryColor: 'indigo',
    colors: { indigo: scale('i'), teal: scale('t'), orange: scale('o'), blue: scale('b') },
  };

  it('picks the light shades in light mode', () => {
    expect(jbrowseThemeFromMantine(mantine, false)).toEqual({
      palette: {
        mode: 'light',
        primary: { main: 'i7' },
        secondary: { main: 'i6' },
        tertiary: { main: 't7' },
        quaternary: { main: 'o7' },
      },
    });
  });

  it('picks the lighter shades in dark mode', () => {
    const t = jbrowseThemeFromMantine(mantine, true) as { palette: Record<string, any> };
    expect(t.palette.mode).toBe('dark');
    expect(t.palette.primary.main).toBe('i4');
    expect(t.palette.secondary.main).toBe('i3');
  });

  it('falls back to blue for an unknown primary colour', () => {
    const t = jbrowseThemeFromMantine({ ...mantine, primaryColor: 'custom' }, false) as {
      palette: Record<string, any>;
    };
    expect(t.palette.primary.main).toBe('b7');
  });
});
