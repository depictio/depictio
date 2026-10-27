import type { JBrowseTrackRow } from '../../api';
import { type CategoryColorSource, categoryColorMap } from '../../categoryColors';

type TrackConf = Record<string, unknown> & { trackId: string };

const ALIGNMENTS_DISPLAY = 'LinearAlignmentsDisplay';
const COVERAGE_DISPLAY = 'LinearSNPCoverageDisplay';

/**
 * The column the dashboard's colours for a sample are pinned under: the
 * component's selection column when it holds the sample (its values equal the
 * rows' sample), else ``sample``. The same name the filter bar and the other
 * tiles colour that column by, so one sample is one colour everywhere.
 */
export function sampleColourColumn(
  selectionColumn: string | null | undefined,
  rows: readonly JBrowseTrackRow[],
): string {
  if (!selectionColumn) return 'sample';
  const holdsSample = rows.some(
    (r) => r.sample != null && r.selection_value != null && r.selection_value === r.sample,
  );
  return holdsSample ? selectionColumn : 'sample';
}

/** Sample → colour over the distinct samples of the manifest rows, by the
 *  dashboard rule (pinned, then the colorway in sorted order, then grey). */
export function sampleColourMap(
  source: CategoryColorSource | null | undefined,
  column: string,
  rows: readonly JBrowseTrackRow[],
  palette?: readonly string[] | null,
): Map<string, string> {
  return categoryColorMap(
    source,
    column,
    rows.map((r) => r.sample),
    palette,
  );
}

/**
 * Colour each alignments track by its sample: the total-coverage histogram of
 * its SNP coverage display (``SNPCoverageRenderer.color``), the one colour
 * slot an alignments track has that JBrowse always draws (the pileup
 * renderer's ``color`` is ignored under the default colour scheme, which
 * paints reads by strand). Mismatch bases keep their base colours on top.
 *
 * Pure: returns new track configs. A track whose coverage renderer already
 * carries a ``color`` (set by the manifest or a config override) is left as it
 * is, and so is every track that is not an alignments track or has no sample.
 */
export function colourAlignmentTracks<T extends TrackConf>(
  tracks: readonly T[],
  rows: readonly JBrowseTrackRow[],
  colours: ReadonlyMap<string, string>,
): T[] {
  const sampleOf = new Map(rows.map((r) => [r.track_id, r.sample]));
  return tracks.map((track) => {
    if (track.type !== 'AlignmentsTrack') return track;
    const sample = sampleOf.get(track.trackId);
    const colour = sample ? colours.get(sample) : undefined;
    if (!colour) return track;

    const displays = (Array.isArray(track.displays) ? track.displays : []).map(
      (d) => ({ ...(d as Record<string, unknown>) }),
    );
    let display = displays.find((d) => d.type === ALIGNMENTS_DISPLAY);
    if (!display) {
      display = { type: ALIGNMENTS_DISPLAY, displayId: `${track.trackId}-${ALIGNMENTS_DISPLAY}` };
      displays.push(display);
    }
    const coverage = { ...((display.snpCoverageDisplay as Record<string, unknown>) ?? {}) };
    const renderers = { ...((coverage.renderers as Record<string, unknown>) ?? {}) };
    const renderer = { ...((renderers.SNPCoverageRenderer as Record<string, unknown>) ?? {}) };
    if (renderer.color) return track;

    renderer.color = colour;
    renderers.SNPCoverageRenderer = renderer;
    coverage.renderers = renderers;
    coverage.type ??= COVERAGE_DISPLAY;
    coverage.displayId ??= `${track.trackId}-${COVERAGE_DISPLAY}`;
    display.snpCoverageDisplay = coverage;
    return { ...track, displays };
  });
}

const WIGGLE_DISPLAY = 'LinearWiggleDisplay';
const WIGGLE_RENDERERS = ['XYPlotRenderer', 'LinePlotRenderer', 'DensityRenderer'] as const;

/**
 * A track's value of the manifest column the tile is coloured by (`color_by`):
 * the manifest row the backend keeps on each track config as `metadata`.
 * Null when the track has no such column (annotation, UCSC, extra tracks) or
 * holds nothing in it.
 */
export function conditionOf(track: TrackConf, column: string): string | null {
  const meta = track.metadata as Record<string, unknown> | undefined;
  const v = meta?.[column];
  if (v === null || v === undefined || v === '') return null;
  return String(v);
}

/** Condition → colour over the distinct values of `column` among the tracks,
 *  by the dashboard rule (pinned, then the colorway in sorted order). */
export function conditionColourMap(
  source: CategoryColorSource | null | undefined,
  column: string,
  tracks: readonly TrackConf[],
  palette?: readonly string[] | null,
): Map<string, string> {
  return categoryColorMap(
    source,
    column,
    tracks.map((t) => conditionOf(t, column)),
    palette,
  );
}

/**
 * Colour the tracks by a manifest column (`color_by`, e.g. the condition):
 * signal tracks get the colour on their plot renderers, alignments tracks on
 * their coverage histogram (as `colourAlignmentTracks` does per sample), so
 * every track of one condition is one colour. Pure: new configs, and a track
 * that already carries a renderer colour (manifest or config override), has no
 * value in the column, or is of another kind is returned as it is.
 */
export function colourTracksBy<T extends TrackConf>(
  tracks: readonly T[],
  column: string,
  colours: ReadonlyMap<string, string>,
): T[] {
  // Alignments go through the per-sample code with the condition standing in
  // for the sample, so the two share the one place that knows the layout.
  const rows: JBrowseTrackRow[] = tracks.map((t) => ({
    track_id: t.trackId,
    name: t.trackId,
    format: '',
    sample: conditionOf(t, column),
    selection_value: null,
  }));
  return colourAlignmentTracks(tracks, rows, colours).map((track) => {
    if (track.type !== 'QuantitativeTrack') return track;
    const colour = colours.get(conditionOf(track, column) ?? '');
    if (!colour) return track;
    const displays = (Array.isArray(track.displays) ? track.displays : []).map((d) => ({
      ...(d as Record<string, unknown>),
    }));
    let display = displays.find((d) => d.type === WIGGLE_DISPLAY);
    if (!display) {
      display = { type: WIGGLE_DISPLAY, displayId: `${track.trackId}-${WIGGLE_DISPLAY}` };
      displays.push(display);
    }
    const renderers = { ...((display.renderers as Record<string, unknown>) ?? {}) };
    // The manifest's own colour (`color` column) is the author's choice.
    if (WIGGLE_RENDERERS.some((name) => (renderers[name] as { color?: unknown } | undefined)?.color)) {
      return track;
    }
    for (const name of WIGGLE_RENDERERS) {
      renderers[name] = { ...((renderers[name] as Record<string, unknown>) ?? {}), color: colour };
    }
    display.renderers = renderers;
    return { ...track, displays };
  });
}
