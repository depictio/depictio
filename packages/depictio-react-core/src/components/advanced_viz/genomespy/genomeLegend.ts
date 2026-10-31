/**
 * The key to the colours a genome view's lanes wear when they come from the
 * genome browser's tracks (one colour per library, by the browser's `color_by`
 * or `color_scale`): the same key the browser shows, a ramp for a sequential
 * scale, over the values the drawn libraries carry.
 */
import { sequentialRamp } from '../../../categoryColors';
import type { GenomeTracksColourKey } from '../../jbrowse/genomeTracksStore';
import { foldByColour, keyTitle } from '../../jbrowse/trackLegend';
import type { GenomeLegend } from './genomeSpySpec';

/**
 * `samples` are the libraries the tile draws (a lane each, or the sample
 * column's values), `groupColours` the colour of each value of the browser's
 * column. Null when fewer than two values are drawn: one colour tells nothing
 * apart.
 */
export function browserKeyLegend(
  key: GenomeTracksColourKey | null | undefined,
  samples: readonly string[],
  groupColours: Readonly<Record<string, string>>,
): GenomeLegend | null {
  if (!key) return null;
  const used = new Set(
    samples.map((s) => key.sampleGroups[s]).filter((g): g is string => !!g && !!groupColours[g]),
  );
  const values = key.values.filter((v) => used.has(v));
  if (values.length < 2) return null;
  const title = keyTitle(key.column);
  if (key.ordered) {
    return {
      title,
      entries: [],
      ramp: {
        stops: sequentialRamp(key.scheme, 7),
        from: values[0],
        to: values[values.length - 1],
        values,
      },
    };
  }
  const entries = foldByColour(values.map((v) => ({ label: v, color: groupColours[v] })));
  return entries.length > 1 ? { title, entries, ramp: null } : null;
}
