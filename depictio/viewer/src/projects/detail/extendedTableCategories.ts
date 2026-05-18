// Detection heuristics for "extended" table categories — table data collections
// whose column shape suggests a specialized Pydantic subclass on the backend.
//
// Today: only coordinates (DCTableCoordinatesConfig — lat_column + lon_column).
// A future category (e.g. volcano-plot tables → DCTableVolcanoConfig) gets its
// own detector here + its own banner block in the Create-DC modal — matching
// the Pydantic subclass story, no parallel registry abstraction.

export type CoordinatesGuess = { latColumn: string; lonColumn: string } | null;

const LAT_PATTERNS = [/^lat$/i, /^latitude$/i];
const LON_PATTERNS = [/^lon$/i, /^lng$/i, /^long$/i, /^longitude$/i];

export function detectCoordinatesColumns(columns: string[]): CoordinatesGuess {
  const lat = columns.find((c) => LAT_PATTERNS.some((re) => re.test(c.trim())));
  const lon = columns.find((c) => LON_PATTERNS.some((re) => re.test(c.trim())));
  if (!lat || !lon || lat === lon) return null;
  return { latColumn: lat, lonColumn: lon };
}
