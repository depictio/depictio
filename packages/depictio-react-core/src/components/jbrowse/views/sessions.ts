/**
 * Pure session builders for the extra JBrowse views (breakpoint split view and
 * circular view). Both reuse the `assembly` and `tracks` of the render payload,
 * so the proxied track URLs and their sanitisation are the ones the linear
 * view already uses; only the session differs. No React, no JBrowse imports,
 * so the logic is unit-testable in plain node.
 */

/** The slice of `JBrowseSessionResponse` these builders read. `sv_track_ids`
 *  and `mate_location` are written by the backend render; they are optional
 *  here so an older payload still builds a (track-less) circular view. */
export interface ExtraViewPayload {
  assembly: Record<string, unknown>;
  tracks: Array<Record<string, unknown> & { trackId: string }>;
  shown_track_ids?: string[];
  configuration?: Record<string, unknown>;
  sv_track_ids?: string[];
  mate_location?: string | null;
}

export interface BreakpointInputs {
  locus: string;
  mateLocus: string;
  openTrackIds: string[];
}

type TrackConf = ExtraViewPayload['tracks'][number];

/** Track types that carry reads: they are listed first in the split view, and
 *  they are the ones that draw the split-read and paired-read connections. */
const ALIGNMENT_TRACK_TYPES = new Set(['AlignmentsTrack', 'PileupTrack', 'SNPCoverageTrack']);

/** Track types JBrowse's circular view has a chord display for (the variant
 *  track's `ChordVariantDisplay`). Showing any other type would throw while the
 *  view opens it, so such a track is left out rather than breaking the view. */
const CIRCULAR_TRACK_TYPES = new Set(['VariantTrack']);

const trackType = (t: TrackConf): string => String(t.type ?? '');

export const isAlignmentTrack = (t: TrackConf): boolean => ALIGNMENT_TRACK_TYPES.has(trackType(t));

/** Rank of a track in the split view: reads, then variants (their breakends are
 *  drawn as connections too), then everything else. */
function breakpointRank(t: TrackConf): number {
  if (isAlignmentTrack(t)) return 0;
  if (trackType(t) === 'VariantTrack') return 1;
  return 2;
}

/**
 * The tracks the split view opens: the open ones that this payload still
 * knows about, alignment tracks first. The order within a rank follows
 * `openTrackIds`. When none of the open ids is known (a payload from another
 * filter state), the payload's own shown tracks stand in, so the view is never
 * an empty frame.
 */
export function breakpointTracks(payload: ExtraViewPayload, openTrackIds: string[]): TrackConf[] {
  const byId = new Map(payload.tracks.map((t) => [t.trackId, t]));
  const pick = (ids: string[]): TrackConf[] => {
    const seen = new Set<string>();
    const out: TrackConf[] = [];
    for (const id of ids) {
      const t = byId.get(id);
      if (t && !seen.has(id)) {
        seen.add(id);
        out.push(t);
      }
    }
    return out;
  };
  let chosen = pick(openTrackIds);
  if (chosen.length === 0) chosen = pick(payload.shown_track_ids ?? []);
  // Array.prototype.sort is stable: the open order survives inside a rank.
  return [...chosen].sort((a, b) => breakpointRank(a) - breakpointRank(b));
}

/** The tracks of the circular view: `sv_track_ids` that exist in the payload
 *  and have a chord display, in `sv_track_ids` order. */
export function circularTracks(payload: ExtraViewPayload): TrackConf[] {
  const byId = new Map(payload.tracks.map((t) => [t.trackId, t]));
  const seen = new Set<string>();
  const out: TrackConf[] = [];
  for (const id of payload.sv_track_ids ?? []) {
    const t = byId.get(id);
    if (t && !seen.has(id) && CIRCULAR_TRACK_TYPES.has(trackType(t))) {
      seen.add(id);
      out.push(t);
    }
  }
  return out;
}

/** The `config` that `createViewState` of `@jbrowse/react-app2` takes. */
export interface AppViewConfig {
  assemblies: Array<Record<string, unknown>>;
  tracks: TrackConf[];
  configuration: Record<string, unknown>;
  defaultSession: Record<string, unknown>;
}

const assemblyNameOf = (payload: ExtraViewPayload): string => String(payload.assembly.name ?? '');

/**
 * Session of the breakpoint split view: one `BreakpointSplitView` holding two
 * stacked linear views, the top on `locus` and the bottom on `mateLocus`, both
 * showing the same tracks. The view draws the connections by itself from the
 * features of the tracks open in both rows: split reads (supplementary
 * alignments) and discordant read pairs from alignment tracks, and breakends
 * from variant tracks. `showHeader` keeps the per-row locus boxes so the two
 * sides stay editable.
 */
export function buildBreakpointConfig(
  payload: ExtraViewPayload,
  inputs: BreakpointInputs,
  theme: Record<string, unknown>,
): { config: AppViewConfig; trackIds: string[] } {
  const assembly = assemblyNameOf(payload);
  const tracks = breakpointTracks(payload, inputs.openTrackIds);
  const trackIds = tracks.map((t) => t.trackId);
  const row = (loc: string) => ({ assembly, loc, tracks: trackIds });
  return {
    trackIds,
    config: {
      assemblies: [payload.assembly],
      tracks,
      configuration: { ...(payload.configuration ?? {}), theme },
      defaultSession: {
        name: 'depictio-breakpoint',
        views: [
          {
            id: 'depictio-breakpoint-view',
            type: 'BreakpointSplitView',
            showHeader: true,
            showIntraviewLinks: true,
            interactiveOverlay: true,
            linkViews: false,
            init: { views: [row(inputs.locus), row(inputs.mateLocus)] },
          },
        ],
      },
    },
  };
}

/** What `createViewState` of `@jbrowse/react-circular-genome-view2` takes. */
export interface CircularViewOptions {
  assembly: Record<string, unknown>;
  tracks: TrackConf[];
  configuration: Record<string, unknown>;
  defaultSession: Record<string, unknown>;
}

/** Session of the circular view: the SV tracks over the whole assembly. */
export function buildCircularOptions(
  payload: ExtraViewPayload,
  theme: Record<string, unknown>,
): { options: CircularViewOptions; trackIds: string[] } {
  const tracks = circularTracks(payload);
  const trackIds = tracks.map((t) => t.trackId);
  return {
    trackIds,
    options: {
      assembly: payload.assembly,
      tracks,
      configuration: { ...(payload.configuration ?? {}), theme },
      defaultSession: {
        name: 'depictio-circular',
        view: {
          id: 'depictio-circular-view',
          type: 'CircularView',
          // The container owns the height (see `CircularView.tsx`), so the
          // view's own drag handle would only fight it.
          hideVerticalResizeHandle: true,
          // JBrowse's own track selector would sit on top of the tile's
          // chrome; the tracks are the declared SV ones.
          hideTrackSelectorButton: true,
          init: { assembly: assemblyNameOf(payload), tracks: trackIds },
        },
      },
    },
  };
}

/** Absolute URLs for every `uri` key: JBrowse resolves a relative one against
 *  its own config base, not the page, so the API paths the backend returns are
 *  anchored on the page origin. Same rule as `JBrowseRenderer`. */
export function absolutizeUris<T>(node: T, origin: string): T {
  if (Array.isArray(node)) return node.map((n) => absolutizeUris(n, origin)) as unknown as T;
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      out[k] =
        k === 'uri' && typeof v === 'string' && v.startsWith('/')
          ? new URL(v, origin).toString()
          : absolutizeUris(v, origin);
    }
    return out as T;
  }
  return node;
}

/** The slice of the Mantine theme the JBrowse palette is derived from. */
export interface ThemeColors {
  primaryColor: string;
  colors: Record<string, readonly string[] | undefined>;
}

/**
 * JBrowse (MUI) palette taken from the Mantine theme, so the extra views wear
 * the dashboard's primary colour in light and dark. The same mapping as the
 * linear view's `jbTheme`, with no colour written here.
 */
export function jbrowseThemeFromMantine(
  mantine: ThemeColors,
  dark: boolean,
): Record<string, unknown> {
  const shade = (name: string, light: number, darkIdx: number): string => {
    const scale = mantine.colors[name] ?? mantine.colors.blue ?? [];
    return scale[dark ? darkIdx : light] ?? scale[scale.length - 1] ?? '';
  };
  const primary = mantine.primaryColor;
  return {
    palette: {
      mode: dark ? 'dark' : 'light',
      primary: { main: shade(primary, 7, 4) },
      secondary: { main: shade(primary, 6, 3) },
      tertiary: { main: shade('teal', 7, 4) },
      quaternary: { main: shade('orange', 7, 4) },
    },
  };
}
